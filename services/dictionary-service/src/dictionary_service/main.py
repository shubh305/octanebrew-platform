from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi_limiter import FastAPILimiter
from prometheus_fastapi_instrumentator import Instrumentator
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
import redis.asyncio as redis
from .config import settings
from .routers import lookup

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Redis for Rate Limiting
    redis_connection = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    await FastAPILimiter.init(redis_connection)
    
    yield
    # Shutdown
    await redis_connection.close()

app = FastAPI(title=settings.APP_TITLE, lifespan=lifespan)

# Enable Prometheus Metrics
Instrumentator().instrument(app).expose(app)

# Enable Tracing
FastAPIInstrumentor.instrument_app(app)

app.include_router(lookup.router, prefix="/v1", tags=["dictionary"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
