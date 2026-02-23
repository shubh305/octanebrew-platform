"""Scene Change detection via FFmpeg — adaptive z-score + graded scoring + luminance boost.

The select filter MUST precede showinfo for scene scores to be computed.
Without it, showinfo outputs scene:0.000 for all frames.
"""

import asyncio
import logging
import re
from . import BaseSignal

logger = logging.getLogger(__name__)


class SceneChangeSignal(BaseSignal):
    """
    Adaptive scene change detector.

    Uses a very low base threshold on the select filter to collect raw scene
    scores from near-all frames, then applies z-score to detect relative spikes.
    This keeps the proven select+showinfo pipeline but makes the actual trigger
    adaptive rather than static.
    """

    @property
    def name(self) -> str:
        return "scene_change"

    @staticmethod
    def _zscore(values: list[float]) -> list[float]:
        n = len(values)
        if n < 4:
            return [0.0] * n
        mean = sum(values) / n
        std = (sum((v - mean) ** 2 for v in values) / n) ** 0.5
        if std < 1e-9:
            return [0.0] * n
        return [(v - mean) / std for v in values]

    async def detect(self, proxy_path: str, config: dict, **kwargs) -> dict[int, float]:
        collection_threshold = float(config.get("base_threshold", 0.10))
        zscore_threshold = float(config.get("zscore_threshold", 2.0))
        dynamic_interval = bool(config.get("dynamic_interval", True))
        luminance_boost = bool(config.get("luminance_boost", True))
        luminance_delta_threshold = float(config.get("luminance_delta_threshold", 20.0))

        # ── Collect scene scores via scdet + showinfo
        cmd = [
            "ffmpeg", "-i", proxy_path,
            "-vf", "scale=160:-2,scdet=t=0.01,showinfo",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stderr_lines = []
        while True:
            line_bytes = await proc.stderr.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace")
            stderr_lines.append(line)
            await asyncio.sleep(0)

        await proc.wait()
        stderr = "".join(stderr_lines)

        # Parse output like:
        # [scdet @ ...] lavfi.scd.score: 0.810, lavfi.scd.time: 0.0333333
        # [Parsed_showinfo_1 @ ...] ... mean:[104 123 137] ...
        
        scdet_re = re.compile(r"lavfi\.scd\.score:\s*(\d+\.?\d*).*?lavfi\.scd\.time:\s*(\d+\.?\d*)")
        meany_re = re.compile(r"mean:\[(\d+)\s")

        frames: list[tuple[float, float, float]] = []
        
        current_time = 0.0
        current_score = 0.0

        for line in stderr.split("\n"):
            scd_m = scdet_re.search(line)
            if scd_m:
                current_score = float(scd_m.group(1))
                current_time = float(scd_m.group(2))
                continue
            
            my_m = meany_re.search(line)
            if my_m:
                mean_y = float(my_m.group(1))
                if current_time > 0:
                    frames.append((current_time, current_score, mean_y))
                    current_time = -1.0

        if not frames:
            logger.info("SceneChange: no frames with scene scores detected")
            return {}

        scene_values = [f[1] for f in frames]
        max_scene = max(scene_values)
        logger.info(
            f"SceneChange: {len(frames)} candidate frames, "
            f"scene range [0, {max_scene:.3f}]"
        )

        zscores = self._zscore(scene_values)

        # ── Score events
        scores: dict[int, float] = {}
        last_time = -999.0
        prev_mean_y: float | None = None

        for i, (pts_time, scene_val, mean_y) in enumerate(frames):
            z = zscores[i]
            graded = min(1.0, scene_val / 0.6)

            min_interval = max(1.0, 2.0 - graded) if dynamic_interval else 2.0

            if pts_time - last_time < min_interval:
                prev_mean_y = mean_y
                continue

            # Trigger: z-score spike OR raw value is clearly high
            if z <= zscore_threshold and graded < 0.6:
                prev_mean_y = mean_y
                continue

            event_score = 0.6 if z > zscore_threshold else graded * 0.4

            # Luminance boost: sudden brightness shift (flashbang, explosion)
            if luminance_boost and prev_mean_y is not None:
                delta = abs(mean_y - prev_mean_y)
                if delta > luminance_delta_threshold:
                    event_score = min(1.0, event_score + 0.3)
                    logger.debug(
                        f"SceneChange: luminance boost t={pts_time:.1f}s δY={delta:.1f}"
                    )

            event_score = min(1.0, event_score)
            if event_score > 0:
                second = int(pts_time)
                scores[second] = max(scores.get(second, 0), event_score)
                last_time = pts_time

            prev_mean_y = mean_y

        logger.info(
            f"SceneChange: {len(scores)} events (z>{zscore_threshold}, "
            f"max_raw_scene={max_scene:.3f})"
        )
        return scores
