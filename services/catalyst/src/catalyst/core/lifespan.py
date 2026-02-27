"""
FastAPI lifespan context manager.
Initializes and cleanly shuts down all shared resources:
  - asyncpg connection pool (PostgreSQL)
  - Redis async client
  - AIOKafka producer
  - Elasticsearch async client
  - HTTPX client (Intelligence Service)
"""
import json
import logging
import asyncpg
import httpx
import redis.asyncio as aioredis
from contextlib import asynccontextmanager
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI
from ..config import settings
from .limiter import TOKEN_BUCKET_LUA

logger = logging.getLogger(__name__)





def _build_es_client() -> AsyncElasticsearch:
    kwargs: dict = {"hosts": [settings.ES_HOST]}
    if settings.ELASTIC_USER:
        kwargs["basic_auth"] = (settings.ELASTIC_USER, settings.ELASTIC_PASSWORD)
    return AsyncElasticsearch(**kwargs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Catalyst: starting up...")

    # 1. Redis
    app.state.redis = aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )
    app.state.limiter_script = app.state.redis.register_script(TOKEN_BUCKET_LUA)

    # 2. PostgreSQL connection pool
    app.state.db_pool = await asyncpg.create_pool(
        dsn=settings.POSTGRES_DSN.replace("+asyncpg", ""),
        min_size=2,
        max_size=10,
    )

    # 3. Elasticsearch
    app.state.elastic = _build_es_client()



    # 4. HTTPX client for Intelligence Service calls
    app.state.http_client = httpx.AsyncClient(
        base_url=settings.INTELLIGENCE_SVC_URL,
        timeout=10.0,
        headers={"X-API-KEY": settings.SERVICE_API_KEY},
    )

    logger.info("Catalyst: all dependencies initialized.")
    yield

    # --- Cleanup ---
    logger.info("Catalyst: shutting down...")
    await app.state.elastic.close()
    await app.state.db_pool.close()
    await app.state.redis.close()
    await app.state.http_client.aclose()
    logger.info("Catalyst: shutdown complete.")
