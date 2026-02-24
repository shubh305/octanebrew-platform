from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent.parent.parent

class Settings(BaseSettings):
    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_TOPIC: str = Field("octane.events", validation_alias=AliasChoices("ANALYTICS_KAFKA_TOPIC", "KAFKA_TOPIC"))
    KAFKA_GROUP_ID: str = Field("analytics_worker_group", validation_alias=AliasChoices("ANALYTICS_KAFKA_GROUP_ID", "KAFKA_GROUP_ID"))
    KAFKA_SASL_USER: str | None = None
    KAFKA_SASL_PASS: str | None = None

    # ClickHouse
    CLICKHOUSE_HOST: str = "clickhouse"
    CLICKHOUSE_PORT: int = 8123
    CLICKHOUSE_USER: str = "default"
    CLICKHOUSE_PASSWORD: str = ""
    CLICKHOUSE_DB: str = Field("octane_analytics", validation_alias=AliasChoices("CLICKHOUSE_DB", "ANALYTICS_DB"))

    # Batching
    BATCH_SIZE: int = Field(1000, validation_alias=AliasChoices("ANALYTICS_BATCH_SIZE", "BATCH_SIZE"))
    FLUSH_INTERVAL: float = Field(5.0, validation_alias=AliasChoices("ANALYTICS_FLUSH_INTERVAL", "FLUSH_INTERVAL"))

    # Security
    SERVICE_API_KEY: str | None = None

    # Service settings
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        extra="ignore"
    )

settings = Settings()
