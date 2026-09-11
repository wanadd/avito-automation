import uuid

from pydantic import BaseModel

from app.schemas.common import Timestamped


class SupplierCreate(BaseModel):
    code: str
    name: str
    is_active: bool = True


class SupplierRead(Timestamped):
    id: uuid.UUID
    code: str
    name: str
    is_active: bool

