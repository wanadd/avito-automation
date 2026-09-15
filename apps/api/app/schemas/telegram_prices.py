import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class TelegramPriceSourceRead(ORMModel):
    id: uuid.UUID
    telegram_channel_id: int
    chat_type: str | None
    title: str | None
    username: str | None
    source_id: uuid.UUID | None
    first_seen_at: datetime
    last_seen_at: datetime | None
    last_received_at: datetime | None


class TelegramPriceBatchRead(ORMModel):
    id: uuid.UUID
    telegram_price_source_id: uuid.UUID | None
    source_id: uuid.UUID | None
    raw_source_record_id: uuid.UUID | None
    raw_source_record_revision_id: uuid.UUID | None
    supplier_snapshot_id: uuid.UUID | None
    submitted_by_user_id: int
    destination_chat_id: int | None
    status: str
    duplicate: bool
    message_count: int
    parsed_rows: int
    accepted_rows: int
    review_rows: int
    failed_rows: int
    first_message_at: datetime | None
    last_message_at: datetime | None
    received_at: datetime
    processed_at: datetime | None
    error: str | None
    response_text: str | None


class TelegramPriceMessageRead(ORMModel):
    id: uuid.UUID
    batch_id: uuid.UUID | None
    telegram_price_source_id: uuid.UUID | None
    update_id: int
    message_id: int | None
    sender_user_id: int | None
    destination_chat_id: int | None
    message_date: datetime | None
    status: str
    raw_text: str | None
    caption: str | None
    forward_origin: dict | None
    error: str | None
    received_at: datetime


class TelegramPriceSourceMapRequest(BaseModel):
    supplier_id: uuid.UUID


class TelegramPriceStatusRead(BaseModel):
    enabled: bool
    last_update_id: int | None
    last_success_poll_at: datetime | None
    last_api_error: str | None
    last_successful_price_ingestion_at: datetime | None
    pending_ingestion_count: int
    failed_ingestion_count: int
    unknown_source_count: int
