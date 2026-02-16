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
        # 1. Query Intelligence
        search_query = query_request.query
        entities = []
        expanded_query = None
        
        if query_request.enable_query_analysis:
            analysis = await intelligence.analyze_query(query_request.query)
            if analysis.get('detected_language') != 'en' and analysis.get('translated_query'):
                search_query = analysis['translated_query']
                logger.info(f"Query translated: '{query_request.query}' -> '{search_query}'")
            
            entities = analysis.get('entities', [])
            
            if query_request.enable_query_expansion and analysis.get('expanded_terms'):
                expanded_query = f"{search_query} {' '.join(analysis['expanded_terms'])}"
                logger.info(f"Query expanded: '{search_query}' -> '{expanded_query}'")

        # 2. Embed Query
        embedding_text = expanded_query or search_query
        vectors = await intelligence.embed_documents([embedding_text])
        query_vector = vectors[0]
        
        # 2. Search
        # Retrieval
        retrieval_limit = max(query_request.limit * 3, 20) if query_request.enable_reranking else query_request.limit

        hits = await elastic.search(
            query_text=search_query,
            vector=query_vector, 
            limit=retrieval_limit, 
            filters=query_request.filters, 
            index_name=query_request.index_name,
            use_hybrid=query_request.use_hybrid,
            min_score=query_request.min_score,
            vector_threshold=query_request.vector_threshold,
            return_chunks=query_request.return_chunks,
            sort_by=query_request.sort_by,
            entities=entities,
            query_language=analysis.get('detected_language', 'en') if query_request.enable_query_analysis else 'en',
            debug=query_request.debug
        )

        # Reranking
        if query_request.enable_reranking and hits:
            logger.info(f"Phase D: Reranking {len(hits)} candidates...")
            
            # Prepare documents for the reranker
            rerank_docs = []
            for hit in hits:
                source = hit['_source']
                
                # Reranker: Matched Chunk > Summary > Title
                text = ""
                if 'inner_hits' in hit and 'matched_chunks' in hit['inner_hits']:
                    inner_hits = hit['inner_hits']['matched_chunks']['hits']['hits']
                    if inner_hits:
                        text = inner_hits[0]['_source'].get('text_chunk', "")
                
                if not text:
                    text = source.get('summary') or source.get('title') or ""
                
                rerank_docs.append({
                    "id": hit['_id'],
                    "text": text,
                    "metadata": hit
                })
            
            reranked = await intelligence.rerank(search_query, rerank_docs)
            
            new_hits = []
            for item in reranked.get('results', [])[:query_request.limit]:
                hit = item['metadata']
                hit['_rerank_score'] = item.get('score')
                new_hits.append(hit)
            
            hits = new_hits
            logger.info(f"Phase D: Reranking complete. Best rerank_score: {hits[0].get('_rerank_score') if hits else 'N/A'}")

        
        # 3. Format Results
        results = []
        for hit in hits:
            source = hit['_source']
            result = {
                "score": hit.get('_score'),
                "rerank_score": hit.get('_rerank_score'),
                "title": source.get('title'),
                "summary": source.get('summary'),
                "metadata": source.get('metadata'),
                "entity_id": source.get('entity_id'),
                "source_app": source.get('source_app'),
                "entities": source.get('entities', []),
                "key_concepts": source.get('key_concepts', []),
                "language": source.get('language'),
                "matched_chunk": None,
                "debug": hit.get('_debug_signals') if query_request.debug else None
            }
            
            # Extract matched chunk snippet from inner hits
            if query_request.return_chunks:
                try:
                    if 'inner_hits' in hit and 'matched_chunks' in hit['inner_hits']:
                        inner_hits = hit['inner_hits']['matched_chunks']['hits']['hits']
                        if inner_hits:
                            chunk_data = inner_hits[0]['_source']
                            result["matched_chunk"] = chunk_data.get('text_chunk') or \
                                                      chunk_data.get('chunks', {}).get('text_chunk')
                    
                    if not result["matched_chunk"] and "chunks" in source:
                        chunks = source["chunks"]
                        if isinstance(chunks, list) and len(chunks) > 0:
                            result["matched_chunk"] = chunks[0].get('text_chunk')
                except Exception as e:
                    logger.warning(f"Failed to extract matched_chunk for {result['entity_id']}: {e}")
                    pass
            
            results.append(result)
            
        return {"results": results}
        
    except Exception as e:
        logger.error(f"Search operation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal search engine error")
