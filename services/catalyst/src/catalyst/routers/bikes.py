"""
GET /bikes/search — autocomplete endpoint for Conduit's /bikes slash command.
"""
import time
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request
from ..models import BikeResult
from ..core.auth import get_api_key
from ..core.limiter import check_rate_limit
from ..services.search import search_products
from ..config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bikes", tags=["Bikes"])


@router.get("/search", response_model=List[BikeResult])
async def search_bikes(
    request: Request,
    q: str = Query(..., min_length=2, description="Partial make/model search string"),
    segment: Optional[str] = Query(None, description="Filter by segment (Commuter, Sports, Cruiser, Scooter)"),
    limit: int = Query(10, ge=1, le=20),
    _auth=Depends(get_api_key),
    _rate=Depends(check_rate_limit),
):
    t0 = time.monotonic()
    cache_key = f"catalyst:bikes:search:{q}:{segment}:{limit}"

    filters = {}
    if segment:
        filters["segment"] = segment

    hits = await search_products(
        request.app.state.elastic,
        request.app.state.http_client,
        request.app.state.redis,
        category="bike",
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
        if h.get("segment"):
            extras.append(h["segment"])
        if extras:
            label_parts.append(f"({', '.join(extras)})")
        display_label = " ".join(label_parts)

        results.append(BikeResult(
            id=str(h.get("id", "")),
            make=h.get("make", ""),
            model=h.get("model", ""),
            segment=h.get("segment"),
            fuel_type=h.get("fuel_type"),
            first_seen_year=h.get("first_seen_year"),
            base_price_inr=h.get("base_price_inr"),
            display_label=display_label,
        ))

    return results
