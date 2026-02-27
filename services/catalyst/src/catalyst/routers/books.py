"""
GET /books/search — autocomplete endpoint for Conduit's /books slash command.
"""
import time
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request
from ..models import BookResult
from ..core.auth import get_api_key
from ..core.limiter import check_rate_limit
from ..services.search import search_products
from ..config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/books", tags=["Books"])


@router.get("/search", response_model=List[BookResult])
async def search_books(
    request: Request,
    q: str = Query(..., min_length=2, description="Title or author search string"),
    year: Optional[int] = Query(None, description="Filter by publication year"),
    genre: Optional[str] = Query(None, description="Filter by genre"),
    limit: int = Query(10, ge=1, le=20),
    _auth=Depends(get_api_key),
    _rate=Depends(check_rate_limit),
):
    t0 = time.monotonic()
    cache_key = f"catalyst:books:search:{q}:{year}:{genre}:{limit}"

    filters = {}
    if year:
        filters["publication_year"] = year
    if genre:
        filters["genre"] = genre

    hits = await search_products(
        request.app.state.elastic,
        request.app.state.http_client,
        request.app.state.redis,
        category="book",
        query=q,
        limit=limit,
        filters=filters,
        cache_key=cache_key,
        ttl=settings.CACHE_TTL_SECONDS,
    )

    results = []
    for h in hits:
        author = h.get("brand_or_author", h.get("author", ""))
        year_val = h.get("first_seen_year") or h.get("publication_year")
        label = h.get("name", h.get("title", ""))
        if author:
            label += f" — {author}"
        if year_val:
            label += f" ({year_val})"

        results.append(BookResult(
            id=str(h.get("id", "")),
            title=h.get("name", h.get("title", "")),
            author=author or None,
            genre=h.get("genre"),
            publication_year=year_val,
            average_rating=h.get("average_rating"),
            display_label=label,
        ))

    return results
