"""
Redis cache helpers — async get/set/invalidate with JSON serialization.
"""
import json
import logging
from typing import Any, Optional
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


async def cache_get(redis: Redis, key: str) -> Optional[Any]:
    """Return deserialized value from Redis cache, or None on miss."""
    try:
        raw = await redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Cache GET failed for key={key}: {e}")
        return None


async def cache_set(redis: Redis, key: str, value: Any, ttl: int = 300) -> None:
    """Serialize and store value in Redis cache with given TTL (seconds)."""
    try:
        await redis.set(key, json.dumps(value), ex=ttl)
    except Exception as e:
        logger.warning(f"Cache SET failed for key={key}: {e}")


async def cache_invalidate(redis: Redis, pattern: str) -> int:
    """Delete all keys matching a glob pattern. Returns count deleted."""
    try:
        keys = await redis.keys(pattern)
        if keys:
            return await redis.delete(*keys)
        return 0
    except Exception as e:
        logger.warning(f"Cache INVALIDATE failed for pattern={pattern}: {e}")
        return 0
