import asyncio
import json
from aiokafka import AIOKafkaConsumer
from pathlib import Path
from .models import IngestRequest
from .config import settings
import asyncpg
from .processors.indexer import ElasticManager
from .processors.chunker import TextChunker
from .processors.sanitizer import Sanitizer

import logging

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def health_check_task():
    """Background task to touch a file for Docker health checks."""
    while True:
        Path("/tmp/healthy").touch()
        await asyncio.sleep(30)

async def consume():
    logger.info(f"Starting Ingestion Worker...")
    asyncio.create_task(health_check_task())
    
    elastic = ElasticManager()
    await elastic.init_index()
    
    chunker = TextChunker()
    
    # Init DB Pool
    try:
        pool = await asyncpg.create_pool(settings.POSTGRES_DSN)
    except Exception as e:
        logger.error(f"Failed to connect to DB: {e}")
        return
    
    # Init Kafka 
    kafka_kwargs = {
        "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "group_id": "ingestion_worker_group",
        "enable_auto_commit": False,
        "auto_offset_reset": "earliest",
        "value_deserializer": lambda m: json.loads(m.decode('utf-8'))
    }
    
    if settings.KAFKA_SASL_USER:
        kafka_kwargs.update({
            "security_protocol": "SASL_PLAINTEXT",
            "sasl_mechanism": "PLAIN",
            "sasl_plain_username": settings.KAFKA_SASL_USER,
            "sasl_plain_password": settings.KAFKA_SASL_PASS
        })

    consumer = AIOKafkaConsumer(
        settings.KAFKA_TOPIC,
        **kafka_kwargs
    )
    
    await consumer.start()
    logger.info(f"Consumer started on {settings.KAFKA_TOPIC}")
    
    try:
        async for msg in consumer:
            try:
                # 1. Parse
                data = IngestRequest(**msg.value)
                
                if data.operation == 'index':
                    # Extract content
                    text_content = data.payload.get('text') or data.payload.get('content') or ""
                    
                    # Sanitize
                    text_content = Sanitizer.clean_html(text_content)
                    
                    title = data.payload.get('title', "")
                    
                    # 2. Pass 1: Text Indexing
                    doc_body = {
                        "source_app": data.source_app,
                        "entity_id": data.entity_id,
                        "title": title,
                        "content": text_content,
                        "metadata": data.payload.get('metadata', {}),
                        "status": "processing_vectors"
                    }
                    await elastic.upsert_text(data.entity_id, doc_body, index_name=data.index_name)
                    logger.info(f"Pass 1: Indexed text for {data.entity_id} in {data.index_name or 'default'}")
                    
                    # 3. Pass 2: Vector Enrichment
                    if text_content:
                        chunks_text = None
                        if data.chunking_strategy != "semantic":
                            chunks_text = await chunker.split_text(
                                text_content, 
                                strategy=data.chunking_strategy,
                                chunk_size=data.chunk_size, 
                                chunk_overlap=data.chunk_overlap
                            )

                        # OPLOG: Insert Job instead of calling API
                        task_type = 'enrich' if data.enrichments else 'embed'
                        async with pool.acquire() as conn:
                            await conn.execute("""
                                INSERT INTO ai_oplog (entity_id, task_type, payload, target_index)
                                VALUES ($1, $2, $3, $4)
                            """, data.entity_id, task_type, json.dumps({
                                "entity_type": data.entity_type,
                                "chunks": chunks_text,
                                "text": text_content,
                                "enrichments": data.enrichments,
                                "chunk_size": data.chunk_size,
                                "chunk_overlap": data.chunk_overlap,
                                "chunking_strategy": data.chunking_strategy
                            }), data.index_name)
                        
                        logger.info(f"Pass 2: Queued {data.chunking_strategy} embedding job for {data.entity_id}")
            
                await consumer.commit()
                
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                pass

    finally:
        await consumer.stop()
        await elastic.close()

if __name__ == "__main__":
    asyncio.run(consume())
