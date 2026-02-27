"""
PostgreSQL query helpers — product details + Reddit discussions.
Uses asyncpg connection pool from app.state.db_pool.
"""
import logging
from typing import Any, Dict, List, Optional
import asyncpg

logger = logging.getLogger(__name__)


async def get_product_by_id(
    pool: asyncpg.Pool,
    product_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch base product data from catalyst.products."""
    query = """
        SELECT p.id, p.category, p.name, p.brand_or_author, p.region, p.first_seen_year,
               p.source_dataset, p.created_at
        FROM catalyst.products p
        WHERE p.id = $1
    """
    row = await pool.fetchrow(query, product_id)
    return dict(row) if row else None


async def get_car_specs(pool: asyncpg.Pool, product_id: str) -> Optional[Dict[str, Any]]:
    """Fetch car detail from catalyst.cars by product_id."""
    query = """
        SELECT make, model, variant, body_type, fuel_type, transmission,
               engine_cc, max_power_bhp, max_torque_nm, seating_capacity,
               base_price_inr, monthly_sales, specs
        FROM catalyst.cars WHERE product_id = $1
    """
    row = await pool.fetchrow(query, product_id)
    if not row:
        return None
    d = dict(row)
    if d.get("specs"):
        import json
        try:
            extra = d.pop("specs")
            if isinstance(extra, str):
                extra = json.loads(extra)
            d.update(extra)
        except Exception:
            pass
    return d


async def get_bike_specs(pool: asyncpg.Pool, product_id: str) -> Optional[Dict[str, Any]]:
    """Fetch bike detail from catalyst.bikes by product_id."""
    query = """
        SELECT make, model, variant, segment, fuel_type, engine_cc,
               max_power_bhp, max_torque_nm, mileage_kmpl, weight_kg,
               base_price_inr, on_road_price_inr, specs
        FROM catalyst.bikes WHERE product_id = $1
    """
    row = await pool.fetchrow(query, product_id)
    if not row:
        return None
    d = dict(row)
    if d.get("specs"):
        import json
        try:
            extra = d.pop("specs")
            if isinstance(extra, str):
                extra = json.loads(extra)
            d.update(extra)
        except Exception:
            pass
    return d


async def get_book_specs(pool: asyncpg.Pool, product_id: str) -> Optional[Dict[str, Any]]:
    """Fetch book detail from catalyst.books by product_id."""
    query = """
        SELECT title, author, isbn, publisher, publication_year, language,
               genre, average_rating, rating_count
        FROM catalyst.books WHERE product_id = $1
    """
    row = await pool.fetchrow(query, product_id)
    return dict(row) if row else None


async def get_mobile_specs(pool: asyncpg.Pool, product_id: str) -> Optional[Dict[str, Any]]:
    """Fetch mobile detail from catalyst.mobiles by product_id."""
    query = """
        SELECT 
            brand, model, variant, screen_size_in, resolution, display_type, 
            refresh_rate_hz, ppi, chipset, cpu_cores, cpu_speed_ghz, gpu, 
            ram_gb, storage_gb, expandable_storage, rear_camera_mp, 
            rear_camera_count, front_camera_mp, battery_mah, fast_charging_w, 
            wireless_charging, has_5g, has_4g, has_nfc, os, os_version, 
            base_price_inr, launch_year, specs
        FROM catalyst.mobiles WHERE product_id = $1
    """
    row = await pool.fetchrow(query, product_id)
    if not row:
        return None
    d = dict(row)
    if d.get("specs"):
        import json
        try:
            extra = d.pop("specs")
            if isinstance(extra, str):
                extra = json.loads(extra)
            d.update(extra)
        except Exception:
            pass
    return d


async def get_reddit_discussions(
    pool: asyncpg.Pool, product_id: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """Fetch top Reddit discussions linked to a product, ordered by confidence then score."""
    query = """
        SELECT rp.reddit_id, rp.title, rp.url, rp.score, rp.num_comments,
               rp.created_utc, rl.link_confidence
        FROM catalyst.product_reddit_links rl
        JOIN catalyst.reddit_posts rp ON rp.id = rl.reddit_post_id
        WHERE rl.product_id = $1
        ORDER BY rl.link_confidence DESC, rp.score DESC
        LIMIT $2
    """
    rows = await pool.fetch(query, product_id, limit)
    results = []
    for row in rows:
        d = dict(row)
        if d.get("created_utc"):
            d["created_utc"] = d["created_utc"].isoformat()
        results.append(d)
    return results


async def count_products_by_category(pool: asyncpg.Pool) -> Dict[str, int]:
    """Return count of products per category for Prometheus gauge."""
    query = """
        SELECT category::text, COUNT(*) AS cnt
        FROM catalyst.products
        GROUP BY category
    """
    rows = await pool.fetch(query)
    return {row["category"]: row["cnt"] for row in rows}
