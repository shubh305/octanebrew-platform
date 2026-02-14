import json
import logging
import redis.asyncio as aioredis
from aiokafka import AIOKafkaProducer
from contextlib import asynccontextmanager
from fastapi import FastAPI
from ..config import settings
from ..processors.intelligence import IntelligenceClient
from ..processors.indexer import ElasticManager
from .limiter import TOKEN_BUCKET_LUA

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize Redis & Lua Script
    app.state.redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    app.state.limiter_script = app.state.redis.register_script(TOKEN_BUCKET_LUA)
    
    # 2. Configure Kafka Producer
    kafka_kwargs = {
        "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "value_serializer": lambda v: json.dumps(v).encode('utf-8')
    }
    if settings.KAFKA_SASL_USER:
        kafka_kwargs.update({
            "security_protocol": "SASL_PLAINTEXT",
            "sasl_mechanism": "PLAIN",
            "sasl_plain_username": settings.KAFKA_SASL_USER,
            "sasl_plain_password": settings.KAFKA_SASL_PASS
        })
    
    app.state.producer = AIOKafkaProducer(**kafka_kwargs)
    
    # 3. Initialize Shared Processing Clients
    app.state.elastic = ElasticManager()
    app.state.intelligence = IntelligenceClient()
    
    # Start background tasks
    await app.state.producer.start()
    logger.info("Ingestion Service core dependencies initialized")
    
    yield
    
    # Shutdown / Cleanup
    await app.state.producer.stop()
    await app.state.elastic.close()
    await app.state.redis.close()
    logger.info("Ingestion Service core dependencies cleaned up")
