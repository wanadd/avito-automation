import csv
import io
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.integrations.one_c.normalizer import normalize_name, normalize_optional
from app.integrations.one_c.types import OneCInvalidRow, OneCParsedFile, OneCParsedRow

JSON_ROOT_KEYS = {"exported_at", "source", "items"}
ITEM_KEYS = {
    "internal_code",
    "sku",
    "barcode",
    "name",
    "stock_total",
    "stock_by_store",
    "cost",
    "currency",
    "updated_at",
}
CSV_KEYS = ITEM_KEYS - {"stock_by_store"}
SUPPORTED_CURRENCIES = {"RUB"}


def parse_file_bytes(content: bytes, *, filename: str | None = None) -> OneCParsedFile:
    text = decode_text(content)
    stripped = text.lstrip("\ufeff \r\n\t")
    if (filename or "").lower().endswith(".json") or stripped.startswith("{"):
        return parse_json_text(stripped)
    return parse_csv_text(text)


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unsupported file encoding")


def parse_json_text(text: str) -> OneCParsedFile:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object")
    unknown = set(payload) - JSON_ROOT_KEYS
    if unknown:
        raise ValueError(f"Unexpected JSON root keys: {sorted(unknown)}")
    if payload.get("source") not in {None, "1c"}:
        raise ValueError("Unsupported source")
    exported_at = parse_datetime(payload.get("exported_at"), "exported_at")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("items must be an array")
    return parse_records(items, exported_at=exported_at)


def parse_csv_text(text: str) -> OneCParsedFile:
    sample = text[:4096]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;")
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("CSV header is missing")
    fieldnames = {field.strip("\ufeff") for field in reader.fieldnames}
    unknown = fieldnames - CSV_KEYS
    if unknown:
        raise ValueError(f"Unexpected CSV columns: {sorted(unknown)}")
    rows = [{(key.strip("\ufeff") if key else key): value for key, value in row.items()} for row in reader]
    exported_at = datetime.now(UTC)
    return parse_records(rows, exported_at=exported_at)


def parse_records(records: list[dict[str, Any]], *, exported_at: datetime) -> OneCParsedFile:
    by_code: dict[str, OneCParsedRow] = {}
    invalid: list[OneCInvalidRow] = []
    duplicate_rows = 0
    warnings: list[str] = []
    for index, record in enumerate(records, start=1):
        unknown = set(record) - ITEM_KEYS
        if unknown:
            invalid.append(OneCInvalidRow(index, f"unexpected keys: {sorted(unknown)}"))
            continue
        try:
            row = parse_row(record, row_number=index, exported_at=exported_at)
        except ValueError as exc:
            invalid.append(OneCInvalidRow(index, str(exc)))
            continue
        previous = by_code.get(row.internal_code)
        if previous is None:
            by_code[row.internal_code] = row
            continue
        duplicate_rows += 1
        if previous != row:
            invalid.append(OneCInvalidRow(index, "duplicate internal_code conflict"))
            warnings.append(f"duplicate internal_code conflict: {row.internal_code}")
    return OneCParsedFile(exported_at, list(by_code.values()), invalid, duplicate_rows, warnings)


def parse_row(record: dict[str, Any], *, row_number: int, exported_at: datetime) -> OneCParsedRow:
    internal_code = normalize_optional(record.get("internal_code"))
    if not internal_code:
        raise ValueError("missing internal_code")
    raw_name = normalize_optional(record.get("name"))
    if not raw_name:
        raise ValueError("missing name")
    currency = (normalize_optional(record.get("currency")) or get_settings().one_c_default_currency).upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError("unsupported currency")
    stock_total = parse_stock(record.get("stock_total"))
    stock_by_store = parse_stock_by_store(record.get("stock_by_store"))
    warnings: list[str] = []
    if stock_by_store is not None and sum(stock_by_store.values()) != stock_total:
        warnings.append("stock_by_store_total_mismatch")
    updated_at = parse_datetime(record.get("updated_at"), "updated_at") if record.get("updated_at") else exported_at
    return OneCParsedRow(
        internal_code=internal_code,
        sku=normalize_optional(record.get("sku")),
        barcode=normalize_optional(record.get("barcode")),
        raw_name=raw_name,
        normalized_name=normalize_name(raw_name),
        stock_total=stock_total,
        stock_by_store=stock_by_store,
        cost_minor=parse_cost_minor(record.get("cost")),
        currency=currency,
        source_updated_at=updated_at,
        warnings=warnings,
    )


def parse_datetime(value: Any, field_name: str) -> datetime:
    if not value:
        raise ValueError(f"missing {field_name}")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_stock(value: Any) -> int:
    if value is None or str(value).strip() == "":
        raise ValueError("missing stock_total")
    try:
        decimal = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("invalid stock_total") from exc
    if decimal < 0 or decimal != decimal.to_integral_value():
        raise ValueError("invalid stock_total")
    return int(decimal)


def parse_stock_by_store(value: Any) -> dict[str, int] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError("invalid stock_by_store")
    return {str(key): parse_stock(store_value) for key, store_value in value.items()}


def parse_cost_minor(value: Any) -> int:
    if value is None or str(value).strip() == "":
        raise ValueError("missing cost")
    raw = str(value).strip().replace(" ", "")
    if "," in raw and "." in raw:
        raise ValueError("invalid cost")
    raw = raw.replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("invalid cost") from exc
    if amount < 0:
        raise ValueError("negative cost")
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def read_file(path: str) -> tuple[bytes, str]:
    file_path = Path(path)
    return file_path.read_bytes(), file_path.name
