from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, Optional, Literal
from datetime import datetime

class IngestRequest(BaseModel):
    trace_id: str
    source_app: str
    entity_id: str
    entity_type: str = "article"
    operation: str = "index"
    timestamp: datetime
    payload: Dict[str, Any]
    enrichments: list[str] = []
    index_name: Optional[str] = None
    chunking_strategy: str = "recursive"
    chunk_size: int = 500
    chunk_overlap: int = 50

    
    @field_validator('payload')
    def validate_payload(cls, v, values):
        if 'operation' in values.data and values.data['operation'] == 'index':
            if 'text' not in v and 'content' not in v:
                pass
        return v

class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    filters: Optional[Dict[str, Any]] = None
    index_name: Optional[str] = None
    use_hybrid: bool = True
    min_score: float = 25.0
    vector_threshold: float = 0.65
    return_chunks: bool = True
    sort_by: Literal["relevancy", "recency", "balanced"] = "relevancy"
    enable_query_expansion: bool = False
    enable_query_analysis: bool = True
    enable_reranking: bool = False
    debug: bool = False
