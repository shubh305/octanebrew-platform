import json
import logging
from pathlib import Path
from aiokafka import AIOKafkaConsumer
from tenacity import retry, wait_fixed

from ..config import settings
from ..models import AnalyticsEvent
from .database import ClickHouseManager
from .observability import instrument_kafka, PROCESS_TIME, BATCH_SIZE_GAUGE, EVENTS_PROCESSED

logger = logging.getLogger("analytics")

@retry(wait=wait_fixed(5))
async def robust_flush(db: ClickHouseManager, batch: list, consumer: AIOKafkaConsumer):
    try:
        if batch:
            logger.info(f"Flushing {len(batch)} events...")
            db.bulk_insert(batch)
            await consumer.commit()
            Path("/tmp/healthy").touch()
    except Exception as e:
        logger.error(f"Flush Connection Error: {e}")
        raise e

async def consume(db: ClickHouseManager):
    instrument_kafka()
    logger.info("Starting Analytics Consumer...")

    kafka_kwargs = {
        "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "group_id": settings.KAFKA_GROUP_ID,
        "enable_auto_commit": False,
        "auto_offset_reset": "earliest"
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
        while True:
            # Using getmany for bulk fetching
            results = await consumer.getmany(
                timeout_ms=int(settings.FLUSH_INTERVAL * 1000), 
                max_records=settings.BATCH_SIZE
            )
            
            batch = []
            for tp, messages in results.items():
                for msg in messages:
                    try:
                        value_str = msg.value.decode('utf-8')
                        value_json = json.loads(value_str)
                        event = AnalyticsEvent(**value_json)
                        batch.append(event.model_dump())
                    except Exception as e:
                        logger.warning(f"Skipping bad message: {e}")
            
            if batch:
                with PROCESS_TIME.time():
                    await robust_flush(db, batch, consumer)
                
                # Update Metrics
                BATCH_SIZE_GAUGE.set(len(batch))
                for evt in batch:
                    EVENTS_PROCESSED.labels(app_id=evt['app_id'], status="success").inc()
            else:
                Path("/tmp/healthy").touch()

    finally:
        await consumer.stop()
