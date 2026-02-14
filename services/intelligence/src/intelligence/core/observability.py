from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

def setup_observability(app: FastAPI):
    Instrumentator().instrument(app).expose(app)
    FastAPIInstrumentor.instrument_app(app)
