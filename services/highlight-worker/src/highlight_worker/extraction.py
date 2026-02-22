"""Extraction — FFmpeg stream-copy clip extraction and thumbnail generation."""

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


async def extract_clip(
    source_path: str,
    start: float,
    end: float,
    output_path: str,
    stream_copy: bool = True,
) -> bool:
    """
    Extract a clip from source video using FFmpeg.

    Uses stream copy (no re-encoding) by default per spec requirements.
    Falls back to re-encoding only if stream_copy=False.

    Returns:
        True if extraction succeeded
    """
    duration = end - start
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    codec_args = ["-c", "copy"] if stream_copy else ["-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-tune", "zerolatency", "-threads", "1"]

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", source_path,
        "-t", str(duration),
        *codec_args,
        "-avoid_negative_ts", "make_zero",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(
            f"Clip extraction failed: {stderr.decode('utf-8', errors='replace')[:500]}"
        )
        return False

    logger.info(f"Extracted clip: {start:.1f}s–{end:.1f}s → {output_path}")
    return True


async def extract_thumbnail(
    source_path: str,
    timestamp: float,
    output_path: str,
    width: int = 640,
    height: int = 360,
) -> bool:
    """
    Extract a thumbnail frame from the video at the given timestamp.

    Returns:
        True if extraction succeeded
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", source_path,
        "-vframes", "1",
        "-vf", f"scale={int(width/2)}:{int(height/2)}:force_original_aspect_ratio=decrease",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(
            f"Thumbnail extraction failed: {stderr.decode('utf-8', errors='replace')[:500]}"
        )
        return False

    logger.info(f"Extracted thumbnail at {timestamp:.1f}s → {output_path}")
    return True


async def extract_all_clips(
    source_path: str,
    clips: list[dict],
    output_dir: str,
    config: dict,
) -> list[dict]:
    """
    Extract all clips and their thumbnails.

    Mutates clip dicts in-place with clip_path and thumbnail_path.

    Returns:
        List of successfully extracted clips
    """
    stream_copy = config.get("extraction", {}).get("stream_copy", True)
    thumb_w = config.get("extraction", {}).get("thumbnail_width", 640)
    thumb_h = config.get("extraction", {}).get("thumbnail_height", 360)

    extracted = []
    for i, clip in enumerate(clips):
        clip_filename = f"clip_{i:03d}.mp4"
        thumb_filename = f"thumb_{i:03d}.jpg"

        clip_path = os.path.join(output_dir, clip_filename)
        thumb_path = os.path.join(output_dir, thumb_filename)

        clip_ok = await extract_clip(
            source_path,
            clip["start"],
            clip["end"],
            clip_path,
            stream_copy=stream_copy,
        )

        if not clip_ok:
            logger.warning(f"Skipping clip {i} — extraction failed")
            continue

        # Thumbnail at clip midpoint
        mid = (clip["start"] + clip["end"]) / 2
        await extract_thumbnail(source_path, mid, thumb_path, thumb_w, thumb_h)

        clip["clip_path"] = clip_path
        clip["thumbnail_path"] = thumb_path
        clip["index"] = i
        extracted.append(clip)

    logger.info(f"Extracted {len(extracted)}/{len(clips)} clips successfully")
    return extracted
