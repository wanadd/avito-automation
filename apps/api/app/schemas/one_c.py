import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import OneCImportMode, OneCImportRunStatus, OneCItemMatchStatus, OneCItemMatchStrategy
from app.schemas.common import ORMModel
from app.schemas.product import ProductVariantRead


class OneCImportRunRead(ORMModel):
    id: uuid.UUID
    filename: str | None
    file_hash: str
    exported_at: datetime
    imported_at: datetime
    status: OneCImportRunStatus
    mode: OneCImportMode
    dry_run: bool
    total_rows: int
    valid_rows: int
    invalid_rows: int
    matched_rows: int
    unmatched_rows: int
    ambiguous_rows: int
    duplicate_rows: int
    would_update_stock: int
    would_update_cost: int
    would_zero_missing: int
    warnings: list
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None


class OneCItemRead(ORMModel):
    id: uuid.UUID
    internal_code: str
    sku: str | None
    barcode: str | None
    raw_name: str
    normalized_name: str
    matched_variant_id: uuid.UUID | None
    match_status: OneCItemMatchStatus
    match_strategy: OneCItemMatchStrategy | None
    match_confidence: float | None
    explicit_mapping: bool
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class OneCMapRequest(BaseModel):
    variant_id: uuid.UUID


class InventoryStateRead(ORMModel):
    variant_id: uuid.UUID
    own_stock_total: int
    own_cost_minor: int | None
    currency: str
    source_item_id: uuid.UUID
    source_updated_at: datetime
    last_import_run_id: uuid.UUID
    updated_at: datetime


class InventoryListItem(BaseModel):
    state: InventoryStateRead
    variant: ProductVariantRead


class VariantInventoryRead(BaseModel):
    state: InventoryStateRead | None
    recent_stock: list[dict]
    recent_cost: list[dict]
