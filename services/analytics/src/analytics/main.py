from fastapi import FastAPI
from .core.lifespan import lifespan
from .routers import health, query
import logging

logger = logging.getLogger("analytics")

# Initialize FastAPI app
app = FastAPI(lifespan=lifespan, title="Octane Analytics Hub", version="0.1.0")

# Include routers
app.include_router(health.router)
app.include_router(query.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
