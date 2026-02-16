import logging
from fastapi import FastAPI
from .core.lifespan import lifespan
from .core.observability import setup_observability
from .routers import chat, embeddings, query, rerank

# 1. Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# 2. App Instance
app = FastAPI(
    title="OctaneBrew Intelligence Service",
    description="AI Orchestrator for Embeddings and Chat Completions",
    version="1.0.0",
    lifespan=lifespan
)

# 3. Observability
setup_observability(app)

# 4. Routers
app.include_router(chat.router, prefix="/v1/chat")
app.include_router(embeddings.router, tags=["embeddings"])
app.include_router(query.router, prefix="/v1/query")
app.include_router(rerank.router, prefix="/v1/rerank")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "intelligence"}
