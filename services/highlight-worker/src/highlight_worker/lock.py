"""Redis distributed lock for job exclusivity."""

import logging
import redis.asyncio as redis

from .config import settings

logger = logging.getLogger(__name__)


class DistributedLock:
    """
    Redis-based distributed lock to ensure only one worker processes
    a highlight job for a given video at any time.
    """

    def __init__(
        self,
        lock_key_prefix: str = settings.LOCK_KEY,
        lock_ttl: int = settings.LOCK_TTL,
    ):
        self.prefix = lock_key_prefix
        self.ttl = lock_ttl
        self._redis: redis.Redis | None = None

    async def connect(self):
        """Initialize Redis connection."""
        self._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        await self._redis.ping()
        logger.info("Redis distributed lock connected")

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.aclose()

    async def acquire(self, video_id: str) -> bool:
        """
        Try to acquire a lock for the given video ID.

        Returns:
            True if lock acquired, False if already held
        """
        if not self._redis:
            await self.connect()

        key = f"{self.prefix}:{video_id}"
        acquired = await self._redis.set(key, "locked", ex=self.ttl, nx=True)

        if acquired:
            logger.info(f"Lock acquired for {video_id}")
        else:
            logger.warning(f"Lock already held for {video_id} — skipping")

        return bool(acquired)

    async def release(self, video_id: str):
        """Release the lock for the given video ID."""
        if not self._redis:
            return

        key = f"{self.prefix}:{video_id}"
        await self._redis.delete(key)
        logger.info(f"Lock released for {video_id}")

    async def extend(self, video_id: str, extra_ttl: int = 600) -> bool:
        """Extend the lock TTL (for long-running jobs)."""
        if not self._redis:
            return False

        key = f"{self.prefix}:{video_id}"
        return bool(await self._redis.expire(key, self.ttl + extra_ttl))
