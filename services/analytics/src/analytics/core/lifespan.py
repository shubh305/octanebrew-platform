import asyncio
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from prometheus_client import start_http_server

from .database import ClickHouseManager
from .consumer import consume

logger = logging.getLogger("analytics")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start metrics server on a separate port for Prometheus
    start_http_server(8000)
    
    # Init DB
    db_manager = ClickHouseManager()
    app.state.db_manager = db_manager
    
    async def health_signal():
        while True:
            with open("/tmp/healthy", "w") as f:
                f.write(str(time.time()))
            await asyncio.sleep(15)
            
    health_task = asyncio.create_task(health_signal())
    
    # Start Kafka Consumer in the background
    consumer_task = asyncio.create_task(consume(db_manager))
    logger.info("Background consumer task started.")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    health_task.cancel()
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
