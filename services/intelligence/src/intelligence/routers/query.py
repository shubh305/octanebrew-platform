from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..core.analyzer import get_query_analyzer, QueryAnalysis, QueryAnalyzer
from ..core.security import get_api_key
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["query"], dependencies=[Depends(get_api_key)])

class AnalyzeRequest(BaseModel):
    query: str

@router.post("/analyze", response_model=QueryAnalysis)
async def analyze_query(
    request: AnalyzeRequest,
    analyzer: QueryAnalyzer = Depends(get_query_analyzer)
):
    """
    Analyzes a user query for language, intent, entities, and expansion terms.
    """
    try:
        return await analyzer.analyze(request.query)
    except Exception as e:
        logger.error(f"Error analyzing query: {e}")
        raise HTTPException(status_code=500, detail=str(e))
