import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import MatchStatus, SupplierSnapshotItemStatus, SupplierSnapshotStatus, SupplierSnapshotType
from app.schemas.common import ORMModel


class SupplierSnapshotCreate(BaseModel):
    supplier_id: uuid.UUID
    source_id: uuid.UUID
    raw_source_record_id: uuid.UUID
    raw_source_record_revision_id: uuid.UUID | None = None
    external_snapshot_id: str | None = None
    snapshot_type: SupplierSnapshotType
    captured_at: datetime | None = None


class SupplierSnapshotRead(ORMModel):
    id: uuid.UUID
    supplier_id: uuid.UUID
    source_id: uuid.UUID
    raw_source_record_id: uuid.UUID
    raw_source_record_revision_id: uuid.UUID | None
    external_snapshot_id: str | None
    snapshot_type: SupplierSnapshotType
    captured_at: datetime
    processed_at: datetime | None
    status: SupplierSnapshotStatus
    total_lines: int
    parsed_items: int
    matched_items: int
    offers_seen: int
    conflicts_count: int
    review_count: int
    parser_error_count: int
    quality_gate_reason: str | None
    created_at: datetime


class SupplierSnapshotItemRead(ORMModel):
    id: uuid.UUID
    snapshot_id: uuid.UUID
    parsed_supplier_item_id: uuid.UUID
    supplier_offer_id: uuid.UUID | None
    product_variant_id: uuid.UUID | None
    match_status: MatchStatus
    item_status: SupplierSnapshotItemStatus
    created_at: datetime


class ProcessSnapshotSummary(BaseModel):
    snapshot_id: uuid.UUID
    status: SupplierSnapshotStatus
    total_lines: int
    parsed: int
    parsed_items: int
    candidate_lines: int
    parser_successful_items: int
    parser_review_items: int
    parser_conflict_items: int
    exact_match: int
    auto_created: int
    review: int
    review_count: int
    conflict: int
    conflicts_count: int
    rejected: int
    parser_error_count: int
    offers_created: int
    offers_updated: int
    offers_seen: int
    moved_to_in_stock: int
    moved_to_suspect_missing: int
    moved_to_out_of_stock: int
    restored: int
    quality_gate_passed: bool
