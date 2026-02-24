from fastapi import APIRouter, HTTPException, Request, Depends
from typing import Dict, Any
from ..core.templates import get_query
from ..core.security import get_api_key
import logging

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_api_key)])

def throw_http_err(status, msg):
    raise HTTPException(status_code=status, detail=msg)

@router.post("/query")
async def query_analytics(payload: Dict[str, Any], request: Request):
    """
    Internal: Run a raw SQL query against ClickHouse.
    """
    sql = payload.get("sql")
    if not sql:
        throw_http_err(400, "SQL query is required")
        
    try:
        # Basic validation: only SELECT allowed
        if not sql.strip().upper().startswith("SELECT"):
            throw_http_err(403, "Only SELECT queries are allowed via this API")
            
        db_manager = request.app.state.db_manager
        result = db_manager.client.query(sql)
        return [dict(zip(result.column_names, row)) for row in result.result_rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query Error: {e}")
        throw_http_err(500, str(e))

@router.post("/report")
async def report_analytics(payload: Dict[str, Any], request: Request):
    """
    Execute a predefined analytics template with parameters.
    """
    template_name = payload.get("template")
    params = payload.get("params", {})
    
    if not template_name:
        throw_http_err(400, "Template name is required")
        
    try:
        query = get_query(template_name, params)
        db_manager = request.app.state.db_manager
        # Using parameterized query for safety
        result = db_manager.client.query(query, parameters=params)
        return [dict(zip(result.column_names, row)) for row in result.result_rows]
    except HTTPException:
        raise
    except ValueError as ve:
        throw_http_err(404, str(ve))
    except Exception as e:
        logger.error(f"Report Error: {e}")
        throw_http_err(500, str(e))
