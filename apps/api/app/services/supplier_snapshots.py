import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.enums import (
    Availability,
    MatchStatus,
    ParseStatus,
    SupplierSnapshotItemStatus,
    SupplierSnapshotStatus,
    SupplierSnapshotType,
)
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.supplier_offer import SupplierOffer, SupplierOfferSnapshot
from app.models.supplier_snapshot import SupplierSnapshot, SupplierSnapshotItem
from app.schemas.supplier_snapshot import SupplierSnapshotCreate
from app.services.matcher import match_parsed_item
from app.services.parser.pipeline import parse_raw_record


def utc_now() -> datetime:
    return datetime.now(UTC)


async def create_snapshot(session: AsyncSession, payload: SupplierSnapshotCreate) -> SupplierSnapshot:
    existing = await session.scalar(
        select(SupplierSnapshot).where(
            SupplierSnapshot.supplier_id == payload.supplier_id,
            SupplierSnapshot.source_id == payload.source_id,
            SupplierSnapshot.raw_source_record_id == payload.raw_source_record_id,
        )
    )
    if existing is not None:
        return existing
    snapshot = SupplierSnapshot(
        supplier_id=payload.supplier_id,
        source_id=payload.source_id,
        raw_source_record_id=payload.raw_source_record_id,
        external_snapshot_id=payload.external_snapshot_id,
        snapshot_type=payload.snapshot_type,
        captured_at=payload.captured_at or utc_now(),
        status=SupplierSnapshotStatus.PENDING,
    )
    session.add(snapshot)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        snapshot = await session.scalar(
            select(SupplierSnapshot).where(
                SupplierSnapshot.supplier_id == payload.supplier_id,
                SupplierSnapshot.source_id == payload.source_id,
                SupplierSnapshot.raw_source_record_id == payload.raw_source_record_id,
            )
        )
        if snapshot is None:
            raise
        return snapshot
    await session.refresh(snapshot)
    return snapshot


async def process_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> dict:
    lock_key = str(snapshot_id)
    await session.execute(text("SELECT pg_advisory_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    try:
        return await _process_snapshot_locked(session, snapshot_id)
    finally:
        await session.execute(text("SELECT pg_advisory_unlock(hashtext(:lock_key))"), {"lock_key": lock_key})


async def _process_snapshot_locked(session: AsyncSession, snapshot_id: uuid.UUID) -> dict:
    snapshot = await session.scalar(select(SupplierSnapshot).where(SupplierSnapshot.id == snapshot_id).with_for_update())
    if snapshot is None:
        raise ValueError("SupplierSnapshot not found")
    if snapshot.status in {SupplierSnapshotStatus.COMPLETED, SupplierSnapshotStatus.REJECTED}:
        return await summarize_snapshot(session, snapshot, quality_gate_passed=snapshot.status == SupplierSnapshotStatus.COMPLETED)

    snapshot.status = SupplierSnapshotStatus.PROCESSING
    await session.commit()

    try:
        parse_result, parsed_rows = await parse_raw_record(session, snapshot.raw_source_record_id)
        await session.execute(delete(SupplierSnapshotItem).where(SupplierSnapshotItem.snapshot_id == snapshot.id))

        exact_match = auto_created = review = conflict = rejected = offers_created = offers_updated = 0
        seen_offer_ids: set[uuid.UUID] = set()

        for parsed in parsed_rows:
            if parsed.parse_status == ParseStatus.IGNORED:
                continue
            if parsed.parse_status == ParseStatus.CONFLICT:
                conflict += 1
                session.add(
                    SupplierSnapshotItem(
                        snapshot_id=snapshot.id,
                        parsed_supplier_item_id=parsed.id,
                        match_status=MatchStatus.CONFLICT_BLOCKED,
                        item_status=SupplierSnapshotItemStatus.CONFLICT,
                    )
                )
                continue
            result = await match_parsed_item(session, parsed.id)
            if result.status == MatchStatus.EXACT_MATCH:
                exact_match += 1
            elif result.status == MatchStatus.AUTO_CREATED:
                auto_created += 1
            elif result.status == MatchStatus.REVIEW:
                review += 1
            elif result.status == MatchStatus.REJECTED:
                rejected += 1
            elif result.status == MatchStatus.CONFLICT_BLOCKED:
                conflict += 1

            offer = None
            item_status = SupplierSnapshotItemStatus.REVIEW
            if result.status in {MatchStatus.EXACT_MATCH, MatchStatus.AUTO_CREATED} and result.matched_variant_id:
                offer = await session.scalar(
                    select(SupplierOffer).where(
                        SupplierOffer.supplier_id == snapshot.supplier_id,
                        SupplierOffer.product_variant_id == result.matched_variant_id,
                        SupplierOffer.supplier_sku == str(result.matched_variant_id),
                    )
                )
                item_status = SupplierSnapshotItemStatus.SEEN if offer else SupplierSnapshotItemStatus.REVIEW
            elif result.status == MatchStatus.CONFLICT_BLOCKED:
                item_status = SupplierSnapshotItemStatus.CONFLICT
            elif result.status == MatchStatus.REJECTED:
                item_status = SupplierSnapshotItemStatus.REJECTED

            if offer:
                seen_offer_ids.add(offer.id)
                offers_created += int(result.offer_created)
                offers_updated += int(result.offer_updated)
            session.add(
                SupplierSnapshotItem(
                    snapshot_id=snapshot.id,
                    parsed_supplier_item_id=parsed.id,
                    supplier_offer_id=offer.id if offer else None,
                    product_variant_id=result.matched_variant_id,
                    match_status=result.status,
                    item_status=item_status,
                )
            )
        await session.flush()

        snapshot.total_lines = parse_result.total_lines
        snapshot.parsed_items = len([row for row in parsed_rows if row.parse_status != ParseStatus.IGNORED])
        snapshot.matched_items = exact_match + auto_created
        snapshot.offers_seen = len(seen_offer_ids)
        snapshot.conflicts_count = conflict
        snapshot.review_count = review
        snapshot.parser_error_count = rejected

        gate_passed, reason = quality_gate(snapshot, raw_text_non_empty=parse_result.total_lines > 0)
        snapshot.quality_gate_reason = reason
        availability_counts = {
            "moved_to_in_stock": 0,
            "moved_to_suspect_missing": 0,
            "moved_to_out_of_stock": 0,
            "restored": 0,
        }
        if gate_passed and snapshot.snapshot_type == SupplierSnapshotType.FULL:
            availability_counts = await apply_snapshot_availability(session, snapshot, seen_offer_ids)
            snapshot.status = SupplierSnapshotStatus.COMPLETED
        elif snapshot.snapshot_type == SupplierSnapshotType.PARTIAL:
            await mark_seen_offers_in_stock(session, snapshot, seen_offer_ids, availability_counts)
            snapshot.status = SupplierSnapshotStatus.COMPLETED
        else:
            snapshot.status = SupplierSnapshotStatus.REJECTED
        snapshot.processed_at = utc_now()
        await session.commit()
        return await summarize_snapshot(
            session,
            snapshot,
            quality_gate_passed=gate_passed,
            availability_counts=availability_counts,
            offers_created=offers_created,
            offers_updated=offers_updated,
        )
    except Exception:
        await session.rollback()
        snapshot = await session.get(SupplierSnapshot, snapshot_id)
        if snapshot:
            snapshot.status = SupplierSnapshotStatus.FAILED
            snapshot.processed_at = utc_now()
            await session.commit()
        raise


def quality_gate(snapshot: SupplierSnapshot, *, raw_text_non_empty: bool) -> tuple[bool, str | None]:
    if not raw_text_non_empty:
        return False, "EMPTY_RAW_TEXT"
    if snapshot.offers_seen < 1:
        return False, "NO_VALID_ITEMS"
    candidate_lines = snapshot.parsed_items
    if candidate_lines <= 0:
        return False, "NO_VALID_ITEMS"
    ratio = snapshot.offers_seen / candidate_lines
    if ratio < get_settings().snapshot_min_valid_item_ratio:
        return False, "LOW_VALID_ITEM_RATIO"
    return True, None


async def apply_snapshot_availability(
    session: AsyncSession, snapshot: SupplierSnapshot, seen_offer_ids: set[uuid.UUID]
) -> dict[str, int]:
    counts = {"moved_to_in_stock": 0, "moved_to_suspect_missing": 0, "moved_to_out_of_stock": 0, "restored": 0}
    await mark_seen_offers_in_stock(session, snapshot, seen_offer_ids, counts)
    offers = list(await session.scalars(select(SupplierOffer).where(SupplierOffer.supplier_id == snapshot.supplier_id)))
    threshold = get_settings().supplier_missing_snapshots_to_out_of_stock
    for offer in offers:
        if offer.id in seen_offer_ids:
            continue
        if offer.last_processed_snapshot_at and snapshot.captured_at < offer.last_processed_snapshot_at:
            continue
        previous = offer.availability
        offer.consecutive_missing_count += 1
        offer.last_missing_snapshot_id = snapshot.id
        offer.last_processed_snapshot_at = snapshot.captured_at
        if offer.consecutive_missing_count >= threshold:
            await transition_offer(session, offer, Availability.OUT_OF_STOCK, snapshot.id, counts, "moved_to_out_of_stock")
        elif offer.availability == Availability.IN_STOCK:
            await transition_offer(session, offer, Availability.SUSPECT_MISSING, snapshot.id, counts, "moved_to_suspect_missing")
        elif previous == Availability.UNKNOWN:
            await transition_offer(session, offer, Availability.SUSPECT_MISSING, snapshot.id, counts, "moved_to_suspect_missing")
    return counts


async def mark_seen_offers_in_stock(
    session: AsyncSession, snapshot: SupplierSnapshot, seen_offer_ids: set[uuid.UUID], counts: dict[str, int]
) -> None:
    if not seen_offer_ids:
        return
    offers = list(await session.scalars(select(SupplierOffer).where(SupplierOffer.id.in_(seen_offer_ids))))
    for offer in offers:
        if offer.last_processed_snapshot_at and snapshot.captured_at < offer.last_processed_snapshot_at:
            continue
        was_missing = offer.availability in {Availability.SUSPECT_MISSING, Availability.OUT_OF_STOCK}
        offer.consecutive_missing_count = 0
        offer.last_seen_snapshot_id = snapshot.id
        offer.last_processed_snapshot_at = snapshot.captured_at
        offer.last_seen_at = utc_now()
        if offer.availability != Availability.IN_STOCK:
            key = "restored" if was_missing else "moved_to_in_stock"
            await transition_offer(
                session,
                offer,
                Availability.IN_STOCK,
                snapshot.id,
                counts,
                key,
                dedupe_source_record_id=snapshot.raw_source_record_id,
            )


async def transition_offer(
    session: AsyncSession,
    offer: SupplierOffer,
    new_status: Availability,
    snapshot_id: uuid.UUID,
    counts: dict[str, int],
    count_key: str,
    *,
    dedupe_source_record_id: uuid.UUID | None = None,
) -> None:
    previous = offer.availability
    if previous == new_status:
        return
    offer.availability = new_status
    offer.last_availability_change_at = utc_now()
    counts[count_key] += 1
    action = {
        Availability.IN_STOCK: "SUPPLIER_OFFER_RESTORED" if previous in {Availability.SUSPECT_MISSING, Availability.OUT_OF_STOCK} else "SUPPLIER_OFFER_IN_STOCK",
        Availability.SUSPECT_MISSING: "SUPPLIER_OFFER_SUSPECT_MISSING",
        Availability.OUT_OF_STOCK: "SUPPLIER_OFFER_OUT_OF_STOCK",
    }.get(new_status, "SUPPLIER_OFFER_AVAILABILITY_CHANGED")
    snapshot_already_recorded = False
    if (
        dedupe_source_record_id is not None
        and previous in {Availability.SUSPECT_MISSING, Availability.OUT_OF_STOCK}
        and new_status == Availability.IN_STOCK
    ):
        snapshot_already_recorded = bool(
            await session.scalar(
                select(SupplierOfferSnapshot.id).where(
                    SupplierOfferSnapshot.supplier_offer_id == offer.id,
                    SupplierOfferSnapshot.price_minor == offer.price_minor,
                    SupplierOfferSnapshot.availability == previous,
                    SupplierOfferSnapshot.source_record_id == dedupe_source_record_id,
                )
            )
        )
    if not snapshot_already_recorded:
        session.add(
            SupplierOfferSnapshot(
                supplier_offer_id=offer.id,
                price_minor=offer.price_minor,
                availability=new_status,
                source_record_id=offer.source_record_id,
            )
        )
    session.add(
        AuditLog(
            entity_type="SupplierOffer",
            entity_id=offer.id,
            action=action,
            old_value={"availability": previous.value},
            new_value={
                "availability": new_status.value,
                "snapshot_id": str(snapshot_id),
                "missing_count": offer.consecutive_missing_count,
            },
            actor_type="SYSTEM",
        )
    )


async def summarize_snapshot(
    session: AsyncSession,
    snapshot: SupplierSnapshot,
    *,
    quality_gate_passed: bool,
    availability_counts: dict[str, int] | None = None,
    offers_created: int = 0,
    offers_updated: int = 0,
) -> dict:
    availability_counts = availability_counts or {
        "moved_to_in_stock": 0,
        "moved_to_suspect_missing": 0,
        "moved_to_out_of_stock": 0,
        "restored": 0,
    }
    items = list(await session.scalars(select(SupplierSnapshotItem).where(SupplierSnapshotItem.snapshot_id == snapshot.id)))
    return {
        "snapshot_id": snapshot.id,
        "status": snapshot.status,
        "total_lines": snapshot.total_lines,
        "parsed": snapshot.parsed_items,
        "exact_match": sum(item.match_status == MatchStatus.EXACT_MATCH for item in items),
        "auto_created": sum(item.match_status == MatchStatus.AUTO_CREATED for item in items),
        "review": sum(item.item_status == SupplierSnapshotItemStatus.REVIEW for item in items),
        "conflict": sum(item.item_status == SupplierSnapshotItemStatus.CONFLICT for item in items),
        "rejected": sum(item.item_status == SupplierSnapshotItemStatus.REJECTED for item in items),
        "offers_created": offers_created,
        "offers_updated": offers_updated,
        "offers_seen": snapshot.offers_seen,
        "quality_gate_passed": quality_gate_passed,
        **availability_counts,
    }
