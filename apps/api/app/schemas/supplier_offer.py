import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import Availability
from app.schemas.common import ORMModel, Timestamped


class SupplierOfferCreate(BaseModel):
    supplier_id: uuid.UUID
    product_variant_id: uuid.UUID
    source_id: uuid.UUID | None = None
    supplier_sku: str | None = None
    supplier_title: str
    price_minor: int = Field(ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    availability: Availability = Availability.UNKNOWN
    source_record_id: uuid.UUID | None = None
    source_updated_at: datetime | None = None


class SupplierOfferRead(Timestamped):
    id: uuid.UUID
    supplier_id: uuid.UUID
    product_variant_id: uuid.UUID
    source_id: uuid.UUID | None
    supplier_sku: str | None
    supplier_title: str
    price_minor: int
    currency: str
    availability: Availability
    source_record_id: uuid.UUID | None
    source_updated_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime


class SupplierOfferSnapshotRead(ORMModel):
    id: uuid.UUID
    supplier_offer_id: uuid.UUID
    price_minor: int
    availability: Availability
    source_record_id: uuid.UUID | None
    captured_at: datetime

