import json
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from fastapi_limiter.depends import RateLimiter
import redis.asyncio as aioredis
from ..core.engine import engine
from ..config import settings
from ..core.security import get_api_key

router = APIRouter()

# Initialize redis for caching
redis_client = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)

class LookupRequest(BaseModel):
    word: str

class Definition(BaseModel):
    definition: str
    synonyms: List[str]
    antonyms: List[str]
    example: Optional[str] = None

class Meaning(BaseModel):
    partOfSpeech: str
    definitions: List[Definition]
    synonyms: List[str]
    antonyms: List[str]

class OctaneBrewMetadata(BaseModel):
    detected_language: str
    translation: Optional[str] = None
    analysis_word: str
    plurals: List[str]
    is_correct: bool
    suggestions: List[str]

class Entry(BaseModel):
    word: str
    phonetic: Optional[str] = None
    phonetics: List[dict] = []
    meanings: List[Meaning]
    metadata: OctaneBrewMetadata

@router.post(
    "/lookup", 
    response_model=List[Entry],
    dependencies=[
        Depends(RateLimiter(times=1000, seconds=60)),
        Depends(get_api_key)
    ]
)
async def lookup_word(request: LookupRequest):
    cache_key = f"dict_cache:{request.word.lower()}"
    
    try:
        # 1. Try to get from Cache
        cached_result = await redis_client.get(cache_key)
        if cached_result:
            return json.loads(cached_result)

        # 2. Perform Analysis
        result = engine.analyze(request.word)
        
        # 3. Save to Cache (1 hour expiry)
        await redis_client.setex(cache_key, 3600, json.dumps(result))
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
