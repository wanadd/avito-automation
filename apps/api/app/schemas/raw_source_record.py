import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import ProcessingStatus
from app.schemas.common import ORMModel


class RawSourceRecordCreate(BaseModel):
    source_id: uuid.UUID
    external_record_id: str | None = None
    raw_text: str
    raw_payload: dict | None = None
    source_published_at: datetime | None = None
    processing_status: ProcessingStatus = ProcessingStatus.NEW


class RawSourceRecordRead(ORMModel):
    id: uuid.UUID
    source_id: uuid.UUID
    external_record_id: str | None
    raw_text: str
    raw_payload: dict | None
    source_published_at: datetime | None
    ingested_at: datetime
    content_hash: str
    processing_status: ProcessingStatus

