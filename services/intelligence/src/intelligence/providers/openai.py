from ..core.interfaces import BaseAIProvider
from ..config import settings
import openai

class OpenAIProvider(BaseAIProvider):
    def __init__(self):
        self.client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def generate_embeddings(self, texts: list[str], **kwargs) -> list[list[float]]:
        response = await self.client.embeddings.create(
            input=texts,
            model=kwargs.get('model', settings.DEFAULT_OPENAI_EMBEDDING_MODEL)
        )
        return [data.embedding for data in response.data]

    async def generate_text(self, prompt: str, system: str = None, **kwargs) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        response = await self.client.chat.completions.create(
            model=kwargs.get('model', "gpt-4o"),
            messages=messages
        )
        return response.choices[0].message.content
