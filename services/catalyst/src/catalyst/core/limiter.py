"""
Redis Token Bucket rate limiter — 120 req/min per X-App-ID.
Uses a Lua script for atomic check-and-consume on Redis.
Pattern identical to the ingestion service limiter.
"""
from fastapi import Request, HTTPException, status
from ..config import settings

# Lua script: atomic token bucket decrement
TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])  -- tokens per second
local now = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1]) or capacity
local last_refill = tonumber(data[2]) or now

-- Refill tokens based on elapsed time
local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 120)
    return 1
else
    return 0
end
"""


async def check_rate_limit(request: Request):
    """Dependency that enforces rate limiting via Redis token bucket."""
    app_id = request.headers.get("X-App-ID", request.client.host if request.client else "unknown")
    key = f"catalyst:ratelimit:{app_id}"

    import time
    now = int(time.time())
    capacity = settings.RATE_LIMIT_PER_MINUTE
    refill_rate = capacity / 60.0

    redis_client = request.app.state.redis
    limiter_script = request.app.state.limiter_script

    allowed = await limiter_script(keys=[key], args=[capacity, refill_rate, now])

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again in a moment.",
            headers={"Retry-After": "60"},
        )
