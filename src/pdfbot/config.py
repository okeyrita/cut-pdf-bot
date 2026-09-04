"""Runtime configuration.

Single source of truth for env vars, shared by the bot process and the Celery workers. Importing
this module never touches the network; :func:`get_settings` is cached so the same object is reused.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


#: Telegram's own limit against the cloud Bot API. A local server raises it to 2 GB.
CLOUD_API_DOWNLOAD_LIMIT_MB = 20


class Settings(BaseSettings):
    """Environment-driven settings. See ``.env.example`` for the full list."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # ---------------------------------------------------------------- telegram
    bot_token: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Token from @BotFather. Optional here on purpose: Celery workers share this Settings "
            "class but never talk to Telegram, so they must be able to boot without it. "
            "create_bot() rejects an empty token."
        ),
    )

    use_local_bot_api: bool = Field(
        default=False,
        description="Talk to a self-hosted telegram-bot-api server instead of api.telegram.org.",
    )
    local_bot_api_url: str = Field(default="http://telegram-bot-api:8081")
    local_bot_api_data_dir: Path = Field(
        default=Path("/var/lib/telegram-bot-api"),
        description=(
            "Where the local API server writes downloaded files. In local mode getFile returns "
            "a path under this directory, so the bot must have it mounted."
        ),
    )

    # ---------------------------------------------------------------- infra
    redis_url: str = Field(default="redis://redis:6379/0")
    celery_broker_url: str = Field(default="amqp://guest:guest@rabbitmq:5672//")
    celery_result_backend: str = Field(default="redis://redis:6379/1")

    data_dir: Path = Field(
        default=Path("/data"),
        description="Shared volume where job workspaces live. Must be writable by bot and worker.",
    )

    # ---------------------------------------------------------------- limits
    max_file_size_mb: int = Field(default=2000, gt=0)
    max_pages: int = Field(default=3000, gt=0)
    max_merge_files: int = Field(default=20, ge=2)
    max_concurrent_jobs_per_user: int = Field(default=1, ge=1)
    task_soft_time_limit: int = Field(default=1500, gt=0, description="Seconds.")
    task_time_limit: int = Field(default=1800, gt=0, description="Seconds; hard kill.")

    # ---------------------------------------------------------------- progress
    progress_min_interval: float = Field(
        default=2.0,
        gt=0,
        description="Seconds between progress edits. Telegram allows ~1 edit/sec per chat.",
    )
    progress_min_ratio: float = Field(
        default=0.05, gt=0, le=1, description="Also emit after this fraction of pages."
    )
    ocr_chunk_pages: int = Field(
        default=10,
        gt=0,
        description="ocrmypdf has no per-page callback, so OCR runs in chunks of this size.",
    )

    # ---------------------------------------------------------------- misc
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = Field(default=True, description="Structured logs; set false for local dev.")
    events_stream: str = Field(default="pdfbot:events")
    events_group: str = Field(default="pdfbot-bot")
    workspace_ttl_seconds: int = Field(
        default=6 * 3600, gt=0, description="Sweep abandoned job directories older than this."
    )

    @field_validator("data_dir", "local_bot_api_data_dir")
    @classmethod
    def _must_be_absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError(f"must be an absolute path, got {value!r}")
        return value

    @model_validator(mode="after")
    def _check_limits(self) -> Settings:
        if self.task_time_limit <= self.task_soft_time_limit:
            raise ValueError("task_time_limit must exceed task_soft_time_limit")
        if not self.use_local_bot_api and self.max_file_size_mb > CLOUD_API_DOWNLOAD_LIMIT_MB:
            # Not fatal: clamp rather than refuse to boot, so the default 2000 works either way.
            object.__setattr__(self, "max_file_size_mb", CLOUD_API_DOWNLOAD_LIMIT_MB)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @computed_field  # type: ignore[prop-decorator]
    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance. Call ``get_settings.cache_clear()`` in tests."""
    # Every field either has a default or is supplied by the environment.
    return Settings()
