"""
Prometheus metrics + OpenTelemetry tracing for Catalyst service.
Registers all spec-defined custom metrics and auto-instruments FastAPI.
"""
import logging
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram, Gauge
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)

# -----------------------------------------------
# Custom Prometheus Metrics (per spec §11)
# -----------------------------------------------
SEARCH_REQUESTS_TOTAL = Counter(
    "catalyst_search_requests_total",
    "Total search requests by category and status",
    ["category", "status"]
)

SEARCH_LATENCY = Histogram(
    "catalyst_search_latency_seconds",
    "End-to-end search latency",
    ["category"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

CATALOG_PRODUCTS_TOTAL = Gauge(
    "catalyst_catalog_products_total",
    "Total products per category in DB",
    ["category"]
)

REDDIT_POSTS_INGESTED_TOTAL = Counter(
    "catalyst_reddit_posts_ingested_total",
    "Total Reddit posts ingested",
    ["category"]
)

PRODUCT_LINKS_TOTAL = Counter(
    "catalyst_product_links_total",
    "Total product-reddit links created"
)

CACHE_HIT_RATIO = Gauge(
    "catalyst_cache_hit_ratio",
    "Redis cache hit/miss ratio (rolling)"
)

# Rolling cache counters used to compute the ratio
_cache_hits = 0
_cache_total = 0


def record_cache_result(hit: bool):
    """Update cache hit/miss counters and refresh the gauge."""
    global _cache_hits, _cache_total
    _cache_total += 1
    if hit:
        _cache_hits += 1
    ratio = _cache_hits / _cache_total if _cache_total > 0 else 0.0
    CACHE_HIT_RATIO.set(ratio)


def setup_observability(app: FastAPI):
    """Initialize Prometheus instrumentation and OpenTelemetry tracing."""
    # Prometheus — auto-instrument all FastAPI routes + expose /metrics
    Instrumentator().instrument(app).expose(app)

    # OTel — auto-instrument FastAPI routes
    FastAPIInstrumentor.instrument_app(app)

    # OTel — instrument all outbound httpx calls (Intelligence Service)
    HTTPXClientInstrumentor().instrument()

    # OTel — configure tracer with OTLP export if endpoint is set
    try:
        from ..config import settings
        if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            resource = Resource.create({"service.name": "catalyst"})
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            logger.info("OTel OTLP tracing configured → %s", settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    except Exception as e:
        logger.warning("OTel setup skipped: %s", e)
