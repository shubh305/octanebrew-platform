from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional
from ..core.interfaces import BaseAIProvider
from ..core.factory import get_ai_provider
from ..core.security import get_api_key
import logging
import time

from functools import partial
from ..core.limiter import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"], dependencies=[Depends(get_api_key)])

class ChatRequest(BaseModel):
    prompt: str
    system: Optional[str] = None
    model: Optional[str] = None

class ChatResponse(BaseModel):
    content: str
    provider: str

from ..config import settings

get_chat_limit = partial(
    check_rate_limit, 
    capacity=settings.CHAT_RATE_LIMIT_CAPACITY, 
    refill_rate=settings.CHAT_RATE_LIMIT_REFILL_RATE, 
    name="chat"
)

@router.post("/completions", response_model=ChatResponse, dependencies=[Depends(get_chat_limit)])
async def chat_completions(
    request: ChatRequest,
    provider: BaseAIProvider = Depends(get_ai_provider)
):
    try:
        content = await provider.generate_text(request.prompt, request.system, model=request.model)
        return ChatResponse(content=content, provider=str(type(provider).__name__))
    except Exception as e:
        error_str = str(e).lower()
        if "rate limit" in error_str or "quota" in error_str:
            raise HTTPException(status_code=429, detail="Upstream AI provider rate limited")
        elif "service" in error_str or "unavailable" in error_str:
            raise HTTPException(status_code=503, detail="AI Provider Unavailable")
        else:
            raise HTTPException(status_code=500, detail=str(e))
