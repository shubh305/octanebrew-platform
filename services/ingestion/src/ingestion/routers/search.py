import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from ..models import SearchRequest
from ..core.limiter import check_rate_limit
from functools import partial

from ..config import settings

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)

get_search_limit = partial(
    check_rate_limit, 
    capacity=settings.SEARCH_RATE_LIMIT_CAPACITY, 
    refill_rate=settings.SEARCH_RATE_LIMIT_REFILL_RATE, 
    name="search"
)

@router.post("/search", dependencies=[Depends(get_search_limit)])
async def search_content(query_request: SearchRequest, request: Request):
    """
    Hybrid Search Endpoint.
    1. Embeds query via Intelligence Service.
    2. Performs Hybrid search in Elasticsearch.
    3. Formats results with inner hit snippets.
    """
    elastic = request.app.state.elastic
    intelligence = request.app.state.intelligence
    
    if not elastic or not intelligence:
        raise HTTPException(status_code=500, detail="Search services not ready")
        
    try:
        # 1. Embed Query
        vectors = await intelligence.embed_documents([query_request.query])
        query_vector = vectors[0]
        
        # 2. Search
        hits = await elastic.search(
            query_text=query_request.query,
            vector=query_vector, 
            limit=query_request.limit, 
            filters=query_request.filters, 
            index_name=query_request.index_name,
            use_hybrid=query_request.use_hybrid,
            min_score=query_request.min_score,
            vector_threshold=query_request.vector_threshold,
            return_chunks=query_request.return_chunks
        )
        
        # 3. Format Results
        results = []
        for hit in hits:
            source = hit['_source']
            result = {
                "score": hit.get('_score') or hit.get('rank'),
                "title": source.get('title'),
                "content": source.get('content'),
                "metadata": source.get('metadata'),
                "entity_id": source.get('entity_id'),
                "source_app": source.get('source_app')
            }
            
            # Extract Matched Chunk if inner hits were requested
            if query_request.return_chunks and 'inner_hits' in hit:
                try:
                    inner_hits = hit['inner_hits']['matched_chunks']['hits']['hits']
                    if inner_hits:
                        inner_source = inner_hits[0]['_source']
                        result["matched_chunk"] = inner_source.get('text_chunk') or \
                                                  inner_source.get('chunks', {}).get('text_chunk')
                except (KeyError, IndexError):
                    pass
            
            results.append(result)
            
        return {"results": results}
        
    except Exception as e:
        logger.error(f"Search operation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal search engine error")
