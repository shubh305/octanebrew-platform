from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request
import time

from ..services.search import search_products
from ..models import MobileResult
from ..core.auth import get_api_key
from ..core.limiter import check_rate_limit
from ..config import settings


router = APIRouter(prefix="/mobiles", tags=["Mobiles"])

@router.get("/search", response_model=List[MobileResult])
async def search_mobiles(
    request: Request,
    q: str = Query(..., min_length=2, description="Search term for mobiles"),
    os: Optional[str] = Query(None, description="Filter by OS (Android, iOS)"),
    has_5g: Optional[bool] = Query(None, description="Filter by 5G support"),
    limit: int = Query(10, ge=1, le=20),
    _auth=Depends(get_api_key),
    _rate=Depends(check_rate_limit),
):
    """
    Search mobiles using Elasticsearch.
    """
    t0 = time.monotonic()
    cache_key = f"catalyst:mobiles:search:{q}:{os}:{has_5g}:{limit}"
    
    filters = {}
    if os:
        filters["os"] = os
    if has_5g is not None:
        filters["has_5g"] = has_5g

    hits = await search_products(
        elastic=request.app.state.elastic,
        http_client=request.app.state.http_client,
        redis=request.app.state.redis,
        category='mobile',
        query=q,
        limit=limit,
        filters=filters,
        cache_key=cache_key,
        ttl=settings.CACHE_TTL_SECONDS,
    )

    results = []
    for h in hits:
        extras = []
        if h.get("first_seen_year"):
            extras.append(str(h["first_seen_year"]))
        if h.get("os"):
            extras.append(h["os"])
        if h.get("ram_gb"):
            extras.append(f"{h['ram_gb']}GB RAM")
        if h.get("has_5g") is not None:
            extras.append("5G" if h["has_5g"] else "4G")
        if h.get("base_price_inr"):
            extras.append(f"₹{h['base_price_inr']:,}")
            
        display_label = " • ".join(extras) if extras else f"{h.get('make', '')} {h.get('model', '')}".strip()

        results.append(MobileResult(
            id=str(h.get("id", "")),
            make=h.get("make", ""),
            model=h.get("model", ""),
            variant=h.get("variant"),
            os=h.get("os"),
            has_5g=h.get("has_5g"),
            ram_gb=h.get("ram_gb"),
            storage_gb=h.get("storage_gb"),
            first_seen_year=h.get("first_seen_year"),
            base_price_inr=h.get("base_price_inr"),
            display_label=display_label,
        ))

    return results
