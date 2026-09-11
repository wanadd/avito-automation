from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conflict import DataConflict
from app.models.enums import ConflictStatus, ParseStatus
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.raw_source_record import RawSourceRecord
from app.models.source import Source
from app.services.parser.colors import extract_color, remove_color
from app.services.parser.conditions import extract_condition
from app.services.parser.confidence import score_confidence, status_from_confidence
from app.services.parser.identity import build_parsed_identity_key
from app.services.parser.line_detector import classify_line
from app.services.parser.memory import parse_memory, remove_memory
from app.services.parser.model_codes import extract_model_code, remove_model_code
from app.services.parser.models import normalize_brand, normalize_model
from app.services.parser.prices import parse_price, remove_price
from app.services.parser.regions import extract_region
from app.services.parser.sections import detect_section
from app.services.parser.text import normalize_lookup, normalize_spaces, tokenize_lines
from app.services.parser.types import ParseResult, ParsedLine, SectionContext


def parse_price_text(raw_text: str) -> ParseResult:
    context = SectionContext()
    parsed_items: list[ParsedLine] = []
    seen_lines: dict[str, int] = {}

    for line_number, raw_line in tokenize_lines(raw_text):
        section = detect_section(raw_line)
        if section is not None:
            context = section
            parsed_items.append(
                ParsedLine(
                    line_number=line_number,
                    raw_line=raw_line,
                    section_raw=section.raw,
                    section_normalized=section.normalized,
                    parse_status=ParseStatus.IGNORED,
                    parse_confidence=Decimal("0.0000"),
                    parsed_payload={"line_type": "section"},
                )
            )
            continue

        item = parse_line(line_number, raw_line, context)
        line_key = normalize_lookup(raw_line)
        if line_key and line_key in seen_lines and item.parse_status != ParseStatus.IGNORED:
            item.parse_flags.append("DUPLICATE_LINE")
            item.parsed_payload["duplicate_of_line"] = seen_lines[line_key]
        elif line_key:
            seen_lines[line_key] = line_number
        parsed_items.append(item)

    detect_price_conflicts(parsed_items)
    for item in parsed_items:
        if item.parse_status != ParseStatus.IGNORED:
            item.parse_confidence = score_confidence(item)
            item.parse_status = status_from_confidence(item)

    return ParseResult(total_lines=len(tokenize_lines(raw_text)), items=parsed_items)


def parse_line(line_number: int, raw_line: str, context: SectionContext) -> ParsedLine:
    item = ParsedLine(
        line_number=line_number,
        raw_line=raw_line,
        section_raw=context.raw,
        section_normalized=context.normalized,
    )
    classification = classify_line(raw_line, context.normalized)
    if classification == "ignored":
        item.parse_status = ParseStatus.IGNORED
        item.parsed_payload = {"line_type": "ignored"}
        return item

    if context.normalized is None:
        item.parse_flags.append("UNKNOWN_SECTION")

    region_raw, region_code, unknown_region = extract_region(raw_line)
    item.region_raw = region_raw
    item.region_code = region_code
    if unknown_region:
        item.parse_flags.append("UNKNOWN_REGION")

    price_raw, price_minor, invalid_price = parse_price(raw_line)
    item.price_minor = price_minor
    if invalid_price:
        item.parse_flags.append("INVALID_PRICE")
    elif price_minor is None:
        item.parse_flags.append("MISSING_PRICE")

    ram_gb, storage_gb, memory_raw, ambiguous_memory = parse_memory(raw_line)
    item.ram_gb = ram_gb
    item.storage_gb = storage_gb
    if ambiguous_memory:
        item.parse_flags.append("AMBIGUOUS_MEMORY")

    code, possible_code = extract_model_code(raw_line)
    item.manufacturer_model_code = code
    if possible_code and code is None:
        item.parse_flags.append("POSSIBLE_MODEL_CODE")

    color_raw, color_normalized = extract_color(raw_line)
    item.color_raw = color_raw
    item.color_normalized = color_normalized
    if color_raw is not None and color_normalized is None:
        item.parse_flags.append("UNKNOWN_COLOR")

    item.condition = extract_condition(raw_line)

    model_source = remove_noise_for_model(raw_line, price_raw, memory_raw, code, color_raw)
    item.model_raw, item.model_normalized, ambiguous_model = normalize_model(context.normalized, model_source)
    if item.model_normalized is None:
        item.parse_flags.append("MISSING_MODEL")
    if ambiguous_model:
        item.parse_flags.append("AMBIGUOUS_MODEL")

    item.brand_raw, item.brand_normalized = normalize_brand(context.normalized, item.model_normalized)
    item.parsed_identity_key = build_parsed_identity_key(
        brand_normalized=item.brand_normalized,
        model_normalized=item.model_normalized,
        manufacturer_model_code=item.manufacturer_model_code,
        ram_gb=item.ram_gb,
        storage_gb=item.storage_gb,
        color_normalized=item.color_normalized,
        region_code=item.region_code,
    )
    item.parsed_payload = {
        "line_type": classification,
        "price_raw": price_raw,
        "memory_raw": memory_raw,
        "identity_key": item.parsed_identity_key,
    }
    item.parse_confidence = score_confidence(item)
    item.parse_status = status_from_confidence(item)
    return item


def remove_noise_for_model(line: str, price_raw: str | None, memory_raw: str | None, code: str | None, color_raw: str | None) -> str:
    value = remove_price(line)
    value = remove_memory(value)
    value = remove_model_code(value, code)
    value = remove_color(value, color_raw)
    if price_raw:
        value = value.replace(price_raw, " ")
    if memory_raw:
        value = value.replace(memory_raw, " ")
    value = "".join(" " if ord(char) > 127 and not char.isalnum() else char for char in value)
    return normalize_spaces(value)


def detect_price_conflicts(items: list[ParsedLine]) -> None:
    grouped: dict[str, list[ParsedLine]] = defaultdict(list)
    for item in items:
        if item.parsed_identity_key and item.price_minor is not None and item.parse_status != ParseStatus.IGNORED:
            grouped[item.parsed_identity_key].append(item)

    for group in grouped.values():
        prices = {item.price_minor for item in group}
        if len(prices) <= 1:
            continue
        evidence = [
            {"line_number": item.line_number, "raw_line": item.raw_line, "price_minor": item.price_minor}
            for item in group
        ]
        for item in group:
            if "PRICE_CONFLICT" not in item.parse_flags:
                item.parse_flags.append("PRICE_CONFLICT")
            item.parsed_payload["price_conflict_evidence"] = evidence
            item.parse_status = ParseStatus.CONFLICT


async def parse_raw_record(session: AsyncSession, raw_record_id) -> tuple[ParseResult, list[ParsedSupplierItem]]:
    raw_record = await session.get(RawSourceRecord, raw_record_id)
    if raw_record is None:
        raise ValueError("RawSourceRecord not found")
    source = await session.get(Source, raw_record.source_id)
    if source is None:
        raise ValueError("Source not found")

    result = parse_price_text(raw_record.raw_text)

    await session.execute(delete(ParsedSupplierItem).where(ParsedSupplierItem.raw_source_record_id == raw_record.id))
    await session.execute(delete(DataConflict).where(DataConflict.raw_source_record_id == raw_record.id))

    db_items = [
        ParsedSupplierItem(
            raw_source_record_id=raw_record.id,
            source_id=raw_record.source_id,
            supplier_id=source.supplier_id,
            line_number=item.line_number,
            raw_line=item.raw_line,
            section_raw=item.section_raw,
            section_normalized=item.section_normalized,
            brand_raw=item.brand_raw,
            brand_normalized=item.brand_normalized,
            model_raw=item.model_raw,
            model_normalized=item.model_normalized,
            manufacturer_model_code=item.manufacturer_model_code,
            ram_gb=item.ram_gb,
            storage_gb=item.storage_gb,
            color_raw=item.color_raw,
            color_normalized=item.color_normalized,
            region_raw=item.region_raw,
            region_code=item.region_code,
            condition=item.condition,
            price_minor=item.price_minor,
            currency=item.currency,
            parse_confidence=item.parse_confidence,
            parse_status=item.parse_status,
            parse_flags=item.parse_flags,
            parsed_payload=item.parsed_payload,
            parsed_identity_key=item.parsed_identity_key,
        )
        for item in result.items
    ]
    session.add_all(db_items)
    await session.flush()
    await create_data_conflicts(session, raw_record, source, result.items)
    await session.commit()
    for db_item in db_items:
        await session.refresh(db_item)
    return result, db_items


async def create_data_conflicts(
    session: AsyncSession, raw_record: RawSourceRecord, source: Source, items: list[ParsedLine]
) -> None:
    grouped: dict[str, list[ParsedLine]] = defaultdict(list)
    for item in items:
        if "PRICE_CONFLICT" in item.parse_flags and item.parsed_identity_key:
            grouped[item.parsed_identity_key].append(item)

    for identity_key, group in grouped.items():
        prices = sorted({item.price_minor for item in group if item.price_minor is not None})
        if len(prices) <= 1:
            continue
        session.add(
            DataConflict(
                conflict_type="PARSED_SUPPLIER_PRICE_MISMATCH",
                source_id=raw_record.source_id,
                product_variant_id=None,
                raw_source_record_id=raw_record.id,
                details={
                    "supplier_id": str(source.supplier_id),
                    "parsed_identity_key": identity_key,
                    "prices_minor": prices,
                    "evidence": [
                        {
                            "line_number": item.line_number,
                            "raw_line": item.raw_line,
                            "price_minor": item.price_minor,
                        }
                        for item in group
                    ],
                },
                status=ConflictStatus.OPEN,
            )
        )


def summarize(raw_record_id, total_lines: int, items: list[ParsedSupplierItem]) -> dict:
    counts = {
        "parsed_count": 0,
        "partial_count": 0,
        "review_count": 0,
        "conflict_count": 0,
        "ignored_count": 0,
    }
    for item in items:
        key = f"{item.parse_status.value.lower()}_count"
        counts[key] += 1
    return {"raw_record_id": raw_record_id, "total_lines": total_lines, **counts, "items": items}
