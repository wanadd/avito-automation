import uuid

from pydantic import BaseModel

from app.models.enums import SourceType
from app.schemas.common import Timestamped


class SourceCreate(BaseModel):
    supplier_id: uuid.UUID
    source_type: SourceType
    external_key: str | None = None
    name: str
    is_active: bool = True


class SourceRead(Timestamped):
    id: uuid.UUID
    supplier_id: uuid.UUID
    source_type: SourceType
    external_key: str | None
    name: str
    is_active: bool

