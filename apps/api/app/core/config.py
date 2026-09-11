from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://avito:change_me_local_only@localhost:5432/avito_automation"
    redis_url: str = "redis://localhost:6379/0"
    app_env: str = "local"
    log_level: str = "INFO"
    supplier_missing_snapshots_to_out_of_stock: int = 2
    snapshot_min_valid_item_ratio: float = 0.50

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
