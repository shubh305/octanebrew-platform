from functools import lru_cache
from ..config import settings
from .interfaces import BaseAIProvider
from ..providers.gemini import GeminiProvider
from ..providers.openai import OpenAIProvider

@lru_cache()
def get_ai_provider() -> BaseAIProvider:
    provider_name = settings.ACTIVE_PROVIDER.lower()
    
    if provider_name == "openai":
        return OpenAIProvider()
    elif provider_name == "gemini":
        return GeminiProvider()
    else:
        # Default fallback
        return GeminiProvider()
