from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any
from ..core.reranker import get_reranker, FlashReranker
from ..core.security import get_api_key
import logging
import time

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rerank"], dependencies=[Depends(get_api_key)])

class RerankDocument(BaseModel):
    id: str | int
    text: str
    metadata: Dict[str, Any] = {}

class RerankRequest(BaseModel):
    query: str
    documents: List[RerankDocument]

@router.post("/rerank")
async def rerank(
    request: RerankRequest,
    reranker: FlashReranker = Depends(get_reranker)
):
    """
    Reranks a list of documents against a query using Flashrank.
    """
    start_time = time.time()
    try:
        # Convert Pydantic models to dicts for Flashrank
        doc_list = [doc.model_dump() for doc in request.documents]
        
        results = reranker.rerank(request.query, doc_list)
        
        # Ensure results are JSON serializable
        for item in results:
            if 'score' in item:
                item['score'] = float(item['score'])
        
        latency = (time.time() - start_time) * 1000
        logger.info(f"Reranked {len(doc_list)} documents in {latency:.2f}ms")
        
        return {
            "query": request.query,
            "results": results,
            "latency_ms": latency
        }
    except Exception as e:
        logger.error(f"Reranking error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
