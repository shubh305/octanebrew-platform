import json
import logging
from typing import List, Optional
from pydantic import BaseModel, Field, ValidationError

from .prompts import QUERY_ANALYSIS_PROMPT
from ..config import settings
from .factory import get_ai_provider

logger = logging.getLogger(__name__)

class QueryAnalysis(BaseModel):
    detected_language: str = Field(description="ISO 639-1 language code")
    original_intent: str = Field(description="The primary intent of the user")
    entities: List[str] = Field(description="List of named entities found in the query")
    expanded_terms: List[str] = Field(description="List of related synonyms or expanded keywords to improve recall")
    translated_query: Optional[str] = Field(description="Query translated to English if original was different")

class QueryAnalyzer:
    def __init__(self):
        self.provider = get_ai_provider()

    async def analyze(self, query: str) -> QueryAnalysis:
        try:
            # Prepare instructions
            format_instructions = (
                "Return valid JSON matching this schema: "
                '{"detected_language": string, "original_intent": string, '
                '"entities": string[], "expanded_terms": string[], "translated_query": string|null}'
            )
            
            prompt = f"Query: {query}\n\n{format_instructions}"
            
            raw_response = await self.provider.generate_text(
                prompt=prompt,
                system=QUERY_ANALYSIS_PROMPT,
                model="fast" # Use fast model for analysis
            )
            
            # Simple JSON extraction logic
            clean_json = raw_response.strip()
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[1].split("```")[0].strip()
                
            data = json.loads(clean_json)
            return QueryAnalysis(**data)
            
        except Exception as e:
            logger.error(f"Query analysis failed: {e}")
            # Fallback to a basic analysis
            return QueryAnalysis(
                detected_language="en",
                original_intent="search",
                entities=[],
                expanded_terms=[],
                translated_query=query
            )

# Factory helper
_analyzer = None

def get_query_analyzer() -> QueryAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = QueryAnalyzer()
    return _analyzer
