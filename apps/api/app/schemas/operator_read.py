import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class Page(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class DashboardRead(BaseModel):
    counts: dict[str, int]
    recent_failures: list[dict[str, Any]]
    recent_review_items: list[dict[str, Any]]
    recent_publication_jobs: list[dict[str, Any]]
    source_freshness: list[dict[str, Any]]


class SystemHealthRead(BaseModel):
    api: str
    database: str
    redis: str
    worker: str
    scheduler: str
    avito_real_mutation: str
    timestamp: datetime


class SettingsRead(BaseModel):
    app_env: str
    auto_prepare_publication: bool
    publication_max_attempts: int
    publication_retry_base_seconds: int
    telegram_control_configured: bool
    avito_live_enabled: bool
    backup_configured: bool
    cookie_secure: bool
    session_ttl_seconds: int


class BackupSmokeRead(BaseModel):
    status: str
    backup_id: str
    path: str
    size_bytes: int


class BulkIdsRequest(BaseModel):
    ids: list[uuid.UUID]


class AlertActionRequest(BaseModel):
    note: str | None = None
