from typing import List, Dict, Any
from flashrank import Ranker, RerankRequest
import logging

from ..config import settings

logger = logging.getLogger(__name__)

class FlashReranker:
    def __init__(self, model_name: str = None):
        """
        Initializes the Flashrank Ranker.
        """
        try:
            target_model = model_name or settings.RERANK_MODEL
            logger.info(f"Initializing Flashrank with model: {target_model}")
            self.ranker = Ranker(model_name=target_model, cache_dir="/tmp/flashrank_cache")
        except Exception as e:
            logger.error(f"Failed to initialize Flashrank: {e}")
            self.ranker = None

    def rerank(self, query: str, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Reranks a list of documents based on a query.
        Each document should be a dict with at least 'id' and 'text'.
        """
        if not self.ranker or not documents:
            return documents

        try:
            rerank_request = RerankRequest(query=query, passages=documents)
            results = self.ranker.rerank(rerank_request)
            return results
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return documents

_reranker = None

def get_reranker() -> FlashReranker:
    global _reranker
    if _reranker is None:
        _reranker = FlashReranker()
    return _reranker
