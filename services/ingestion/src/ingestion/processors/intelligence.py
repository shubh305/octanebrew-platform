import httpx
from ..config import settings
import logging

class IntelligenceClient:
    def __init__(self):
        self.base_url = settings.INTELLIGENCE_SVC_URL
        self.summary_model = settings.SUMMARY_MODEL
        self.embedding_model = settings.EMBEDDING_MODEL

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        results = []
        batch_size = 20
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            logging.getLogger(__name__).info(f"  Enrichment Batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1} ({len(batch)} items)")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/v1/embeddings", 
                    json={"input": batch, "model": self.embedding_model},
                    timeout=30.0,
                    headers={"X-API-KEY": settings.SERVICE_API_KEY}
                )
                response.raise_for_status()
                data = response.json()['data']
                results.extend(data)
        
        return results

    async def generate_summary(
        self, 
        text: str, 
        entity_type: str = "article",
        title: str = "",
        description: str = "",
        category: str = ""
    ) -> dict:
        """
        Generate structured summary using LLM.
        
        Returns:
            dict with keys like 'overview', 'key_concepts', 'entities', 'language'
            Format varies by entity_type (see prompts.py for schemas)
        """
        from .prompts import get_system_prompt, get_user_prompt, validate_json_response
        
        async with httpx.AsyncClient() as client:
            try:
                system_prompt = get_system_prompt(entity_type)
                user_prompt = get_user_prompt(
                    text, 
                    entity_type, 
                    title=title, 
                    description=description, 
                    category=category
                )

                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json={
                        "model": self.summary_model,
                        "prompt": user_prompt,
                        "system": system_prompt
                    },
                    timeout=60.0,
                    headers={
                        "X-App-ID": "ingestion-worker",
                        "X-API-KEY": settings.SERVICE_API_KEY
                    }
                )
                response.raise_for_status()
                data = response.json()
                raw_content = data['content']
                
                # Parse and validate JSON response
                try:
                    structured_data = validate_json_response(raw_content)
                    logging.getLogger(__name__).info(f"Successfully parsed {entity_type} summary with {len(structured_data)} fields")
                    return structured_data
                except ValueError as ve:
                    logging.getLogger(__name__).error(f"JSON validation failed: {ve}")
                    return {"summary": raw_content, "error": "json_parse_failed"}
                    
            except httpx.HTTPStatusError as e:
                logging.getLogger(__name__).error(f"Summarization HTTP error: {e.response.status_code} - {e.response.text}")
                return None
            except Exception as e:
                logging.getLogger(__name__).error(f"Summarization failed: {e}")
                return None

    async def analyze_query(self, query: str) -> dict:
        """
        Analyzes a search query using the intelligence service.
        Returns: {detected_language, original_intent, entities, expanded_terms, translated_query}
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/query/analyze",
                    json={"query": query},
                    timeout=30.0,
                    headers={
                        "X-App-ID": "search-router",
                        "X-API-KEY": settings.SERVICE_API_KEY
                    }
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logging.getLogger(__name__).error(f"Query analysis failed: {e}")
                return {
                    "detected_language": "en",
                    "original_intent": "search",
                    "entities": [],
                    "expanded_terms": [],
                    "translated_query": query
                }

    async def rerank(self, query: str, documents: list[dict]) -> dict:
        """
        Reranks a list of documents against a query using Flashrank in intelligence-svc.
        Args:
            query: The search query
            documents: List of {id, text, metadata} dicts
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/rerank/rerank",
                    json={"query": query, "documents": documents},
                    timeout=30.0,
                    headers={
                        "X-App-ID": "search-router",
                        "X-API-KEY": settings.SERVICE_API_KEY
                    }
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logging.getLogger(__name__).error(f"Reranking failed: {e}")
                return {"results": documents, "latency_ms": 0}
