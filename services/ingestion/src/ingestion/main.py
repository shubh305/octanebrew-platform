import logging
from fastapi import FastAPI, Depends
from .core.lifespan import lifespan
from .core.observability import setup_observability
from .core.security import get_api_key
from .routers import ingest, search

# 1. Basic Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# 2. FastAPI Application Instance
app = FastAPI(
    title="OctaneBrew Ingestion Service",
    description="Scalable Gateway for Content Ingestion and Semantic Search",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(get_api_key)]
)

# 3. Setup Observability (Metrics & Tracing)
setup_observability(app)

# 4. Mount Routers
app.include_router(ingest.router)
app.include_router(search.router)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "ingestion"}
