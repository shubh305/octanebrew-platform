from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

@router.get("/health")
async def health():
    return {"status": "healthy"}
