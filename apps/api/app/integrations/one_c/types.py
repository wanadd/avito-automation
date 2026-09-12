from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class OneCParsedRow:
    internal_code: str
    sku: str | None
    barcode: str | None
    raw_name: str
    normalized_name: str
    stock_total: int
    cost_minor: int
    currency: str
    source_updated_at: datetime
    stock_by_store: dict[str, int] | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OneCInvalidRow:
    row_number: int
    reason: str


@dataclass(frozen=True)
class OneCParsedFile:
    exported_at: datetime
    rows: list[OneCParsedRow]
    invalid_rows: list[OneCInvalidRow]
    duplicate_rows: int
    warnings: list[str]
