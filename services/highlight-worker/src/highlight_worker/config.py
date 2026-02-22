"""Settings module — environment variables and YAML config loading."""

import yaml
import logging
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from typing import Optional

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent.parent.parent.parent


class Settings(BaseSettings):
    """Environment variables for the highlight worker."""

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = Field(
        None,
        validation_alias=AliasChoices("KAFKA_BOOTSTRAP_SERVERS", "KAFKA_BROKERS"),
    )
    KAFKA_GROUP_ID: str = Field(
        "highlight-worker",
        validation_alias=AliasChoices("HIGHLIGHT_KAFKA_GROUP_ID", "KAFKA_GROUP_ID"),
    )
    KAFKA_SASL_USER: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("KAFKA_SASL_USER", "KAFKA_BROKER_USER"),
    )
    KAFKA_SASL_PASS: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("KAFKA_SASL_PASS", "KAFKA_BROKER_PASS"),
    )

    # Kafka Topics
    KAFKA_TOPIC_HIGHLIGHTS_REQUEST: str = Field(
        "video.highlights.request",
        validation_alias=AliasChoices("KAFKA_TOPIC_HIGHLIGHTS_REQUEST"),
    )
    KAFKA_TOPIC_HIGHLIGHTS_COMPLETE: str = Field(
        "video.highlights.complete",
        validation_alias=AliasChoices("KAFKA_TOPIC_HIGHLIGHTS_COMPLETE"),
    )
    KAFKA_TOPIC_HIGHLIGHTS_DEGRADED: str = Field(
        "video.highlights.degraded",
        validation_alias=AliasChoices("KAFKA_TOPIC_HIGHLIGHTS_DEGRADED"),
    )
    KAFKA_TOPIC_HIGHLIGHTS_FAILED: str = Field(
        "video.highlights.failed",
        validation_alias=AliasChoices("KAFKA_TOPIC_HIGHLIGHTS_FAILED"),
    )

    # MinIO
    MINIO_ENDPOINT: str = Field(
        "minio:9000", validation_alias=AliasChoices("MINIO_ENDPOINT")
    )
    MINIO_ROOT_USER: str = Field(
        None, validation_alias=AliasChoices("MINIO_ROOT_USER", "MINIO_ACCESS_KEY")
    )
    MINIO_ROOT_PASSWORD: str = Field(
        None,
        validation_alias=AliasChoices("MINIO_ROOT_PASSWORD", "MINIO_SECRET_KEY"),
    )
    MINIO_BUCKET: str = Field(
        "openstream-uploads", validation_alias=AliasChoices("MINIO_BUCKET")
    )
    MINIO_SECURE: bool = False

    # Intelligence Service
    INTELLIGENCE_SVC_URL: str = Field(
        None, validation_alias=AliasChoices("INTELLIGENCE_SVC_URL")
    )
    SERVICE_API_KEY: str = Field(
        "", validation_alias=AliasChoices("SERVICE_API_KEY", "SHARED_API_KEY")
    )

    # Redis
    REDIS_URL: str = Field(
        "redis://redis:6379",
        validation_alias=AliasChoices("HIGHLIGHT_REDIS_URL", "REDIS_URL"),
    )
    LOCK_KEY: str = Field("highlight:lock", validation_alias=AliasChoices("LOCK_KEY"))
    LOCK_TTL: int = Field(1800, validation_alias=AliasChoices("LOCK_TTL"))

    # Postgres (for oplog)
    POSTGRES_DSN: str = Field(
        None, validation_alias=AliasChoices("POSTGRES_DSN")
    )

    # Resource Governance
    MAX_CPU_PERCENT: int = 60
    MAX_MEMORY_MB: int = 900
    JOB_TIMEOUT_SECONDS: int = 1800

    # Paths
    CONFIG_PATH: str = Field(
        "config/highlight_config.yaml",
        validation_alias=AliasChoices("HIGHLIGHT_CONFIG_PATH"),
    )
    OPENSTREAM_VOL_PATH: str = Field(
        "/minio_data",
        validation_alias=AliasChoices("OPENSTREAM_VOL_PATH"),
    )

    # Logging
    LOG_LEVEL: str = Field("INFO", validation_alias=AliasChoices("LOG_LEVEL"))

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"), extra="ignore"
    )


settings = Settings()


def load_yaml_config(path: str | None = None) -> dict:
    """Load and return the YAML highlight config, falling back to defaults."""
    config_path = Path(path or settings.CONFIG_PATH)

    # Try relative to CWD first, then absolute
    if not config_path.is_absolute():
        candidates = [
            Path.cwd() / config_path,
            Path(__file__).parent.parent.parent / config_path,
        ]
    else:
        candidates = [config_path]

    for candidate in candidates:
        if candidate.exists():
            logger.info(f"Loading highlight config from {candidate}")
            with open(candidate) as f:
                return yaml.safe_load(f)

    logger.warning(f"Config not found at {config_path}, using built-in defaults")
    return _default_config()


def _default_config() -> dict:
    """Built-in fallback configuration."""
    return {
        "scoring": {
            "qualification_threshold": 0.35,
            "max_clips": 5,
            "min_clip_duration": 8,
            "max_clip_duration": 60,
            "context_buffer": 3,
            "min_gap": 5,
        },
        "signals": {
            "audio_spike": {
                "enabled": True,
                "weight": 0.30,
                "rms_threshold": 0.15,
                "min_consecutive_frames": 3,
                "hop_size": 0.5,
            },
            "scene_change": {
                "enabled": True,
                "weight": 0.25,
                "score_threshold": 0.35,
                "min_interval": 2.0,
            },
            "chat_spike": {
                "enabled": True,
                "weight": 0.20,
                "bucket_size": 10,
                "spike_multiplier": 2.5,
            },
            "ocr_keyword": {"enabled": False, "weight": 0.15},
            "vtt_semantic": {"enabled": True, "weight": 0.10},
        },
        "governance": {
            "max_cpu_percent": 60,
            "max_memory_mb": 900,
            "poll_interval": 10,
            "job_timeout": 1800,
            "nice_priority": 15,
        },
        "redis": {
            "lock_key": "highlight:lock",
            "lock_ttl": 1800,
        },
        "extraction": {
            "stream_copy": False,
            "thumbnail_width": 640,
            "thumbnail_height": 360,
        },
    }
