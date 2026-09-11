from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://avito:change_me_local_only@localhost:5432/avito_automation"
    redis_url: str = "redis://localhost:6379/0"
    app_env: str = "local"
    log_level: str = "INFO"
    supplier_missing_snapshots_to_out_of_stock: int = 2
    snapshot_min_valid_item_ratio: float = 0.50
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session_path: str = "/data/telegram/session"
    telegram_collector_enabled: bool = False
    telegram_collector_poll_seconds: int = 300
    telegram_backfill_limit: int = 50
    telegram_flood_wait_fail_seconds: int = 30
    telegram_default_collection_interval_seconds: int = 600
    collection_scheduler_jitter_seconds: int = 30
    collection_job_max_attempts: int = 3
    job_stale_running_seconds: int = 900
    scheduler_tick_seconds: int = 10
    source_error_failure_threshold: int = 3
    source_stale_multiplier: int = 3
    redis_lock_ttl_seconds: int = 300

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("telegram_api_id", "telegram_api_hash", mode="before")
    @classmethod
    def empty_string_is_none(cls, value):
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
