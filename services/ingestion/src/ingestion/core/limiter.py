import time
import logging
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)

# Token Bucket Lua Script
TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
else
    local elapsed = math.max(0, now - last_refill)
    tokens = math.min(capacity, tokens + (elapsed * refill_rate))
    last_refill = now
end

if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    redis.call('EXPIRE', key, 3600) -- TTL for cleanup
    return 1
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    return 0
end
"""

async def check_rate_limit(request: Request, capacity: int = 60, refill_rate: float = 1.0, name: str = "default"):
    """
    Generic Rate Limiter using Token Bucket via Redis.
    """
    script = request.app.state.limiter_script
    
    client_ip = request.client.host if request.client else "unknown"
    key = f"rate_limit:{name}:{client_ip}"
    
    allowed = await script(keys=[key], args=[capacity, refill_rate, time.time()])
    
    if not allowed:
        logger.warning(f"Rate limit exceeded for {client_ip} on {name}")
        raise HTTPException(
            status_code=429, 
            detail=f"Too Many Requests: Token Bucket Empty. Refill Rate: {refill_rate}/sec"
        )
