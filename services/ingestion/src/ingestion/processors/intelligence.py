import httpx
from ..config import settings
import asyncio
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

    async def generate_summary(self, text: str, entity_type: str = "article") -> str:
        from .prompts import get_system_prompt, get_user_prompt
        async with httpx.AsyncClient() as client:
            try:
                system_prompt = get_system_prompt(entity_type)
                user_prompt = get_user_prompt(text, entity_type)

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
                return data['content']
            except Exception as e:
                print(f"Summarization failed: {e}")
                return None
