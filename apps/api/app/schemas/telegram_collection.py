import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import TelegramCollectionMode, TelegramCollectionRunStatus
from app.schemas.common import ORMModel


class TelegramCollectRequest(BaseModel):
    mode: TelegramCollectionMode = TelegramCollectionMode.INCREMENTAL
    limit: int | None = Field(default=None, ge=1, le=500)


class TelegramCollectionResult(BaseModel):
    run_id: uuid.UUID
    source_id: uuid.UUID
    status: TelegramCollectionRunStatus
    mode: TelegramCollectionMode
    fetched: int
    new_records: int
    duplicate_records: int
    edited_records: int
    ignored_records: int
    snapshots_created: int
    snapshots_processed: int
    failed_records: int
    last_message_id: int | None
    error: str | None = None


class TelegramCollectionRunRead(ORMModel):
    id: uuid.UUID
    source_id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None
    status: TelegramCollectionRunStatus
    mode: TelegramCollectionMode
    fetched_count: int
    new_count: int
    duplicate_count: int
    edited_count: int
    ignored_count: int
    snapshots_created: int
    snapshots_processed: int
    failed_count: int
    start_message_id: int | None
    end_message_id: int | None
    error: str | None


class TelegramSourceTestResult(BaseModel):
    reachable: bool
    external_chat_id: int | None = None
    title: str | None = None
    username: str | None = None
    latest_message_id: int | None = None
    error: str | None = None
