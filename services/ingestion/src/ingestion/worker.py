import logging
import asyncio
import json
import asyncpg
from aiokafka import AIOKafkaProducer
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from .processors.indexer import ElasticManager
from .processors.intelligence import IntelligenceClient
from .processors.chunker import TextChunker
from .config import settings
from prometheus_client import start_http_server, Counter, Gauge, Histogram
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.kafka import KafkaInstrumentor

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Metrics
JOBS_PROCESSED = Counter('octane_ingest_worker_jobs_total', 'Total jobs processed', ['status'])
JOB_LATENCY = Histogram('octane_ingest_worker_job_seconds', 'Time spent processing job')
RETRY_COUNT = Counter('octane_ingest_worker_retries_total', 'Total job retries')

from pathlib import Path

class JobProcessor:
    def __init__(self):
        self.elastic = ElasticManager()
        self.intelligence = IntelligenceClient()
        self.chunker = TextChunker()
        self.pool = None
        self.producer = None

    async def health_check_task(self):
        """Background task to touch a file for Docker health checks."""
        while True:
            Path("/tmp/healthy").touch()
            await asyncio.sleep(30)

    async def start(self):
        asyncio.create_task(self.health_check_task())

        # Start Metrics Server
        try:
            start_http_server(8001)
            logger.info("Metrics server started on port 8001")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
        
        # Instrument Outbound Traffic (HTTP & Kafka)
        HTTPXClientInstrumentor().instrument()
        KafkaInstrumentor().instrument()

        # Init Kafka Producer
        kafka_kwargs = {
            "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "value_serializer": lambda m: json.dumps(m).encode('utf-8')
        }
        
        if settings.KAFKA_SASL_USER:
            kafka_kwargs.update({
                "security_protocol": "SASL_PLAINTEXT",
                "sasl_mechanism": "PLAIN",
                "sasl_plain_username": settings.KAFKA_SASL_USER,
                "sasl_plain_password": settings.KAFKA_SASL_PASS
            })
            
        self.producer = AIOKafkaProducer(**kafka_kwargs)
        await self.producer.start()
        logger.info(f"Kafka Result Producer started on {settings.KAFKA_BOOTSTRAP_SERVERS}")

        self.pool = await asyncpg.create_pool(settings.POSTGRES_DSN)
        await self.elastic.init_index()
        logger.info("Job Processor started.")
        
        while True:
            try:
                await self.process_batch()
            except Exception as e:
                logger.error(f"Job Processor Error: {e}")
            await asyncio.sleep(5)

    async def process_batch(self):
        async with self.pool.acquire() as conn:
            # 1. Fetch Pending Jobs
            # SKIP LOCKED ensures multiple workers don't grab same job
            rows = await conn.fetch("""
                UPDATE ai_oplog
                SET status = 'PROCESSING', updated_at = NOW()
                WHERE id IN (
                    SELECT id FROM ai_oplog
                    WHERE status IN ('PENDING', 'RETRY')
                      AND next_attempt_at <= NOW()
                    FOR UPDATE SKIP LOCKED
                    LIMIT 10
                )
                RETURNING id, entity_id, task_type, payload, retry_count, target_index
            """)
            
            if not rows:
                return

            logger.info(f"Processing {len(rows)} jobs...")
            
            for row in rows:
                job_id = row['id']
                try:
                    with JOB_LATENCY.time():
                        await self.execute_job(row)
                    
                    # Success
                    await conn.execute("""
                        UPDATE ai_oplog SET status = 'COMPLETED', updated_at = NOW() WHERE id = $1
                    """, job_id)
                    JOBS_PROCESSED.labels(status="success").inc()
                except Exception as e:
                    # Failure
                    logger.error(f"Job {job_id} failed: {e}", exc_info=True)
                    await self.handle_failure(conn, row, e)
                    JOBS_PROCESSED.labels(status="failure").inc()

    async def execute_job(self, job):
        payload = json.loads(job['payload'])
        enrichments = payload.get('enrichments', [])
        
        if job['task_type'] in ['embed', 'enrich']:
            chunks = payload.get('chunks')
            text = payload.get('text')
            strategy = payload.get('chunking_strategy', 'recursive')
            
            # 1. Chunk if missing 
            if not chunks and text:
                logger.info(f"Worker performing {strategy} chunking for {job['entity_id']}...")
                chunks = await self.chunker.split_text(
                    text,
                    strategy=strategy,
                    chunk_size=payload.get('chunk_size', 500),
                    chunk_overlap=payload.get('chunk_overlap', 50),
                    intelligence_client=self.intelligence
                )

            nested_chunks = []
            summary = None
            
            # 2. Vectorize Chunks
            if chunks:
                vectors = await self.intelligence.embed_documents(chunks)
                logger.info(f"Generated {len(vectors)} embeddings with dimension {len(vectors[0])}")
                nested_chunks = [
                    {"text_chunk": txt, "vector": vec}
                    for txt, vec in zip(chunks, vectors)
                ]
            
            # 3. Generate Summary
            if "summary" in enrichments and text:
                entity_type = payload.get('entity_type', 'article')
                summary = await self.intelligence.generate_summary(text, entity_type=entity_type)
                
            await self.elastic.update_vectors(job['entity_id'], nested_chunks, summary, index_name=job['target_index'])

            # 4. Emit Result Event
            await self.emit_result(job['entity_id'], payload.get('entity_type'), summary, job['target_index'])

    async def emit_result(self, entity_id, entity_type, summary, index_name):
        if not summary:
            return
            
        result_payload = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "summary": summary,
            "index_name": index_name,
            "status": "completed",
            "timestamp": asyncio.get_event_loop().time()
        }
        
        try:
            logger.info(f"Emitting result for {entity_id} to {settings.KAFKA_RESULT_TOPIC}")
            await self.producer.send_and_wait(
                settings.KAFKA_RESULT_TOPIC,
                value=result_payload
            )
        except Exception as e:
            logger.error(f"Failed to emit kafka result: {e}")

    async def handle_failure(self, conn, job, error):
        retry_count = job['retry_count'] + 1
        # Exponential backoff
        delay = (2 ** retry_count) * 60
        
        await conn.execute("""
            UPDATE ai_oplog 
            SET status = 'RETRY', 
                retry_count = $1, 
                next_attempt_at = NOW() + ($2 || ' seconds')::interval,
                error_message = $3,
                updated_at = NOW()
            WHERE id = $4
        """, retry_count, str(delay), str(error), job['id'])

if __name__ == "__main__":
    processor = JobProcessor()
    asyncio.run(processor.start())
