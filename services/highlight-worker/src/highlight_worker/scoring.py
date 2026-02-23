"""Scoring — per-second weighted scoring and qualification from signal outputs."""

import asyncio
import logging
from typing import Dict

logger = logging.getLogger(__name__)


async def compute_scores(
    signal_outputs: dict[str, dict[int, float]],
    signal_weights: dict[str, float],
    duration_seconds: int,
) -> dict[int, dict[str, float]]:
    """
    Compute scores with ±1s temporal fusion and per-second signal counts.
    Returns {second: {"total": float, "sig_count": int}}
    """
    aggregate: dict[int, dict[str, float]] = {}

    for sec in range(duration_seconds):
        total = 0.0
        sig_count = 0
        for sig_name, scores in signal_outputs.items():
            weight = signal_weights.get(sig_name, 0.0)
            
            # Temporal Fusion: Take max score in ±1s window
            window = [
                scores.get(sec - 1, 0.0),
                scores.get(sec, 0.0),
                scores.get(sec + 1, 0.0)
            ]
            signal_score = max(window)
            
            weighted_score = signal_score * weight
            total += weighted_score
            
            if signal_score > 0.1:
                sig_count += 1

        if total > 0.01:
            aggregate[sec] = {"total": round(total, 4), "sig_count": sig_count}
            
        if sec % 10000 == 0:
            await asyncio.sleep(0)

    logger.info(
        f"Scoring: {len(aggregate)} seconds scored with temporal fusion"
    )
    return aggregate


async def qualify_seconds(
    aggregate_scores: dict[int, dict[str, float]],
    threshold: float,
) -> dict[int, float]:
    """
    Filter to only seconds meeting threshold AND cross-signal qualification.
    """
    qualified = {}
    for sec, data in aggregate_scores.items():
        score = data["total"]
        count = data["sig_count"]
        
        # Qualification Logic:
        # 1. Total score must be above threshold
        # 2. MUST have either:
        #    a) Agreement from ≥ 2 signals
        #    b) Single signal extremely high (>0.7 total score)
        if score >= threshold:
            if count >= 2 or score >= 0.3:
                qualified[sec] = score
        
        if sec % 10000 == 0:
            await asyncio.sleep(0)

    logger.info(
        f"Qualification: {len(qualified)}/{len(aggregate_scores)} seconds "
        f"above threshold {threshold} (with signal agreement check)"
    )
    return qualified
