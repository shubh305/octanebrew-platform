from google import genai
from google.genai import types
from ..core.interfaces import BaseAIProvider
from ..config import settings
import asyncio
import logging
import json

logger = logging.getLogger(__name__)

class GeminiProvider(BaseAIProvider):
    def __init__(self):
        try:
            self.client = genai.Client(api_key=settings.GOOGLE_API_KEY)
            self.models_config = {}
            if settings.AI_MODELS:
                try:
                    self.models_config = json.loads(settings.AI_MODELS)
                except Exception as e:
                    logger.error(f"Failed to parse AI_MODELS JSON: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini Client: {e}")
            raise

    def _get_model_id(self, requested_alias: str) -> str:
        if requested_alias in self.models_config:
            return self.models_config[requested_alias].get("model", requested_alias)
        # Default fallback
        if "default" in self.models_config:
            return self.models_config["default"].get("model", "gemini-1.5-flash")
        return "gemini-1.5-flash"

    async def generate_embeddings(self, texts: list[str], **kwargs) -> list[list[float]]:
        try:
            model_id = kwargs.get('model') or settings.DEFAULT_EMBEDDING_MODEL
            loop = asyncio.get_running_loop()
            
            response = await loop.run_in_executor(
                None,
                lambda: self.client.models.embed_content(
                    model=model_id,
                    contents=texts,
                    config=types.EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT",
                        title="Embedding"
                    )
                )
            )
            return [e.values for e in response.embeddings]
        except Exception as e:
            logger.error(f"Gemini Embedding Error: {e}")
            raise

    async def generate_text(self, prompt: str, system: str = None, **kwargs) -> str:
        try:
            model_alias = kwargs.get('model') or "default"
            model_id = self._get_model_id(model_alias)
            
            config = None
            if system:
                config = types.GenerateContentConfig(
                    system_instruction=system
                )

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=config
                )
            )
            if not response.text:
                logger.warning("Gemini returned empty response")
                return ""
            return response.text
        except Exception as e:
            logger.error(f"Gemini Chat Error (Model: {model_id}): {e}")
            raise
