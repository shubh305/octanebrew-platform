from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).parent.parent.parent.parent.parent

class Settings(BaseSettings):
    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = Field(None, validation_alias=AliasChoices("KAFKA_BOOTSTRAP_SERVERS", "KAFKA_BROKERS"))
    KAFKA_TOPIC: str = Field(None, validation_alias=AliasChoices("INGESTION_KAFKA_TOPIC", "KAFKA_TOPIC"))
    KAFKA_RESULT_TOPIC: str = Field(None, validation_alias=AliasChoices("INGESTION_KAFKA_RESULT_TOPIC", "KAFKA_RESULT_TOPIC"))
    OPENSTREAM_KAFKA_TOPIC: str = Field("openstream.ingest.requests", validation_alias=AliasChoices("OPENSTREAM_KAFKA_TOPIC"))
    OPENSTREAM_KAFKA_RESULT_TOPIC: str = Field("openstream.ingest.results", validation_alias=AliasChoices("OPENSTREAM_KAFKA_RESULT_TOPIC"))

    KAFKA_GROUP_ID: Optional[str] = Field(None, validation_alias=AliasChoices("INGESTION_KAFKA_GROUP_ID", "KAFKA_GROUP_ID"))
    
    KAFKA_SASL_USER: Optional[str] = Field(None, validation_alias=AliasChoices("KAFKA_SASL_USER", "KAFKA_BROKER_USER"))
    KAFKA_SASL_PASS: Optional[str] = Field(None, validation_alias=AliasChoices("KAFKA_SASL_PASS", "KAFKA_BROKER_PASS"))
    
    # Elasticsearch
    ES_HOST: str = Field(None, validation_alias=AliasChoices("ES_HOST", "ELASTICSEARCH_URL"))
    ES_USER: Optional[str] = Field(None, validation_alias=AliasChoices("ES_USER", "ELASTIC_USER"))
    ES_PASSWORD: Optional[str] = Field(None, validation_alias=AliasChoices("ES_PASSWORD", "ELASTIC_PASSWORD"))
    EMBEDDING_DIMS: int = Field(3072, validation_alias=AliasChoices("EMBEDDING_DIMS"))
    ES_INDEX_NAME: str = Field(None, validation_alias=AliasChoices("ES_INDEX_NAME"))
    
    # DB
    REDIS_URL: str = Field(None, validation_alias=AliasChoices("INGESTION_REDIS_URL", "REDIS_URL"))
    POSTGRES_DSN: str = Field(None, validation_alias=AliasChoices("POSTGRES_DSN"))
    
    # AI Service Integration
    INTELLIGENCE_SVC_URL: str = Field(None, validation_alias=AliasChoices("INTELLIGENCE_SVC_URL"))
    SUMMARY_MODEL: str = Field(None, validation_alias=AliasChoices("SUMMARY_MODEL"))
    EMBEDDING_MODEL: str = Field(None, validation_alias=AliasChoices("EMBEDDING_MODEL"))
    
    # Rate Limiting
    SEARCH_RATE_LIMIT_CAPACITY: int = 300
    SEARCH_RATE_LIMIT_REFILL_RATE: float = 5.0
    
    # Service settings
    LOG_LEVEL: str = Field("INFO", validation_alias=AliasChoices("LOG_LEVEL"))
    SERVICE_API_KEY: str = Field("", validation_alias=AliasChoices("SERVICE_API_KEY"))

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        extra="ignore"
    )

settings = Settings()
