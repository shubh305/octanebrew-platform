import logging
from fastapi import FastAPI, Depends
from .core.lifespan import lifespan
from .core.observability import setup_observability
from .core.auth import get_api_key
from .routers import cars, bikes, books, products, mobiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Catalyst — Product Launch Intelligence",
    description="Product catalog + Reddit signal spoke for OctaneBrew Platform. "
                "Powers Conduit editor slash commands: /cars, /bikes, /books.",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(get_api_key)],
)

# Prometheus metrics + OTel tracing
setup_observability(app)

# Routers
app.include_router(cars.router)
app.include_router(bikes.router)
app.include_router(books.router)
app.include_router(mobiles.router)
app.include_router(products.router)


@app.get("/health", tags=["System"])
async def health_check():
    """Liveness probe — returns ok if app is running."""
    return {"status": "ok", "service": "catalyst"}
