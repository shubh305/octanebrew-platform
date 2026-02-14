from abc import ABC, abstractmethod

class BaseAIProvider(ABC):
    @abstractmethod
    async def generate_text(self, prompt: str, system: str = None, **kwargs) -> str:
        """
        Generate text completion for a given prompt and optional system instruction.
        """
        pass
    
    @abstractmethod
    async def generate_embeddings(self, texts: list[str], **kwargs) -> list[list[float]]:
        """
        Generate embeddings for a list of text strings.
        Returns a list of vectors.
        """
        pass
