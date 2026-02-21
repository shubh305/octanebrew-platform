"""Chat Spike detection via chat.json message bucketing."""

import json
import logging
import statistics
from pathlib import Path
from . import BaseSignal

logger = logging.getLogger(__name__)


class ChatSpikeSignal(BaseSignal):
    """Detects chat activity spikes by bucketing message timestamps."""

    @property
    def name(self) -> str:
        return "chat_spike"

    async def detect(
        self, proxy_path: str, config: dict, **kwargs
    ) -> dict[int, float]:
        chat_path = kwargs.get("chat_path")
        if not chat_path or not Path(chat_path).exists():
            logger.info("ChatSpike: no chat.json found — skipping")
            return {}

        bucket_size = config.get("bucket_size", 10)
        spike_multiplier = config.get("spike_multiplier", 2.5)

        try:
            with open(chat_path) as f:
                messages = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"ChatSpike: failed to parse chat.json: {e}")
            return {}

        if not messages:
            logger.info("ChatSpike: empty chat log — skipping")
            return {}

        # Bucket messages by time offset
        buckets: dict[int, int] = {}
        for msg in messages:
            ts = msg.get("offset_seconds") or msg.get("timestamp_offset", 0)
            bucket = int(ts) // bucket_size * bucket_size
            buckets[bucket] = buckets.get(bucket, 0) + 1

        if not buckets:
            return {}

        # Calculate median and threshold
        counts = list(buckets.values())
        median = statistics.median(counts) if counts else 0
        threshold = median * spike_multiplier

        # Score spikes relative to the threshold
        scores: dict[int, float] = {}
        max_count = max(counts) if counts else 1

        for bucket_start, count in buckets.items():
            if count > threshold:
                # Spread score across seconds in the bucket
                score = min(1.0, count / max_count)
                for sec in range(bucket_start, bucket_start + bucket_size):
                    scores[sec] = score

        logger.info(
            f"ChatSpike: {len(scores)} seconds above threshold "
            f"(median={median:.1f}, threshold={threshold:.1f})"
        )
        return scores
