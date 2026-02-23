"""Main entry point — Kafka consumer for highlight generation jobs."""

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from prometheus_client import start_http_server

from .config import settings
from .job import run_highlight_job
from .lock import DistributedLock
from .metrics import JOBS_PROCESSED

# Setup Logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Kafka topics
TOPIC_REQUEST = settings.KAFKA_TOPIC_HIGHLIGHTS_REQUEST
TOPIC_COMPLETE = settings.KAFKA_TOPIC_HIGHLIGHTS_COMPLETE
TOPIC_DEGRADED = settings.KAFKA_TOPIC_HIGHLIGHTS_DEGRADED
TOPIC_FAILED = settings.KAFKA_TOPIC_HIGHLIGHTS_FAILED


async def health_check_task():
    """Background task to touch a file for Docker health checks."""
    while True:
        Path("/tmp/healthy").touch()
        await asyncio.sleep(30)


async def consume():
    """Main consumer loop — processes one highlight job at a time."""
    logger.info("Starting Highlight Worker...")
    asyncio.create_task(health_check_task())

    # Start Prometheus metrics server
    try:
        start_http_server(8002)
        logger.info("Metrics server started on port 8002")
    except Exception as e:
        logger.error(f"Failed to start metrics server: {e}")

    # Build Kafka connection kwargs
    kafka_kwargs = {
        "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "group_id": settings.KAFKA_GROUP_ID,
        "enable_auto_commit": False,
        "auto_offset_reset": "earliest",
        "value_deserializer": lambda m: json.loads(m.decode("utf-8")),
        "max_poll_interval_ms": 10800000,
        "session_timeout_ms": 180000,
        "heartbeat_interval_ms": 40000,
    }

    producer_kwargs = {
        "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "value_serializer": lambda m: json.dumps(m).encode("utf-8"),
    }

    if settings.KAFKA_SASL_USER:
        sasl_config = {
            "security_protocol": "SASL_PLAINTEXT",
            "sasl_mechanism": "PLAIN",
            "sasl_plain_username": settings.KAFKA_SASL_USER,
            "sasl_plain_password": settings.KAFKA_SASL_PASS,
        }
        kafka_kwargs.update(sasl_config)
        producer_kwargs.update(sasl_config)

    consumer = AIOKafkaConsumer(TOPIC_REQUEST, **kafka_kwargs)
    producer = AIOKafkaProducer(**producer_kwargs)

    await consumer.start()
    await producer.start()

    lock = DistributedLock()
    await lock.connect()
    logger.info(f"Consumer started on topic: {TOPIC_REQUEST}")

    try:
        async for msg in consumer:
            payload = msg.value
            video_id = payload.get("videoId", "unknown")

            logger.info(f"Received highlight request for video: {video_id}")

            # Acquire distributed lock
            if not await lock.acquire(video_id):
                logger.warning(f"Skipping {video_id} — lock already held")
                await consumer.commit()
                continue

            try:
                result = await asyncio.wait_for(
                    run_highlight_job(payload),
                    timeout=settings.JOB_TIMEOUT_SECONDS,
                )

                # Determine outcome: complete vs degraded
                if result.get("warnings"):
                    topic = TOPIC_DEGRADED
                else:
                    topic = TOPIC_COMPLETE

                await producer.send_and_wait(topic, value=result)
                logger.info(f"Emitted {topic} for {video_id}")

            except asyncio.TimeoutError:
                logger.error(f"Job timed out for {video_id}")
                JOBS_PROCESSED.labels(status="timeout").inc()
                await producer.send_and_wait(
                    TOPIC_FAILED,
                    value={
                        "videoId": video_id,
                        "error": f"Job timed out after {settings.JOB_TIMEOUT_SECONDS}s",
                        "ts": __import__("time").time(),
                    },
                )

            except Exception as e:
                logger.error(f"Job failed for {video_id}: {e}", exc_info=True)
                JOBS_PROCESSED.labels(status="error").inc()
                await producer.send_and_wait(
                    TOPIC_FAILED,
                    value={
                        "videoId": video_id,
                        "error": str(e),
                        "ts": __import__("time").time(),
                    },
                )

            finally:
                await lock.release(video_id)
                await consumer.commit()

    except asyncio.CancelledError:
        logger.info("Consumer cancelled — shutting down")
    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("Highlight Worker stopped")


def main():
    """Entrypoint for the highlight worker."""
    loop = asyncio.new_event_loop()

    def _shutdown(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        for task in asyncio.all_tasks(loop):
            task.cancel()
        loop.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        loop.run_until_complete(consume())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
