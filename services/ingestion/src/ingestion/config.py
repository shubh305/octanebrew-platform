from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent.parent.parent

class Settings(BaseSettings):
    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = Field("kafka:9092", validation_alias=AliasChoices("KAFKA_BOOTSTRAP_SERVERS", "KAFKA_BROKERS"))
    KAFKA_TOPIC: str = Field("octane.ingest.requests", validation_alias=AliasChoices("INGESTION_KAFKA_TOPIC", "KAFKA_TOPIC"))
    KAFKA_RESULT_TOPIC: str = "octane.ingest.results"
    KAFKA_SASL_USER: str | None = Field(None, validation_alias=AliasChoices("KAFKA_SASL_USER", "KAFKA_BROKER_USER"))
    KAFKA_SASL_PASS: str | None = Field(None, validation_alias=AliasChoices("KAFKA_SASL_PASS", "KAFKA_BROKER_PASS"))
    
    # Elasticsearch
    ES_HOST: str = "http://elasticsearch:9200"
    ES_USER: str | None = Field(None, validation_alias=AliasChoices("ES_USER", "ELASTIC_USER"))
    ES_PASSWORD: str | None = Field(None, validation_alias=AliasChoices("ES_PASSWORD", "ELASTIC_PASSWORD"))
    EMBEDDING_DIMS: int = 768
    ES_INDEX_NAME: str = "octane-search-v1"
    
    # Redis
    REDIS_URL: str = Field("redis://redis:6379", validation_alias=AliasChoices("INGESTION_REDIS_URL", "REDIS_URL"))
    POSTGRES_DSN: str = "postgresql://user:password@postgres:5432/octane"
    
    # AI Service Integration
    INTELLIGENCE_SVC_URL: str = "http://intelligence-svc:8000"
    SUMMARY_MODEL: str = "gemini-2.5-flash-lite"
    EMBEDDING_MODEL: str = "gemini-embedding-001"
    
    # Rate Limiting
    SEARCH_RATE_LIMIT_CAPACITY: int = 300
    SEARCH_RATE_LIMIT_REFILL_RATE: float = 5.0
    
    # Service settings
    LOG_LEVEL: str = "INFO"
    SERVICE_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        extra="ignore"
    )

settings = Settings()
