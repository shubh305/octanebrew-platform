from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.kafka import KafkaInstrumentor

def setup_observability(app: FastAPI):
    # Enable Prometheus Metrics
    Instrumentator().instrument(app).expose(app)

    # Enable Tracing
    FastAPIInstrumentor.instrument_app(app)
    KafkaInstrumentor().instrument()
