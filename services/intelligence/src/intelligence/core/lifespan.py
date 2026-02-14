import redis.asyncio as redis
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .limiter import TOKEN_BUCKET_LUA
from ..config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.redis = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    app.state.limiter_script = app.state.redis.register_script(TOKEN_BUCKET_LUA)
    yield
    # Shutdown
    await app.state.redis.close()
