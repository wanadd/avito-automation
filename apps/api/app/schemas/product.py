import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import ProductCondition
from app.schemas.common import Timestamped


class ProductCreate(BaseModel):
    brand: str
    canonical_name: str
    model_family: str | None = None
    category: str | None = None
    is_active: bool = True


class ProductRead(Timestamped):
    id: uuid.UUID
    brand: str
    canonical_name: str
    model_family: str | None
    category: str | None
    is_active: bool


class ProductVariantCreate(BaseModel):
    manufacturer_model_code: str | None = None
    ram_gb: int | None = None
    storage_gb: int | None = None
    color_raw: str | None = None
    color_normalized: str | None = None
    region_code: str | None = None
    condition: ProductCondition | None = None
    is_active: bool = True


class ProductVariantRead(Timestamped):
    id: uuid.UUID
    product_id: uuid.UUID
    manufacturer_model_code: str | None
    ram_gb: int | None
    storage_gb: int | None
    color_raw: str | None
    color_normalized: str | None
    region_code: str | None
    condition: ProductCondition | None
    canonical_key: str
    is_active: bool


class ProductAliasCreate(BaseModel):
    product_id: uuid.UUID | None = None
    product_variant_id: uuid.UUID | None = None
    alias: str
    normalized_alias: str
    source_id: uuid.UUID | None = None


class ProductAliasRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    product_variant_id: uuid.UUID | None
    alias: str
    normalized_alias: str
    source_id: uuid.UUID | None
    created_at: datetime
