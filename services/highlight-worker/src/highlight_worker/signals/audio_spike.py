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


def _rolling_zscore(values: list[float], window_size: int, silence_thresh: float = -50.0) -> list[float]:
    """Rolling z-score computation ignoring silence. Prevents steady noise from skewing baselines."""
    n = len(values)
    if n == 0:
        return []
    z_scores = [0.0] * n
    
    for i in range(n):
        start = max(0, i - window_size // 2)
        end = min(n, i + window_size // 2 + 1)
        
        active_vals = [v for v in values[start:end] if v >= silence_thresh]
        if len(active_vals) < 4:
            z_scores[i] = 0.0
            continue
            
        mean = sum(active_vals) / len(active_vals)
        std = (sum((v - mean) ** 2 for v in active_vals) / len(active_vals)) ** 0.5
        
        if std < 0.5:
            z_scores[i] = 0.0
        else:
            z_scores[i] = (values[i] - mean) / std
            
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
        _, stderr_data = await proc.communicate()
        stderr = stderr_data.decode("utf-8", errors="replace")

        results: list[tuple[float, float, float]] = []
        current_time = 0.0
        current_rms: float | None = None
        current_peak: float | None = None

        for line in stderr.split("\n"):
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
        rms_z = _rolling_zscore(rms_values, samples_per_window, silence_thresh=-50.0)
        
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
                    hf_z = _rolling_zscore(hf_rms, samples_per_window, silence_thresh=-50.0)
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
        spike_times = [t for t, _ in hop_scores]
        spike_map = {t: s for t, s in hop_scores}
        confirmed: dict[int, float] = {}

        for st, _ in hop_scores:
            window_end = st + window_seconds
            spikes_in_window = [t for t in spike_times if st <= t <= window_end]
            if len(spikes_in_window) >= min_spike_count:
                sec = int(st)
                best = max(spike_map[t] for t in spikes_in_window)
                confirmed[sec] = max(confirmed.get(sec, 0), best)

        # Density control: max spikes per rolling minute
        max_spikes_per_min = 45
        final_confirmed: dict[int, float] = {}
        
        for sec in sorted(confirmed.keys()):
            recent_high_value = sum(1 for s, v in final_confirmed.items() if (sec - 60 < s <= sec) and v > 0.1)
            
            scale = 1.0
            if recent_high_value > max_spikes_per_min:
                scale = max(0.1, max_spikes_per_min / recent_high_value)
                
            final_confirmed[sec] = confirmed[sec] * scale

        logger.info(
            f"AudioSpike: {len([s for s, v in final_confirmed.items() if v > 0.1])} high-value confirmed spike events "
            f"(z>{zscore_threshold}, hop={hop}s, window={window_seconds}s, min_spikes={min_spike_count})"
        )
        return final_confirmed
