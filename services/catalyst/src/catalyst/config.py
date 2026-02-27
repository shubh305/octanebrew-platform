from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).parent.parent.parent.parent.parent.parent

class Settings(BaseSettings):
    # Service Identity
    SERVICE_NAME: str = "catalyst"
    PORT: int = 8002

    # Auth
    SERVICE_API_KEY: str = Field("", validation_alias=AliasChoices("SERVICE_API_KEY"))

    # PostgreSQL
    POSTGRES_DSN: str = Field(..., validation_alias=AliasChoices("POSTGRES_DSN"))

    # Elasticsearch
    ES_HOST: str = Field("http://elasticsearch:9200", validation_alias=AliasChoices("ES_HOST", "ELASTICSEARCH_URL"))
    ELASTIC_USER: Optional[str] = Field(None, validation_alias=AliasChoices("ELASTIC_USER", "ES_USER"))
    ELASTIC_PASSWORD: Optional[str] = Field(None, validation_alias=AliasChoices("ELASTIC_PASSWORD", "ES_PASSWORD"))
    ES_PRODUCTS_INDEX: str = Field("catalyst_products", validation_alias=AliasChoices("ES_PRODUCTS_INDEX"))

    # Redis
    REDIS_URL: str = Field(..., validation_alias=AliasChoices("REDIS_URL"))
    CACHE_TTL_SECONDS: int = Field(300, validation_alias=AliasChoices("CACHE_TTL_SECONDS"))
    RATE_LIMIT_PER_MINUTE: int = Field(120, validation_alias=AliasChoices("RATE_LIMIT_PER_MINUTE"))

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = Field("kafka:9092", validation_alias=AliasChoices("KAFKA_BOOTSTRAP_SERVERS"))
    KAFKA_SASL_USER: Optional[str] = Field(None, validation_alias=AliasChoices("KAFKA_SASL_USER", "KAFKA_BROKER_USER"))
    KAFKA_SASL_PASS: Optional[str] = Field(None, validation_alias=AliasChoices("KAFKA_SASL_PASS", "KAFKA_BROKER_PASS"))
    KAFKA_REDDIT_POSTS_TOPIC: str = Field("octane.catalyst.reddit_posts", validation_alias=AliasChoices("KAFKA_REDDIT_POSTS_TOPIC"))
    KAFKA_MATCH_JOBS_TOPIC: str = Field("octane.catalyst.match_jobs", validation_alias=AliasChoices("KAFKA_MATCH_JOBS_TOPIC"))

    # Intelligence Service
    INTELLIGENCE_SVC_URL: str = Field("http://intelligence-svc:8000", validation_alias=AliasChoices("INTELLIGENCE_SVC_URL"))
    INTELLIGENCE_RERANK_ENDPOINT: str = Field("/v1/rerank", validation_alias=AliasChoices("INTELLIGENCE_RERANK_ENDPOINT"))

    # Reddit (PRAW)
    REDDIT_CLIENT_ID: Optional[str] = Field(None, validation_alias=AliasChoices("REDDIT_CLIENT_ID"))
    REDDIT_CLIENT_SECRET: Optional[str] = Field(None, validation_alias=AliasChoices("REDDIT_CLIENT_SECRET"))
    REDDIT_USER_AGENT: str = Field("catalyst-watcher/1.0 by OctaneBrew", validation_alias=AliasChoices("REDDIT_USER_AGENT"))

    # Kaggle
    KAGGLE_USERNAME: Optional[str] = Field(None, validation_alias=AliasChoices("KAGGLE_USERNAME"))
    KAGGLE_KEY: Optional[str] = Field(None, validation_alias=AliasChoices("KAGGLE_KEY"))

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = Field(None, validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_ENDPOINT"))
    LOG_LEVEL: str = Field("INFO", validation_alias=AliasChoices("LOG_LEVEL"))

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        extra="ignore"
    )

settings = Settings()
