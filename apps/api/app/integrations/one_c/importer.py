import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.one_c.matcher import match_one_c_row
from app.integrations.one_c.parser import parse_file_bytes, read_file
from app.integrations.one_c.types import OneCParsedFile, OneCParsedRow
from app.models.audit_log import AuditLog
from app.models.conflict import DataConflict
from app.models.enums import ConflictStatus, OneCImportMode, OneCImportRunStatus, OneCItemMatchStatus, OneCItemMatchStrategy
from app.models.one_c import (
    OneCImportRun,
    OneCItem,
    VariantCostSnapshot,
    VariantInventoryState,
    VariantStockSnapshot,
)
from app.models.product import Product, ProductVariant


async def import_one_c_file(
    session: AsyncSession,
    content: bytes,
    *,
    filename: str | None,
    mode: OneCImportMode,
    dry_run: bool = False,
) -> OneCImportRun:
    file_hash = hashlib.sha256(content).hexdigest()
    existing = await session.scalar(
        select(OneCImportRun).where(
            OneCImportRun.file_hash == file_hash,
            OneCImportRun.dry_run == dry_run,
            OneCImportRun.status != OneCImportRunStatus.FAILED,
        )
    )
    if existing:
        duplicate = OneCImportRun(
            filename=filename,
            file_hash=file_hash,
            exported_at=existing.exported_at,
            status=OneCImportRunStatus.DUPLICATE,
            mode=mode,
            dry_run=dry_run,
            total_rows=existing.total_rows,
            valid_rows=existing.valid_rows,
            invalid_rows=existing.invalid_rows,
            matched_rows=existing.matched_rows,
            unmatched_rows=existing.unmatched_rows,
            ambiguous_rows=existing.ambiguous_rows,
            duplicate_rows=existing.duplicate_rows,
            would_update_stock=existing.would_update_stock,
            would_update_cost=existing.would_update_cost,
            would_zero_missing=existing.would_zero_missing,
            warnings=existing.warnings,
            finished_at=now(),
        )
        session.add(duplicate)
        await session.commit()
        await session.refresh(duplicate)
        return duplicate

    parsed = parse_file_bytes(content, filename=filename)
    run = OneCImportRun(
        filename=filename,
        file_hash=file_hash,
        exported_at=parsed.exported_at,
        status=OneCImportRunStatus.PROCESSING,
        mode=mode,
        dry_run=dry_run,
        total_rows=len(parsed.rows) + len(parsed.invalid_rows) + parsed.duplicate_rows,
        valid_rows=len(parsed.rows),
        invalid_rows=len(parsed.invalid_rows),
        duplicate_rows=parsed.duplicate_rows,
        warnings=parsed.warnings + [f"row {row.row_number}: {row.reason}" for row in parsed.invalid_rows],
    )
    session.add(run)
    await session.flush()

    try:
        await apply_import(session, run, parsed, mode=mode, dry_run=dry_run)
    except Exception as exc:
        run.status = OneCImportRunStatus.FAILED
        run.error_message = str(exc)[:512]
    run.finished_at = now()
    await session.commit()
    await session.refresh(run)
    return run


async def import_one_c_path(session: AsyncSession, path: str, *, mode: OneCImportMode, dry_run: bool = False) -> OneCImportRun:
    content, filename = read_file(path)
    return await import_one_c_file(session, content, filename=filename, mode=mode, dry_run=dry_run)


async def apply_import(
    session: AsyncSession,
    run: OneCImportRun,
    parsed: OneCParsedFile,
    *,
    mode: OneCImportMode,
    dry_run: bool,
) -> None:
    valid_ratio = len(parsed.rows) / max(run.total_rows, 1)
    if mode == OneCImportMode.FULL:
        if len(parsed.rows) < get_settings().one_c_min_full_export_rows or valid_ratio < get_settings().one_c_min_valid_row_ratio:
            run.status = OneCImportRunStatus.REJECTED
            run.error_message = "FULL import quality gate failed"
            session.add(AuditLog(entity_type="OneCImportRun", entity_id=run.id, action="FULL_IMPORT_REJECTED", old_value=None, new_value={"valid_ratio": valid_ratio}, actor_type="SYSTEM"))
            return

    matched_rows: list[tuple[OneCParsedRow, OneCItem | None, uuid.UUID]] = []
    for row in parsed.rows:
        existing_item = await session.scalar(select(OneCItem).where(OneCItem.internal_code == row.internal_code))
        match = await match_one_c_row(session, row, existing_item)
        if match.status == OneCItemMatchStatus.MATCHED:
            run.matched_rows += 1
            matched_rows.append((row, existing_item, match.variant_id))
        elif match.status == OneCItemMatchStatus.AMBIGUOUS:
            run.ambiguous_rows += 1
        else:
            run.unmatched_rows += 1

        if not dry_run:
            item = existing_item or OneCItem(
                internal_code=row.internal_code,
                raw_name=row.raw_name,
                normalized_name=row.normalized_name,
            )
            item.sku = row.sku
            item.barcode = row.barcode
            item.raw_name = row.raw_name
            item.normalized_name = row.normalized_name
            item.last_seen_at = now()
            if not item.explicit_mapping:
                item.matched_variant_id = match.variant_id
                item.match_status = match.status
                item.match_strategy = match.strategy
                item.match_confidence = match.confidence
            session.add(item)
            await session.flush()
            if match.status == OneCItemMatchStatus.AMBIGUOUS:
                session.add(DataConflict(conflict_type="ONE_C_AMBIGUOUS_MATCH", source_id=None, product_variant_id=None, raw_source_record_id=None, details={"internal_code": row.internal_code}, status=ConflictStatus.OPEN))

    missing_zero = await missing_zero_candidates(session, [row.internal_code for row in parsed.rows]) if mode == OneCImportMode.FULL else []
    run.would_zero_missing = len(missing_zero)
    active_count = await session.scalar(select(func.count()).select_from(VariantInventoryState).where(VariantInventoryState.own_stock_total > 0))
    if mode == OneCImportMode.FULL and active_count and len(missing_zero) / active_count > get_settings().one_c_max_missing_ratio:
        run.status = OneCImportRunStatus.REJECTED
        run.error_message = "FULL import missing ratio exceeded"
        session.add(AuditLog(entity_type="OneCImportRun", entity_id=run.id, action="FULL_IMPORT_REJECTED", old_value=None, new_value={"would_zero_missing": len(missing_zero), "active_count": active_count}, actor_type="SYSTEM"))
        return

    for row, existing_item, variant_id in matched_rows:
        state = await session.get(VariantInventoryState, variant_id)
        run.would_update_stock += 1 if state is None or state.own_stock_total != row.stock_total else 0
        run.would_update_cost += 1 if state is None or state.own_cost_minor != row.cost_minor or state.currency != row.currency else 0
        if dry_run:
            continue
        item = await session.scalar(select(OneCItem).where(OneCItem.internal_code == row.internal_code))
        await apply_state(session, run, item, variant_id, row.stock_total, row.cost_minor, row.currency, row.source_updated_at, row.stock_by_store)

    if mode == OneCImportMode.FULL:
        for state, item in missing_zero:
            if dry_run:
                continue
            await apply_state(session, run, item, state.variant_id, 0, state.own_cost_minor, state.currency, run.exported_at, None, missing_zero=True)

    if dry_run:
        run.status = OneCImportRunStatus.COMPLETED_WITH_WARNINGS if run.warnings else OneCImportRunStatus.COMPLETED
    else:
        run.status = OneCImportRunStatus.COMPLETED_WITH_WARNINGS if run.warnings else OneCImportRunStatus.COMPLETED


async def apply_state(
    session: AsyncSession,
    run: OneCImportRun,
    item: OneCItem,
    variant_id: uuid.UUID,
    stock_total: int,
    cost_minor: int | None,
    currency: str,
    source_updated_at: datetime,
    stock_by_store: dict | None,
    *,
    missing_zero: bool = False,
) -> None:
    state = await session.get(VariantInventoryState, variant_id)
    if state is not None and source_updated_at < state.source_updated_at:
        return
    stock_changed = state is None or state.own_stock_total != stock_total
    cost_changed = cost_minor is not None and (state is None or state.own_cost_minor != cost_minor or state.currency != currency)
    old_stock = state.own_stock_total if state else None
    old_cost = state.own_cost_minor if state else None

    if state is None:
        state = VariantInventoryState(
            variant_id=variant_id,
            own_stock_total=stock_total,
            own_cost_minor=cost_minor,
            currency=currency,
            source_item_id=item.id,
            source_updated_at=source_updated_at,
            last_import_run_id=run.id,
        )
        session.add(state)
    else:
        state.own_stock_total = stock_total
        if cost_minor is not None:
            state.own_cost_minor = cost_minor
            state.currency = currency
        state.source_item_id = item.id
        state.source_updated_at = source_updated_at
        state.last_import_run_id = run.id

    if stock_changed:
        session.add(VariantStockSnapshot(variant_id=variant_id, source_item_id=item.id, import_run_id=run.id, stock_total=stock_total, stock_by_store=stock_by_store, source_updated_at=source_updated_at))
        action = "FULL_IMPORT_MISSING_ZERO_APPLIED" if missing_zero else "OWN_STOCK_CHANGED"
        session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action=action, old_value={"own_stock_total": old_stock}, new_value={"own_stock_total": stock_total}, actor_type="SYSTEM"))
    if cost_changed and cost_minor is not None:
        session.add(VariantCostSnapshot(variant_id=variant_id, source_item_id=item.id, import_run_id=run.id, cost_minor=cost_minor, currency=currency, source_updated_at=source_updated_at))
        session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action="OWN_COST_CHANGED", old_value={"own_cost_minor": old_cost}, new_value={"own_cost_minor": cost_minor}, actor_type="SYSTEM"))


async def missing_zero_candidates(session: AsyncSession, present_codes: list[str]) -> list[tuple[VariantInventoryState, OneCItem]]:
    statement = (
        select(VariantInventoryState, OneCItem)
        .join(OneCItem, OneCItem.id == VariantInventoryState.source_item_id)
        .where(VariantInventoryState.own_stock_total > 0)
    )
    rows = []
    for state, item in (await session.execute(statement)).all():
        if item.internal_code not in present_codes:
            rows.append((state, item))
    return rows


async def map_one_c_item(session: AsyncSession, item_id: uuid.UUID, variant_id: uuid.UUID) -> OneCItem:
    item = await session.get(OneCItem, item_id)
    variant = await session.get(ProductVariant, variant_id)
    if item is None:
        raise ValueError("OneCItem not found")
    if variant is None:
        raise ValueError("ProductVariant not found")
    old = str(item.matched_variant_id) if item.matched_variant_id else None
    item.matched_variant_id = variant_id
    item.match_status = OneCItemMatchStatus.MATCHED
    item.match_strategy = OneCItemMatchStrategy.MANUAL
    item.match_confidence = 1.0
    item.explicit_mapping = True
    session.add(AuditLog(entity_type="OneCItem", entity_id=item.id, action="ONE_C_ITEM_MAPPED", old_value={"variant_id": old}, new_value={"variant_id": str(variant_id)}, actor_type="USER"))
    await session.commit()
    await session.refresh(item)
    return item


async def unmap_one_c_item(session: AsyncSession, item_id: uuid.UUID) -> OneCItem:
    item = await session.get(OneCItem, item_id)
    if item is None:
        raise ValueError("OneCItem not found")
    old = str(item.matched_variant_id) if item.matched_variant_id else None
    item.matched_variant_id = None
    item.match_status = OneCItemMatchStatus.UNMATCHED
    item.match_strategy = None
    item.match_confidence = None
    item.explicit_mapping = False
    session.add(AuditLog(entity_type="OneCItem", entity_id=item.id, action="ONE_C_ITEM_UNMAPPED", old_value={"variant_id": old}, new_value=None, actor_type="USER"))
    await session.commit()
    await session.refresh(item)
    return item


async def get_effective_procurement_cost(session: AsyncSession, variant_id: uuid.UUID) -> dict:
    state = await session.get(VariantInventoryState, variant_id)
    return {"variant_id": variant_id, "own_stock_cost_minor": state.own_cost_minor if state else None, "supplier_offers": []}


def now() -> datetime:
    return datetime.now(UTC)
