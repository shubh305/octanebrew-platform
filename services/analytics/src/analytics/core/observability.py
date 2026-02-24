from prometheus_client import Counter, Gauge, Histogram
from opentelemetry.instrumentation.kafka import KafkaInstrumentor
import logging
from ..config import settings

# Setup Logging
logging.basicConfig(level=settings.LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("analytics")

# Metrics
EVENTS_PROCESSED = Counter('octane_analytics_events_total', 'Total events processed', ['app_id', 'status'])
BATCH_SIZE_GAUGE = Gauge('octane_analytics_batch_size', 'Current batch size')
PROCESS_TIME = Histogram('octane_analytics_process_seconds', 'Time spent processing batch')

def instrument_kafka():
    KafkaInstrumentor().instrument()
