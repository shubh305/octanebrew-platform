"""Consolidation — cluster qualified seconds into non-overlapping clip windows."""

import logging

logger = logging.getLogger(__name__)


def consolidate_clips(
    qualified: dict[int, float],
    min_duration: int = 8,
    max_duration: int = 60,
    context_buffer: int = 3,
    min_gap: int = 5,
    max_clips: int = 5,
) -> list[dict]:
    """
    Merge adjacent qualified seconds into clip windows.

    Steps:
    1. Cluster consecutive seconds into segments
    2. Expand each segment with context buffer
    3. Merge overlapping segments
    4. Enforce min/max duration constraints
    5. Rank by peak score and cap at max_clips

    Returns:
        List of clip dicts: [{start, end, score, peak_second}, ...]
    """
    if not qualified:
        return []

    # 1. Sort seconds
    seconds = sorted(qualified.keys())

    # 2. Form clusters of consecutive seconds
    clusters: list[list[int]] = []
    current_cluster = [seconds[0]]

    for i in range(1, len(seconds)):
        if seconds[i] - seconds[i - 1] <= min_gap:
            current_cluster.append(seconds[i])
        else:
            clusters.append(current_cluster)
            current_cluster = [seconds[i]]
    clusters.append(current_cluster)

    # 3. Convert clusters to clip windows with context buffer
    raw_clips = []
    for cluster in clusters:
        start = max(0, cluster[0] - context_buffer)
        end = cluster[-1] + context_buffer

        # Peak score in this cluster
        peak_score = max(qualified.get(s, 0) for s in cluster)
        peak_second = max(cluster, key=lambda s: qualified.get(s, 0))

        raw_clips.append({
            "start": start,
            "end": end,
            "score": round(peak_score, 4),
            "peak_second": peak_second,
        })

    # 4. Merge overlapping clips
    merged: list[dict] = []
    for clip in sorted(raw_clips, key=lambda c: c["start"]):
        if merged and clip["start"] <= merged[-1]["end"] + min_gap:
            # Merge with previous
            merged[-1]["end"] = max(merged[-1]["end"], clip["end"])
            merged[-1]["score"] = max(merged[-1]["score"], clip["score"])
        else:
            merged.append(clip.copy())

    # 5. Enforce duration constraints
    constrained = []
    for clip in merged:
        duration = clip["end"] - clip["start"]
        if duration < min_duration:
            # Expand symmetrically to min_duration
            expand = (min_duration - duration) // 2
            clip["start"] = max(0, clip["start"] - expand)
            clip["end"] = clip["start"] + min_duration
        elif duration > max_duration:
            # Trim from the end
            clip["end"] = clip["start"] + max_duration
        constrained.append(clip)

    # 6. Rank by score, cap at max_clips
    ranked = sorted(constrained, key=lambda c: c["score"], reverse=True)
    final = ranked[:max_clips]

    # Re-sort by start time for output
    final.sort(key=lambda c: c["start"])

    logger.info(
        f"Consolidation: {len(clusters)} clusters → {len(merged)} merged → "
        f"{len(final)} final clips (max={max_clips})"
    )
    return final
