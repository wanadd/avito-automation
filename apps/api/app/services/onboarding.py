import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.one_c.importer import import_one_c_file, map_one_c_item
from app.models.audit_log import AuditLog
from app.models.conflict import DataConflict
from app.models.content import GenericListingDraft, ProductContentDraft, ProductContentFacts, ProductImageSet
from app.models.enums import (
    ConflictStatus,
    GenericReadinessStatus,
    OneCImportMode,
    OneCImportRunStatus,
    ProductCondition,
    PublicationJobStatus,
    ReviewStatus,
    SupplierSnapshotType,
)
from app.models.manual_import import ManualImportBatch
from app.models.match_review import MatchReview
from app.models.one_c import OneCImportRun, OneCItem, VariantInventoryState
from app.models.product import Product, ProductAlias, ProductVariant
from app.models.publication import PublicationIntent, PublicationJob
from app.models.raw_source_record import RawSourceRecord
from app.models.source import Source
from app.models.supplier_offer import SupplierOffer
from app.models.supplier_snapshot import SupplierSnapshot
from app.schemas.onboarding import ProductOnboardingRequest
from app.schemas.raw_source_record import RawSourceRecordCreate
from app.schemas.supplier_snapshot import SupplierSnapshotCreate
from app.services.canonical_key import build_canonical_key
from app.services.parser.pipeline import parse_price_text
from app.services.raw_records import create_raw_record
from app.services.supplier_snapshots import create_snapshot, process_snapshot


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_alias(value: str) -> str:
    return " ".join(value.casefold().split())


def _parsed_preview(raw_text: str) -> dict:
    parsed = parse_price_text(raw_text)
    counts = {"PARSED": 0, "PARTIAL": 0, "REVIEW": 0, "CONFLICT": 0, "IGNORED": 0}
    items = []
    for item in parsed.items:
        counts[item.parse_status.value] += 1
        if item.parse_status.value == "IGNORED":
            continue
        items.append(
            {
                "line_number": item.line_number,
                "raw_line": item.raw_line,
                "status": item.parse_status.value,
                "brand": item.brand_normalized,
                "model": item.model_normalized,
                "model_code": item.manufacturer_model_code,
                "condition": item.condition.value if item.condition else None,
                "price_minor": item.price_minor,
                "flags": item.parse_flags,
            }
        )
    candidate_lines = parsed.total_lines - counts["IGNORED"]
    valid_seen_items = counts["PARSED"] + counts["PARTIAL"]
    ratio = valid_seen_items / candidate_lines if candidate_lines else 0
    return {
        "total_lines": parsed.total_lines,
        "candidate_product_lines": candidate_lines,
        "valid_seen_items": valid_seen_items,
        "computed_ratio": ratio,
        "counts": counts,
        "items": items,
    }


async def preview_telegram_manual_import(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    raw_text: str,
    snapshot_type: SupplierSnapshotType,
    captured_at: datetime | None,
    actor: str | None,
) -> ManualImportBatch:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    content_hash = _hash_text(raw_text)
    scope_key = f"source:{source_id}"
    existing = await session.scalar(
        select(ManualImportBatch).where(
            ManualImportBatch.import_type == "TELEGRAM",
            ManualImportBatch.scope_key == scope_key,
            ManualImportBatch.content_hash == content_hash,
            ManualImportBatch.mode == snapshot_type.value,
        )
    )
    if existing is not None:
        return existing
    preview = _parsed_preview(raw_text)
    if captured_at is not None:
        preview["captured_at"] = captured_at.isoformat()
    batch = ManualImportBatch(
        import_type="TELEGRAM",
        scope_key=scope_key,
        source_id=source.id,
        supplier_id=source.supplier_id,
        mode=snapshot_type.value,
        status="PREVIEWED",
        content_hash=content_hash,
        raw_content=raw_text,
        preview=preview,
        actor=actor,
    )
    session.add(batch)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return await session.scalar(
            select(ManualImportBatch).where(
                ManualImportBatch.import_type == "TELEGRAM",
                ManualImportBatch.scope_key == scope_key,
                ManualImportBatch.content_hash == content_hash,
                ManualImportBatch.mode == snapshot_type.value,
            )
        )
    await session.refresh(batch)
    return batch


async def confirm_telegram_manual_import(session: AsyncSession, batch_id: uuid.UUID, *, actor: str | None = None) -> ManualImportBatch:
    batch = await session.get(ManualImportBatch, batch_id)
    if batch is None or batch.import_type != "TELEGRAM":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manual import batch not found")
    if batch.status in {"CONFIRMED", "DUPLICATE"}:
        return batch
    source = await session.get(Source, batch.source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    raw = await create_raw_record(
        session,
        RawSourceRecordCreate(
            source_id=source.id,
            external_record_id=f"manual:{batch.content_hash}",
            raw_text=batch.raw_content,
            raw_payload={"manual_import_batch_id": str(batch.id), "import_type": "TELEGRAM"},
        ),
    )
    snapshot = await create_snapshot(
        session,
        SupplierSnapshotCreate(
            supplier_id=source.supplier_id,
            source_id=source.id,
            raw_source_record_id=raw.id,
            external_snapshot_id=f"manual:{batch.content_hash}",
            snapshot_type=SupplierSnapshotType(batch.mode),
            captured_at=_captured_at_from_preview(batch.preview),
        ),
    )
    summary = jsonable_encoder(await process_snapshot(session, snapshot.id))
    batch.raw_source_record_id = raw.id
    batch.supplier_snapshot_id = snapshot.id
    batch.status = "CONFIRMED"
    batch.result = {"snapshot": summary}
    batch.actor = actor or batch.actor
    batch.confirmed_at = datetime.now(UTC)
    session.add(AuditLog(entity_type="ManualImportBatch", entity_id=batch.id, action="TELEGRAM_MANUAL_IMPORT_CONFIRMED", old_value=None, new_value=batch.result, actor_type="USER"))
    await session.commit()
    await session.refresh(batch)
    return batch


async def preview_one_c_manual_import(
    session: AsyncSession,
    *,
    filename: str,
    content: str,
    mode: OneCImportMode,
    actor: str | None,
) -> ManualImportBatch:
    content_hash = _hash_text(content)
    existing = await session.scalar(
        select(ManualImportBatch).where(
            ManualImportBatch.import_type == "ONE_C",
            ManualImportBatch.scope_key == "one_c",
            ManualImportBatch.content_hash == content_hash,
            ManualImportBatch.mode == mode.value,
        )
    )
    if existing is not None:
        return existing
    run = await import_one_c_file(session, content.encode("utf-8"), filename=filename, mode=mode, dry_run=True)
    preview = {
        "run_id": str(run.id),
        "status": run.status.value,
        "total_rows": run.total_rows,
        "valid_rows": run.valid_rows,
        "invalid_rows": run.invalid_rows,
        "matched_rows": run.matched_rows,
        "unmatched_rows": run.unmatched_rows,
        "ambiguous_rows": run.ambiguous_rows,
        "duplicate_rows": run.duplicate_rows,
        "would_update_stock": run.would_update_stock,
        "would_update_cost": run.would_update_cost,
        "would_zero_missing": run.would_zero_missing,
        "warnings": run.warnings,
        "error_message": run.error_message,
    }
    batch = ManualImportBatch(
        import_type="ONE_C",
        scope_key="one_c",
        mode=mode.value,
        status="PREVIEWED",
        filename=filename,
        content_hash=content_hash,
        raw_content=content,
        preview=preview,
        one_c_import_run_id=run.id,
        actor=actor,
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    return batch


async def confirm_one_c_manual_import(session: AsyncSession, batch_id: uuid.UUID, *, actor: str | None = None) -> ManualImportBatch:
    batch = await session.get(ManualImportBatch, batch_id)
    if batch is None or batch.import_type != "ONE_C":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manual import batch not found")
    if batch.status in {"CONFIRMED", "DUPLICATE"}:
        return batch
    run = await import_one_c_file(session, batch.raw_content.encode("utf-8"), filename=batch.filename, mode=OneCImportMode(batch.mode), dry_run=False)
    batch.one_c_import_run_id = run.id
    batch.status = "CONFIRMED" if run.status != OneCImportRunStatus.DUPLICATE else "DUPLICATE"
    batch.result = {
        "run_id": str(run.id),
        "status": run.status.value,
        "total_rows": run.total_rows,
        "valid_rows": run.valid_rows,
        "invalid_rows": run.invalid_rows,
        "matched_rows": run.matched_rows,
        "unmatched_rows": run.unmatched_rows,
        "ambiguous_rows": run.ambiguous_rows,
        "would_update_stock": run.would_update_stock,
        "would_update_cost": run.would_update_cost,
        "would_zero_missing": run.would_zero_missing,
        "warnings": run.warnings,
        "error_message": run.error_message,
    }
    batch.actor = actor or batch.actor
    batch.confirmed_at = datetime.now(UTC)
    session.add(AuditLog(entity_type="ManualImportBatch", entity_id=batch.id, action="ONE_C_MANUAL_IMPORT_CONFIRMED", old_value=None, new_value=batch.result, actor_type="USER"))
    await session.commit()
    await session.refresh(batch)
    return batch


async def onboard_product(session: AsyncSession, payload: ProductOnboardingRequest) -> dict:
    product = await session.scalar(
        select(Product).where(Product.brand == payload.product.brand, Product.canonical_name == payload.product.canonical_name)
    )
    if product is None:
        product = Product(**payload.product.model_dump())
        session.add(product)
        await session.flush()

    canonical_key = build_canonical_key(
        brand=product.brand,
        canonical_name=product.canonical_name,
        manufacturer_model_code=payload.variant.manufacturer_model_code,
        ram_gb=payload.variant.ram_gb,
        storage_gb=payload.variant.storage_gb,
        color_normalized=payload.variant.color_normalized,
        region_code=payload.variant.region_code,
        condition=payload.variant.condition,
    )
    variant = await session.scalar(select(ProductVariant).where(ProductVariant.canonical_key == canonical_key))
    if variant is None:
        variant = ProductVariant(product_id=product.id, canonical_key=canonical_key, **payload.variant.model_dump())
        session.add(variant)
        await session.flush()
    aliases_created = 0
    for alias in payload.aliases:
        normalized = _normalize_alias(alias.alias)
        existing_alias = await session.scalar(
            select(ProductAlias).where(ProductAlias.normalized_alias == normalized, ProductAlias.source_id == alias.source_id)
        )
        if existing_alias is None:
            session.add(ProductAlias(product_variant_id=variant.id, alias=alias.alias, normalized_alias=normalized, source_id=alias.source_id))
            aliases_created += 1
    if payload.one_c_item_id is not None:
        await map_one_c_item(session, payload.one_c_item_id, variant.id)
    session.add(
        AuditLog(
            entity_type="ProductVariant",
            entity_id=variant.id,
            action="PRODUCT_ONBOARDED",
            old_value=None,
            new_value={"aliases_created": aliases_created, "condition": variant.condition.value if isinstance(variant.condition, ProductCondition) else variant.condition},
            actor_type="USER",
        )
    )
    await session.commit()
    await session.refresh(product)
    await session.refresh(variant)
    return {"product": product, "variant": variant, "aliases_created": aliases_created, "one_c_item_id": payload.one_c_item_id}


async def accept_match_review(
    session: AsyncSession,
    review_id: uuid.UUID,
    *,
    variant_id: uuid.UUID,
    alias: str | None,
    actor: str,
) -> MatchReview:
    review = await session.get(MatchReview, review_id)
    variant = await session.get(ProductVariant, variant_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MatchReview not found")
    if variant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ProductVariant not found")
    old_status = review.status.value
    review.status = ReviewStatus.ACCEPTED
    review.candidate_variant_id = variant.id
    if alias:
        normalized = _normalize_alias(alias)
        existing_alias = await session.scalar(
            select(ProductAlias).where(ProductAlias.normalized_alias == normalized, ProductAlias.source_id.is_(None))
        )
        if existing_alias is None:
            session.add(ProductAlias(product_variant_id=variant.id, alias=alias, normalized_alias=normalized, source_id=None))
    session.add(
        AuditLog(
            entity_type="MatchReview",
            entity_id=review.id,
            action="MATCH_REVIEW_ACCEPTED",
            old_value={"status": old_status},
            new_value={"status": review.status.value, "variant_id": str(variant.id), "alias": alias},
            actor_type="USER",
            actor_id=actor,
        )
    )
    await session.commit()
    await session.refresh(review)
    return review


async def resolve_conflict(
    session: AsyncSession,
    conflict_id: uuid.UUID,
    *,
    actor: str,
    resolution: str | None,
) -> DataConflict:
    conflict = await session.get(DataConflict, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DataConflict not found")
    old_status = conflict.status.value
    conflict.status = ConflictStatus.RESOLVED
    conflict.resolved_at = datetime.now(UTC)
    session.add(
        AuditLog(
            entity_type="DataConflict",
            entity_id=conflict.id,
            action="DATA_CONFLICT_RESOLVED",
            old_value={"status": old_status},
            new_value={"status": conflict.status.value, "resolution": resolution},
            actor_type="USER",
            actor_id=actor,
        )
    )
    await session.commit()
    await session.refresh(conflict)
    return conflict


async def listing_dry_run_validation(session: AsyncSession, listing_id: uuid.UUID) -> dict:
    listing = await session.get(GenericListingDraft, listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GenericListingDraft not found")
    checks = {
        "listing_approved": listing.generic_readiness == GenericReadinessStatus.APPROVED,
        "has_title": bool(listing.title),
        "has_description": bool(listing.description),
        "has_price": listing.price_minor is not None,
        "has_stock_decision": listing.stock_decision is not None,
        "avito_contract_disabled": True,
    }
    job = await session.scalar(
        select(PublicationJob)
        .join(PublicationIntent, PublicationIntent.id == PublicationJob.intent_id)
        .where(PublicationIntent.listing_id == listing.id)
        .order_by(PublicationJob.created_at.desc())
    )
    checks["dry_run_success"] = bool(job and job.status.value == "DRY_RUN_SUCCESS" and job.dry_run)
    checks.update(
        {
            "IDENTITY": bool(listing.variant_id),
            "STOCK": listing.stock_decision in {"ACTIVE", "REVIEW"},
            "PRICE": listing.price_minor is not None,
            "CONTENT": bool(listing.content_draft_id and listing.title and listing.description),
            "IMAGES": listing.image_set_id is not None,
            "CONFLICTS": True,
            "HASHES": bool(listing.content_hash and job and job.payload_hash),
        }
    )
    status_value = "INTERNAL_DRY_RUN_VALIDATED" if all(checks.values()) else "NOT_READY"
    return {"status": status_value, "listing_id": str(listing.id), "checks": checks, "job_id": str(job.id) if job else None}


async def pilot_readiness(session: AsyncSession) -> dict:
    dry_run_validated = await _dry_run_validated_count(session)
    checks = {
        "TOTAL": await _count(session, ProductVariant),
        "MATCHED": await _count(session, OneCItem, OneCItem.matched_variant_id.is_not(None)),
        "MATCH_REVIEW": await _count(session, MatchReview),
        "CONFLICT": await _count(session, DataConflict),
        "OWN_STOCK": await _count(session, VariantInventoryState, VariantInventoryState.own_stock_total > 0),
        "SUPPLIER_ONLY": await _supplier_only_count(session),
        "NO_STOCK": await _no_stock_count(session),
        "PRICING_READY": await _pricing_ready_count(session),
        "PRICING_REVIEW": await _pricing_review_count(session),
        "FACTS_READY": await _count(session, ProductContentFacts, ProductContentFacts.requires_review.is_(False), ProductContentFacts.has_conflicts.is_(False)),
        "CONTENT_READY": await _count(session, ProductContentDraft, ProductContentDraft.approved_at.is_not(None)),
        "IMAGES_READY": await _count(session, ProductImageSet, ProductImageSet.approved_at.is_not(None)),
        "LISTING_READY": await _listing_ready_count(session),
        "APPROVED": await _count(session, GenericListingDraft, GenericListingDraft.generic_readiness == GenericReadinessStatus.APPROVED),
        "DRY_RUN_VALIDATED": dry_run_validated,
        "raw_records": await _count(session, RawSourceRecord),
        "telegram_manual_batches": await _count(session, ManualImportBatch, ManualImportBatch.import_type == "TELEGRAM"),
        "one_c_items": await _count(session, OneCItem),
        "one_c_import_runs": await _count(session, OneCImportRun),
        "products": await _count(session, Product),
        "variants": await _count(session, ProductVariant),
        "supplier_offers": await _count(session, SupplierOffer),
        "inventory_states": await _count(session, VariantInventoryState),
        "content_facts": await _count(session, ProductContentFacts),
        "content_drafts": await _count(session, ProductContentDraft),
        "image_sets": await _count(session, ProductImageSet),
        "generic_listings": await _count(session, GenericListingDraft),
        "dry_run_success_jobs": dry_run_validated,
    }
    critical = ["TOTAL", "LISTING_READY"]
    status_value = "READY_FOR_PILOT" if all(checks[key] > 0 for key in critical) else "NOT_READY"
    return {"status": status_value, "checks": checks}


async def _count(session: AsyncSession, model, *criteria) -> int:
    statement = select(func.count()).select_from(model)
    for criterion in criteria:
        statement = statement.where(criterion)
    return int(await session.scalar(statement) or 0)


async def _supplier_only_count(session: AsyncSession) -> int:
    rows = await session.execute(
        select(func.count())
        .select_from(ProductVariant)
        .outerjoin(VariantInventoryState, VariantInventoryState.variant_id == ProductVariant.id)
        .join(SupplierOffer, SupplierOffer.product_variant_id == ProductVariant.id)
        .where((VariantInventoryState.variant_id.is_(None)) | (VariantInventoryState.own_stock_total <= 0))
    )
    return int(rows.scalar() or 0)


async def _no_stock_count(session: AsyncSession) -> int:
    states = await session.scalars(select(ProductVariant.id))
    total = 0
    for variant_id in states:
        inventory = await session.get(VariantInventoryState, variant_id)
        offers = list(await session.scalars(select(SupplierOffer).where(SupplierOffer.product_variant_id == variant_id)))
        if (inventory is None or inventory.own_stock_total <= 0) and not offers:
            total += 1
    return total


async def _pricing_ready_count(session: AsyncSession) -> int:
    from app.models.enums import StockDecision
    from app.models.pricing import VariantPricingState

    return await _count(session, VariantPricingState, VariantPricingState.final_price_minor.is_not(None), VariantPricingState.stock_decision == StockDecision.ACTIVE)


async def _pricing_review_count(session: AsyncSession) -> int:
    from app.models.enums import StockDecision
    from app.models.pricing import VariantPricingState

    return await _count(session, VariantPricingState, VariantPricingState.stock_decision == StockDecision.REVIEW)


async def _listing_ready_count(session: AsyncSession) -> int:
    return await _count(
        session,
        GenericListingDraft,
        GenericListingDraft.generic_readiness.in_([GenericReadinessStatus.READY, GenericReadinessStatus.APPROVED]),
    )


async def _dry_run_validated_count(session: AsyncSession) -> int:
    return await _count(session, PublicationJob, PublicationJob.status == PublicationJobStatus.DRY_RUN_SUCCESS, PublicationJob.dry_run.is_(True))


def _captured_at_from_preview(preview: dict) -> datetime | None:
    value = preview.get("captured_at")
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
