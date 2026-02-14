from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, field_validator
from ..core.interfaces import BaseAIProvider
from ..core.factory import get_ai_provider
from ..core.security import get_api_key
from ..core.limiter import check_rate_limit
from functools import partial
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/embeddings", tags=["embeddings"], dependencies=[Depends(get_api_key)])

class EmbeddingRequest(BaseModel):
    input: list[str] = Field(..., max_length=100, description="Max 100 texts per batch")
    model: str = "models/embedding-001"
    
    @field_validator('input')
    def check_not_empty(cls, v):
        if not v:
            raise ValueError('Input list cannot be empty')
        return v

class EmbeddingResponse(BaseModel):
    data: list[list[float]]

from ..config import settings

get_embed_limit = partial(
    check_rate_limit, 
    capacity=settings.EMBED_RATE_LIMIT_CAPACITY, 
    refill_rate=settings.EMBED_RATE_LIMIT_REFILL_RATE, 
    name="embeddings"
)

@router.post("", response_model=EmbeddingResponse, dependencies=[Depends(get_embed_limit)])
async def create_embeddings(
    request: EmbeddingRequest,
    provider: BaseAIProvider = Depends(get_ai_provider)
):
    try:
        data = await provider.generate_embeddings(request.input, model=request.model)
        return EmbeddingResponse(data=data)
    except Exception as e:
        error_str = str(e).lower()
        if "429" in error_str or "quota" in error_str or "rate limit" in error_str:
             raise HTTPException(status_code=429, detail="Upstream Rate Limit Exceeded")
        logger.error(f"Embedding failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
