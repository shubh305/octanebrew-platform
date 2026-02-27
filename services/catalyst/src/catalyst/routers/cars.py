"""
GET /cars/search — autocomplete endpoint for Conduit's /cars slash command.
Full pipeline: Redis cache → ES fuzzy match → Intelligence rerank.
"""
import time
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request
from ..models import CarResult
from ..core.auth import get_api_key
from ..core.limiter import check_rate_limit
from ..services.search import search_products
from ..config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cars", tags=["Cars"])


@router.get("/search", response_model=List[CarResult])
async def search_cars(
    request: Request,
    q: str = Query(..., min_length=2, description="Partial make/model search string"),
    year: Optional[int] = Query(None, description="Filter by first_seen_year"),
    fuel_type: Optional[str] = Query(None, description="Filter by fuel type"),
    limit: int = Query(10, ge=1, le=20),
    _auth=Depends(get_api_key),
    _rate=Depends(check_rate_limit),
):
    t0 = time.monotonic()
    cache_key = f"catalyst:cars:search:{q}:{year}:{fuel_type}:{limit}"

    filters = {}
    if year:
        filters["first_seen_year"] = year
    if fuel_type:
        filters["fuel_type"] = fuel_type

    hits = await search_products(
        request.app.state.elastic,
        request.app.state.http_client,
        request.app.state.redis,
        category="car",
        query=q,
        limit=limit,
        filters=filters,
        cache_key=cache_key,
        ttl=settings.CACHE_TTL_SECONDS,
    )

    results = []
    for h in hits:
        label_parts = [f"{h.get('make', '')} {h.get('model', '')}".strip()]
        extras = []
        if h.get("first_seen_year"):
            extras.append(str(h["first_seen_year"]))
        if h.get("fuel_type"):
            extras.append(h["fuel_type"])
        if h.get("body_type"):
            extras.append(h["body_type"])
        if extras:
            label_parts.append(f"({', '.join(extras)})")
        display_label = " ".join(label_parts)

        results.append(CarResult(
            id=str(h.get("id", "")),
            make=h.get("make", ""),
            model=h.get("model", ""),
            body_type=h.get("body_type"),
            fuel_type=h.get("fuel_type"),
            first_seen_year=h.get("first_seen_year"),
            base_price_inr=h.get("base_price_inr"),
            display_label=display_label,
        ))

    return results
