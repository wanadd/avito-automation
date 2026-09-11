import uuid
from datetime import datetime

from app.models.enums import ConflictStatus
from app.schemas.common import ORMModel


class DataConflictRead(ORMModel):
    id: uuid.UUID
    conflict_type: str
    source_id: uuid.UUID | None
    product_variant_id: uuid.UUID | None
    raw_source_record_id: uuid.UUID | None
    details: dict
    status: ConflictStatus
    created_at: datetime
    resolved_at: datetime | None

