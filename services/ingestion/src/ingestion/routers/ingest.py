from fastapi import APIRouter, Request, HTTPException
from ..models import IngestRequest
from ..config import settings

router = APIRouter(tags=["ingest"])

@router.post("/ingest")
async def ingest_content(payload: IngestRequest, request: Request):
    """
    Fire-and-forget ingestion. 
    Accepts content, validates schema, and pushes to Kafka for async processing.
    """
    producer = request.app.state.producer
    if not producer:
         raise HTTPException(status_code=500, detail="Kafka producer not ready")
    
    try:
        await producer.send_and_wait(settings.KAFKA_TOPIC, payload.model_dump(mode='json'))
        return {"status": "queued", "trace_id": payload.trace_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
