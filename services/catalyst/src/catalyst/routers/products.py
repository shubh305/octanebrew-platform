"""
GET /products/{id} — full product detail + optional Reddit discussions.
Called by Conduit after user selects an autocomplete result.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from ..models import ProductDetail, RedditDiscussion
from ..core.auth import get_api_key
from ..services.db import (
    get_product_by_id, get_car_specs, get_bike_specs,
    get_book_specs, get_mobile_specs, get_reddit_discussions
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["Products"])


@router.get("/{product_id}", response_model=ProductDetail)
async def get_product(
    request: Request,
    product_id: str,
    include_reddit: bool = Query(True, description="Include Reddit discussions"),
    _auth=Depends(get_api_key),
):
    pool = request.app.state.db_pool

    # Base product
    product = await get_product_by_id(pool, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    category = product["category"]

    # Category-specific specs
    specs = {}
    if category == "car":
        specs_row = await get_car_specs(pool, product_id)
        if specs_row:
            specs = {k: v for k, v in specs_row.items() if v is not None}
    elif category == "bike":
        specs_row = await get_bike_specs(pool, product_id)
        if specs_row:
            specs = {k: v for k, v in specs_row.items() if v is not None}
    elif category == "book":
        specs_row = await get_book_specs(pool, product_id)
        if specs_row:
            specs = {k: v for k, v in specs_row.items() if v is not None}
    elif category == "mobile":
        specs_row = await get_mobile_specs(pool, product_id)
        if specs_row:
            specs = {k: v for k, v in specs_row.items() if v is not None}

    # Reddit discussions
    reddit_discussions = []
    if include_reddit:
        raw_discussions = await get_reddit_discussions(pool, product_id, limit=10)
        reddit_discussions = [
            RedditDiscussion(
                reddit_id=d["reddit_id"],
                title=d["title"],
                url=d.get("url", ""),
                score=d.get("score", 0),
                num_comments=d.get("num_comments", 0),
                created_utc=d.get("created_utc"),
                link_confidence=d.get("link_confidence", 0.0),
            )
            for d in raw_discussions
        ]

    return ProductDetail(
        id=str(product["id"]),
        category=category,
        name=product["name"],
        brand_or_author=product.get("brand_or_author"),
        first_seen_year=product.get("first_seen_year"),
        region=product.get("region", "IN"),
        specs=specs,
        reddit_discussions=reddit_discussions,
    )
