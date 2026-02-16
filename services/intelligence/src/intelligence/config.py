from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent.parent.parent

class Settings(BaseSettings):
    GOOGLE_API_KEY: str = "" 
    OPENAI_API_KEY: str = ""
    ACTIVE_PROVIDER: str = Field(None, validation_alias=AliasChoices("ACTIVE_PROVIDER", "DEFAULT_PROVIDER"))
    SERVICE_API_KEY: str = ""
    REDIS_URL: str = Field("redis://redis:6379", validation_alias=AliasChoices("INTELLIGENCE_REDIS_URL", "REDIS_URL"))
    AI_MODELS: str = "{}"
    
    DEFAULT_EMBEDDING_MODEL: str = Field(None, validation_alias=AliasChoices("DEFAULT_EMBEDDING_MODEL", "DEFAULT_OPENAI_EMBEDDING_MODEL"))
    DEFAULT_OPENAI_EMBEDDING_MODEL: str = Field(None, validation_alias=AliasChoices("DEFAULT_OPENAI_EMBEDDING_MODEL", "DEFAULT_EMBEDDING_MODEL"))
    RERANK_MODEL: str = Field("ms-marco-TinyBERT-L-2-v2", validation_alias=AliasChoices("RERANK_MODEL", "FLASH_RERANK_MODEL"))

    # Rate Limiting (Token Bucket)
    CHAT_RATE_LIMIT_CAPACITY: int = 300
    CHAT_RATE_LIMIT_REFILL_RATE: float = 5
    
    # Embeddings: 200 req/min => ~3.33 req/sec
    EMBED_RATE_LIMIT_CAPACITY: int = 2000
    EMBED_RATE_LIMIT_REFILL_RATE: float = 50

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        extra="ignore"
    )

settings = Settings()
