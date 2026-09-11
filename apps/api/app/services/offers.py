import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.conflict import DataConflict
from app.models.enums import ConflictStatus
from app.models.supplier_offer import SupplierOffer, SupplierOfferSnapshot
from app.schemas.supplier_offer import SupplierOfferCreate


async def upsert_supplier_offer(session: AsyncSession, payload: SupplierOfferCreate) -> SupplierOffer:
    offer = None
    if payload.supplier_sku is not None:
        offer = await session.scalar(
            select(SupplierOffer).where(
                SupplierOffer.supplier_id == payload.supplier_id,
                SupplierOffer.supplier_sku == payload.supplier_sku,
            )
        )

    now = datetime.now(UTC)
    if offer is None:
        offer = SupplierOffer(**payload.model_dump(), first_seen_at=now, last_seen_at=now)
        session.add(offer)
        await session.flush()
        session.add(
            SupplierOfferSnapshot(
                supplier_offer_id=offer.id,
                price_minor=offer.price_minor,
                availability=offer.availability,
                source_record_id=offer.source_record_id,
            )
        )
        try:
            await session.commit()
            await session.refresh(offer)
            return offer
        except IntegrityError:
            await session.rollback()
            if payload.supplier_sku is None:
                raise
            existing = await session.scalar(
                select(SupplierOffer).where(
                    SupplierOffer.supplier_id == payload.supplier_id,
                    SupplierOffer.supplier_sku == payload.supplier_sku,
                )
            )
            if existing is None:
                raise
            return existing

    old = {"price_minor": offer.price_minor, "availability": offer.availability.value}
    changed = offer.price_minor != payload.price_minor or offer.availability != payload.availability
    if changed:
        offer.price_minor = payload.price_minor
        offer.availability = payload.availability
        offer.supplier_title = payload.supplier_title
        offer.currency = payload.currency
        offer.source_id = payload.source_id
        offer.source_record_id = payload.source_record_id
        offer.source_updated_at = payload.source_updated_at
        offer.last_seen_at = now
        session.add(
            SupplierOfferSnapshot(
                supplier_offer_id=offer.id,
                price_minor=payload.price_minor,
                availability=payload.availability,
                source_record_id=payload.source_record_id,
            )
        )
        session.add(
            AuditLog(
                entity_type="SupplierOffer",
                entity_id=offer.id,
                action="UPDATED",
                old_value=old,
                new_value={"price_minor": payload.price_minor, "availability": payload.availability.value},
                actor_type="system",
            )
        )
    else:
        offer.last_seen_at = now
    await session.commit()
    await session.refresh(offer)
    return offer


async def record_price_conflict(
    session: AsyncSession,
    *,
    supplier_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    source_id: uuid.UUID | None,
    raw_source_record_id: uuid.UUID | None,
    first_price_minor: int,
    second_price_minor: int,
) -> DataConflict | None:
    if first_price_minor == second_price_minor:
        return None

    conflict = DataConflict(
        conflict_type="SUPPLIER_VARIANT_PRICE_MISMATCH",
        source_id=source_id,
        product_variant_id=product_variant_id,
        raw_source_record_id=raw_source_record_id,
        details={
            "supplier_id": str(supplier_id),
            "first_price_minor": first_price_minor,
            "second_price_minor": second_price_minor,
        },
        status=ConflictStatus.OPEN,
    )
    session.add(conflict)
    await session.commit()
    await session.refresh(conflict)
    return conflict
