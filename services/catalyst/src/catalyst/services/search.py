"""
Elasticsearch query + Intelligence Service reranking for search endpoints.
Implements the full search pipeline:
  1. ES fuzzy query on catalyst_products index
  2. Intelligence Service cross-encoder reranking (with circuit-breaker fallback)
  3. Response mapping to typed result models
"""
import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from elasticsearch import AsyncElasticsearch

from ..config import settings
from ..core.observability import SEARCH_REQUESTS_TOTAL, SEARCH_LATENCY, record_cache_result

logger = logging.getLogger(__name__)

# Circuit-breaker state
_rerank_failures = 0
_rerank_circuit_open = False
_CIRCUIT_OPEN_THRESHOLD = 3


async def search_products(
    elastic: AsyncElasticsearch,
    http_client: httpx.AsyncClient,
    redis,
    *,
    category: str,
    query: str,
    limit: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    cache_key: str,
    ttl: int = 300,
) -> List[Dict[str, Any]]:
    """
    Full search pipeline: Redis cache → ES fuzzy query → Intel rerank → cache write.
    Returns list of raw hit dicts (caller maps to typed models).
    """
    from ..core.cache import cache_get, cache_set

    t0 = time.monotonic()

    # 1. Cache check
    cached = await cache_get(redis, cache_key)
    if cached is not None:
        record_cache_result(hit=True)
        SEARCH_REQUESTS_TOTAL.labels(category=category, status="cache_hit").inc()
        return cached
    record_cache_result(hit=False)

    # 2. Elasticsearch fuzzy query
    es_results = await _es_query(elastic, category=category, query=query, filters=filters, top_n=20)

    # 3. Intelligence Service reranking (with circuit-breaker)
    reranked = await _rerank(http_client, query=query, hits=es_results, top_n=limit)

    results = reranked[:limit]

    # 4. Cache results
    await cache_set(redis, cache_key, results, ttl=ttl)

    elapsed = time.monotonic() - t0
    SEARCH_LATENCY.labels(category=category).observe(elapsed)
    SEARCH_REQUESTS_TOTAL.labels(category=category, status="ok").inc()

    return results


async def _es_query(
    elastic: AsyncElasticsearch,
    *,
    category: str,
    query: str,
    filters: Optional[Dict[str, Any]],
    top_n: int = 20,
) -> List[Dict[str, Any]]:
    """Run a fuzzy bool query against the catalyst_products ES index."""
    must_clauses = [
        {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["name^5", "brand_or_author^3", "specs_summary"],
                            "fuzziness": "AUTO",
                            "type": "best_fields",
                            "boost": 1.0
                        }
                    },
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["name^5", "brand_or_author^10", "specs_summary"],
                            "type": "phrase_prefix",
                            "boost": 10.0
                        }
                    }
                ],
                "minimum_should_match": 1
            }
        }
    ]
    filter_clauses = [{"term": {"category": category}}]

    if filters:
        for field, value in filters.items():
            if value is not None:
                filter_clauses.append({"term": {field: value}})

    body = {
        "query": {
            "bool": {
                "must": must_clauses,
                "filter": filter_clauses,
            }
        },
        "size": top_n,
    }

    try:
        resp = await elastic.search(index=settings.ES_PRODUCTS_INDEX, **body)
        hits = resp["hits"]["hits"]
        return [{"id": h["_id"], "_score": h["_score"], **h["_source"]} for h in hits]
    except Exception as e:
        logger.error("Elasticsearch query failed: %s", e)
        return []


async def _rerank(
    http_client: httpx.AsyncClient,
    *,
    query: str,
    hits: List[Dict[str, Any]],
    top_n: int,
) -> List[Dict[str, Any]]:
    """
    Call Intelligence Service cross-encoder reranker.
    Falls back to ES-ranked results on failure (circuit-breaker pattern).
    """
    global _rerank_failures, _rerank_circuit_open

    if not hits:
        return []

    if _rerank_circuit_open:
        logger.warning("Rerank circuit open — returning ES results directly (degraded mode)")
        SEARCH_REQUESTS_TOTAL.labels(category="all", status="degraded").inc()
        return hits[:top_n]

    rerank_docs = [{"id": str(i), "text": h.get("name", h.get("title", ""))} for i, h in enumerate(hits)]

    try:
        resp = await http_client.post(
            "/v1/rerank/rerank",
            json={"query": query, "documents": rerank_docs},
            timeout=5.0,
        )
        resp.raise_for_status()
        ranked_results = resp.json().get("results", [])
        ranked_indices = [int(item["id"]) for item in ranked_results]
        _rerank_failures = 0
        _rerank_circuit_open = False
        final_hits = [hits[i] for i in ranked_indices if i < len(hits)]
        return final_hits if final_hits else hits[:top_n]
    except Exception as e:
        _rerank_failures += 1
        logger.warning("Rerank call failed (%d/%d): %s", _rerank_failures, _CIRCUIT_OPEN_THRESHOLD, e)
        if _rerank_failures >= _CIRCUIT_OPEN_THRESHOLD:
            _rerank_circuit_open = True
            logger.error("Rerank circuit breaker OPENED — degraded mode active")
        return hits[:top_n]
