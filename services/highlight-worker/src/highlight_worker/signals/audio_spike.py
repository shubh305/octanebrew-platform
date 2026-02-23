"""Audio Spike detection via FFmpeg astats — adaptive z-score + transient + high-frequency energy."""

import asyncio
import logging
import math
import re

from . import BaseSignal

logger = logging.getLogger(__name__)

# Any dB value below this is treated as silence and clamped
_SILENCE_FLOOR_DB = -90.0

# Pattern matches ametadata=print outputs
_RMS_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(.*)")
_PEAK_RE = re.compile(r"lavfi\.astats\.Overall\.Peak_level=(.*)")


def _to_db(raw: str) -> float:
    """Parse dB string and clamp to silence floor."""
    try:
        v = float(raw)
        return max(v, _SILENCE_FLOOR_DB) if math.isfinite(v) else _SILENCE_FLOOR_DB
    except ValueError:
        return _SILENCE_FLOOR_DB


async def _rolling_zscore(values: list[float], window_size: int, silence_thresh: float = -50.0) -> list[float]:
    """Rolling z-score computation ignoring silence. Prevents steady noise from skewing baselines."""
    n = len(values)
    if n == 0:
        return []
    z_scores = [0.0] * n
    
    half = window_size // 2
    
    # We use a sliding window to maintain sum and sum of squares of 'active' values (>= silence_thresh)
    active_count = 0
    active_sum = 0.0
    active_sum_sq = 0.0
    
    # Initialize first window half (right side of center at i=0)
    for j in range(min(n, half + 1)):
        v = values[j]
        if v >= silence_thresh:
            active_count += 1
            active_sum += v
            active_sum_sq += v * v

    for i in range(n):
        # Result for current i
        if active_count >= 4:
            mean = active_sum / active_count
            variance = (active_sum_sq / active_count) - (mean * mean)
            std = max(0.0, variance) ** 0.5
            
            if std >= 0.5:
                z_scores[i] = (values[i] - mean) / std
        
        # Prepare window for next iteration (i+1)
        # 1. Remove element falling out of the left side
        left_out = i - half
        if left_out >= 0:
            v_out = values[left_out]
            if v_out >= silence_thresh:
                active_count -= 1
                active_sum -= v_out
                active_sum_sq -= v_out * v_out
        
        # 2. Add element entering the right side
        right_in = i + half + 1
        if right_in < n:
            v_in = values[right_in]
            if v_in >= silence_thresh:
                active_count += 1
                active_sum += v_in
                active_sum_sq += v_in * v_in
        
        # Yield to event loop every 5000 iterations
        if i % 5000 == 0:
            await asyncio.sleep(0)
            
    return z_scores


class AudioSpikeSignal(BaseSignal):
    """
    Adaptive audio spike detector using z-score over full-video RMS distribution.
    """

    @property
    def name(self) -> str:
        return "audio_spike"

    async def _collect_rms_samples(
        self, proxy_path: str, hop: float, extra_af: str = ""
    ) -> list[tuple[float, float, float]]:
        """
        Run ffmpeg astats and return list of (timestamp_s, rms_db, peak_db).
        Uses ametadata=print to continuously stream the metrics to stderr,
        avoiding buffering issues with long videos.
        """
        reset = max(1, int(round(1.0 / hop)))
        
        # Chain astats with ametadata to force constant printing
        af_filter = (
            f"astats=metadata=1:reset={reset},"
            f"ametadata=print:key=lavfi.astats.Overall.RMS_level,"
            f"ametadata=print:key=lavfi.astats.Overall.Peak_level"
        )
        if extra_af:
            af_filter = f"{extra_af},{af_filter}"

        cmd = ["ffmpeg", "-i", proxy_path, "-af", af_filter, "-f", "null", "-"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        
        results: list[tuple[float, float, float]] = []
        current_time = 0.0
        current_rms: float | None = None
        current_peak: float | None = None

        while True:
            line_bytes = await proc.stderr.readline()
            if not line_bytes:
                break
            
            line = line_bytes.decode("utf-8", errors="replace")
            
            # Looking for: [Parsed_ametadata_1 @ ...] lavfi.astats.Overall.RMS_level=-34.2
            m1 = _RMS_RE.search(line)
            if m1:
                current_rms = _to_db(m1.group(1))
                
            m2 = _PEAK_RE.search(line)
            if m2:
                current_peak = _to_db(m2.group(1))

            # When we've collected both for a given block, record it
            if current_rms is not None and current_peak is not None:
                results.append((current_time, current_rms, current_peak))
                current_time += hop
                current_rms = None
                current_peak = None
            
            # Yield to event loop to allow heartbeats
            await asyncio.sleep(0)

        await proc.wait()

        logger.info(
            f"AudioSpike: parsed {len(results)} continuous ametadata blocks "
            f"(hop={hop}s, reset={reset})"
        )
        return results

    async def detect(self, proxy_path: str, config: dict, **kwargs) -> dict[int, float]:
        hop = float(config.get("hop_size", 0.5))
        zscore_threshold = float(config.get("zscore_threshold", 2.0))
        transient_delta_db = float(config.get("transient_delta_db", 6.0))
        highfreq_boost = bool(config.get("highfreq_boost", False))
        window_seconds = float(config.get("window_seconds", 2.0))
        min_spike_count = int(config.get("min_spike_count", 2))

        logger.info(f"AudioSpike: config: hop {hop}, zscore_threshold {zscore_threshold}, transient_delta_db {transient_delta_db}, highfreq_boost {highfreq_boost}, window_seconds {window_seconds}, min_spike_count {min_spike_count}")

        # ── Primary full-spectrum pass 
        records = await self._collect_rms_samples(proxy_path, hop)
        if not records:
            logger.warning("AudioSpike: no astats samples parsed — skipping")
            return {}

        timestamps = [r[0] for r in records]
        rms_values = [r[1] for r in records]
        peak_values = [r[2] for r in records]

        # Use a 30-second rolling window
        samples_per_window = int(30.0 / hop) if hop > 0 else 60
        rms_z = await _rolling_zscore(rms_values, samples_per_window, silence_thresh=-50.0)
        
        active_rms = [v for v in rms_values if v >= -50.0]
        std_val = (sum((v - sum(active_rms)/len(active_rms))**2 for v in active_rms)/len(active_rms))**0.5 if active_rms else 0.0

        logger.info(
            f"AudioSpike: rms range [{min(rms_values):.1f}, {max(rms_values):.1f}] dB  "
            f"(active_samples={len(active_rms)}, active_std={std_val:.2f} dB)"
        )

        # ── Optional high-frequency pass 
        hf_spike_seconds: set[int] = set()
        if highfreq_boost:
            try:
                # Use a slightly lower z-score threshold for high-frequency to be more inclusive
                hf_zscore_threshold = zscore_threshold * 0.75
                hf_records = await self._collect_rms_samples(proxy_path, hop, extra_af="highpass=f=2000")
                if hf_records:
                    hf_rms = [r[1] for r in hf_records]
                    hf_z = await _rolling_zscore(hf_rms, samples_per_window, silence_thresh=-50.0)
                    for ts, z in zip([r[0] for r in hf_records], hf_z):
                        if z > hf_zscore_threshold:
                            hf_spike_seconds.add(int(ts))
                    logger.info(f"AudioSpike: high-freq pass → {len(hf_spike_seconds)} spike seconds")
            except Exception as e:
                logger.debug(f"AudioSpike: high-freq pass failed (non-fatal): {e}")

        # ── Per-hop scoring 
        hop_scores: list[tuple[float, float]] = []
        for i, (ts, rms_db, peak_db) in enumerate(zip(timestamps, rms_values, peak_values)):
            score = 0.0

            if rms_z[i] > zscore_threshold:
                score += 0.6

            # Transient: peak much louder than sustained RMS → gunshot / impact
            if abs(peak_db - rms_db) > transient_delta_db:
                score += 0.3

            if int(ts) in hf_spike_seconds:
                score += 0.3

            if score > 0:
                hop_scores.append((ts, min(1.0, score)))

        # ── Window aggregation 
        # ── Window aggregation (O(N) optimized) 
        spike_times = [t for t, _ in hop_scores]
        spike_map = {t: s for t, s in hop_scores}
        confirmed: dict[int, float] = {}

        right_idx = 0
        for i, (st, _) in enumerate(hop_scores):
            window_end = st + window_seconds
            while right_idx < len(spike_times) and spike_times[right_idx] <= window_end:
                right_idx += 1
            
            # spikes_in_window is spike_times[i : right_idx]
            if (right_idx - i) >= min_spike_count:
                sec = int(st)
                # Find max score in the current window. While this part is O(window), 
                best = max(spike_map[t] for t in spike_times[i:right_idx])
                confirmed[sec] = max(confirmed.get(sec, 0), best)
            
            if i % 1000 == 0:
                await asyncio.sleep(0)

        # Density control
        max_spikes_per_min = 45
        final_confirmed: dict[int, float] = {}
        sorted_secs = sorted(confirmed.keys())
        
        left_idx = 0
        recent_high_count = 0
        
        for i, sec in enumerate(sorted_secs):
            # Window is (sec - 60, sec]
            # 1. Slide left_idx to expel old ones
            while left_idx < i and sorted_secs[left_idx] <= sec - 60:
                if final_confirmed[sorted_secs[left_idx]] > 0.1:
                    recent_high_count -= 1
                left_idx += 1
            
            scale = 1.0
            if recent_high_count > max_spikes_per_min:
                scale = max(0.1, max_spikes_per_min / recent_high_count)
            
            score = confirmed[sec] * scale
            final_confirmed[sec] = score
            
            if score > 0.1:
                recent_high_count += 1
                
            if i % 1000 == 0:
                await asyncio.sleep(0)

        logger.info(
            f"AudioSpike: {len([s for s, v in final_confirmed.items() if v > 0.1])} high-value confirmed spike events "
            f"(z>{zscore_threshold}, hop={hop}s, window={window_seconds}s, min_spikes={min_spike_count})"
        )
        return final_confirmed
