import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import SourceType, SupplierSnapshotType, TelegramCollectionRunStatus
from app.schemas.common import Timestamped


class SourceCreate(BaseModel):
    supplier_id: uuid.UUID
    source_type: SourceType
    external_key: str | None = None
    name: str
    is_active: bool = True
    external_chat_id: int | None = None
    username: str | None = None
    title: str | None = None
    telegram_enabled: bool = False
    snapshot_type: SupplierSnapshotType = SupplierSnapshotType.FULL


class SourceRead(Timestamped):
    id: uuid.UUID
    supplier_id: uuid.UUID
    source_type: SourceType
    external_key: str | None
    name: str
    is_active: bool
    external_chat_id: int | None
    username: str | None
    title: str | None
    telegram_enabled: bool
    snapshot_type: SupplierSnapshotType
    last_collected_message_id: int | None
    last_collection_at: datetime | None
    last_collection_status: TelegramCollectionRunStatus | None
    last_collection_error: str | None
