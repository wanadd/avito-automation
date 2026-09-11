import uuid
from datetime import datetime
from decimal import Decimal

from app.models.enums import ParseStatus, ProductCondition
from app.schemas.common import ORMModel


class ParsedSupplierItemRead(ORMModel):
    id: uuid.UUID
    raw_source_record_id: uuid.UUID
    source_id: uuid.UUID
    supplier_id: uuid.UUID
    line_number: int
    raw_line: str
    section_raw: str | None
    section_normalized: str | None
    brand_raw: str | None
    brand_normalized: str | None
    model_raw: str | None
    model_normalized: str | None
    manufacturer_model_code: str | None
    ram_gb: int | None
    storage_gb: int | None
    color_raw: str | None
    color_normalized: str | None
    region_raw: str | None
    region_code: str | None
    condition: ProductCondition | None
    price_minor: int | None
    currency: str
    parse_confidence: Decimal
    parse_status: ParseStatus
    parse_flags: list[str]
    parsed_payload: dict
    parsed_identity_key: str | None
    created_at: datetime


class ParseSummary(ORMModel):
    raw_record_id: uuid.UUID
    total_lines: int
    parsed_count: int
    partial_count: int
    review_count: int
    conflict_count: int
    ignored_count: int
    items: list[ParsedSupplierItemRead]
