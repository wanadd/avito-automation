from dataclasses import dataclass, field
from decimal import Decimal

from app.models.enums import ParseStatus, ProductCondition


@dataclass(slots=True)
class SectionContext:
    raw: str | None = None
    normalized: str | None = None


@dataclass(slots=True)
class ParsedLine:
    line_number: int
    raw_line: str
    section_raw: str | None = None
    section_normalized: str | None = None
    brand_raw: str | None = None
    brand_normalized: str | None = None
    model_raw: str | None = None
    model_normalized: str | None = None
    manufacturer_model_code: str | None = None
    ram_gb: int | None = None
    storage_gb: int | None = None
    color_raw: str | None = None
    color_normalized: str | None = None
    region_raw: str | None = None
    region_code: str | None = None
    condition: ProductCondition | None = None
    price_minor: int | None = None
    currency: str = "RUB"
    parse_confidence: Decimal = Decimal("0.0000")
    parse_status: ParseStatus = ParseStatus.REVIEW
    parse_flags: list[str] = field(default_factory=list)
    parsed_payload: dict = field(default_factory=dict)
    parsed_identity_key: str | None = None


@dataclass(slots=True)
class ParseResult:
    total_lines: int
    items: list[ParsedLine]

