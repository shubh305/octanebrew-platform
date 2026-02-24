from pydantic import BaseModel, model_validator
from typing import Dict, Any, Optional
from datetime import datetime

class AnalyticsEvent(BaseModel):
    app_id: str
    event_name: str
    user_id: str
    timestamp: datetime
    properties: Dict[str, Any]
    trace_id: Optional[str] = None

    @model_validator(mode='before')
    @classmethod
    def map_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Map legacy 'event' to 'event_name'
            if 'event' in data and 'event_name' not in data:
                data['event_name'] = data.pop('event')
            
            # Map legacy 'ts' (ms or s timestamp) to 'timestamp'
            if 'ts' in data and 'timestamp' not in data:
                ts = data.pop('ts')
                if isinstance(ts, (int, float)):
                    if ts > 10**12: # Likely ms
                         data['timestamp'] = datetime.fromtimestamp(ts / 1000.0)
                    else:
                         data['timestamp'] = datetime.fromtimestamp(ts)
                else:
                    data['timestamp'] = ts

            # Provide safe defaults if missing
            if 'app_id' not in data:
                data['app_id'] = 'unknown'
            if 'user_id' not in data:
                data['user_id'] = 'anonymous'
            
            # If properties missing, wrap extra fields
            if 'properties' not in data:
                standard_keys = {'app_id', 'event_name', 'user_id', 'timestamp', 'trace_id'}
                data['properties'] = {k: v for k, v in data.items() if k not in standard_keys}
                
        return data
