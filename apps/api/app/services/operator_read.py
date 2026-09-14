import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redis import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.conflict import DataConflict
from app.models.content import GenericListingDraft, ProductContentDraft, ProductContentFacts, ProductImageSet
from app.models.enums import (
    Availability,
    GenericListingStatus,
    GenericReadinessStatus,
    OperationalAlertStatus,
    PublicationJobStatus,
    SourceCollectionJobStatus,
    StockDecision,
    SupplierSnapshotItemStatus,
)
from app.models.one_c import OneCImportRun, VariantInventoryState
from app.models.pricing import VariantPricingState
from app.models.product import Product, ProductVariant
from app.models.publication import MarketplaceListingBinding, OperationalAlert, PublicationAttempt, PublicationJob, PublicationStateHistory
from app.models.source import Source
from app.models.source_collection_job import SourceCollectionJob
from app.models.supplier import Supplier
from app.models.supplier_offer import SupplierOffer
from app.models.supplier_snapshot import SupplierSnapshot, SupplierSnapshotItem


def _value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row(**kwargs: Any) -> dict[str, Any]:
    return {key: _value(value) for key, value in kwargs.items()}


async def count_rows(session: AsyncSession, model, *conditions) -> int:
    statement = select(func.count()).select_from(model)
    for condition in conditions:
        statement = statement.where(condition)
    return int(await session.scalar(statement) or 0)


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    counts = {
        "products": await count_rows(session, Product),
        "variants": await count_rows(session, ProductVariant),
        "ready_listings": await count_rows(session, GenericListingDraft, GenericListingDraft.generic_readiness == GenericReadinessStatus.READY),
        "review_required": await count_rows(session, GenericListingDraft, GenericListingDraft.generic_readiness == GenericReadinessStatus.REVIEW_REQUIRED),
        "approved": await count_rows(session, GenericListingDraft, GenericListingDraft.status == GenericListingStatus.APPROVED),
        "no_stock": await count_rows(session, VariantPricingState, VariantPricingState.stock_decision == StockDecision.OUT_OF_STOCK),
        "pricing_review": await count_rows(session, VariantPricingState, VariantPricingState.stock_decision == StockDecision.REVIEW),
        "supplier_stale": 0,
        "supplier_conflicts": await count_rows(session, SupplierSnapshotItem, SupplierSnapshotItem.item_status == SupplierSnapshotItemStatus.CONFLICT),
        "publication_queued": await count_rows(session, PublicationJob, PublicationJob.status == PublicationJobStatus.QUEUED),
        "publication_blocked": await count_rows(session, PublicationJob, PublicationJob.status == PublicationJobStatus.BLOCKED),
        "publication_failed": await count_rows(session, PublicationJob, PublicationJob.status == PublicationJobStatus.FAILED),
        "dry_run_success": await count_rows(session, PublicationJob, PublicationJob.status == PublicationJobStatus.DRY_RUN_SUCCESS),
        "open_alerts": await count_rows(session, OperationalAlert, OperationalAlert.status == OperationalAlertStatus.OPEN),
    }
    jobs = list(
        await session.scalars(
            select(PublicationJob)
            .where(PublicationJob.status.in_([PublicationJobStatus.BLOCKED, PublicationJobStatus.FAILED]))
            .order_by(PublicationJob.updated_at.desc())
            .limit(8)
        )
    )
    review_items = list(
        await session.scalars(
            select(GenericListingDraft)
            .where(GenericListingDraft.generic_readiness.in_([GenericReadinessStatus.REVIEW_REQUIRED, GenericReadinessStatus.STALE]))
            .order_by(GenericListingDraft.updated_at.desc())
            .limit(8)
        )
    )
    recent_jobs = list(await session.scalars(select(PublicationJob).order_by(PublicationJob.created_at.desc()).limit(8)))
    sources = list(await session.scalars(select(Source).order_by(Source.created_at.desc()).limit(8)))
    return {
        "counts": counts,
        "recent_failures": [_row(id=job.id, status=job.status, error_code=job.error_code, updated_at=job.updated_at) for job in jobs],
        "recent_review_items": [
            _row(id=item.id, variant_id=item.variant_id, title=item.title, readiness=item.generic_readiness, reasons=item.readiness_reasons, updated_at=item.updated_at)
            for item in review_items
        ],
        "recent_publication_jobs": [_row(id=job.id, status=job.status, marketplace=job.marketplace, created_at=job.created_at, error_code=job.error_code) for job in recent_jobs],
        "source_freshness": [_row(id=source.id, name=source.name, type=source.source_type, enabled=source.is_active, updated_at=source.updated_at) for source in sources],
    }


async def product_list(session: AsyncSession, *, search: str | None, limit: int, offset: int) -> dict[str, Any]:
    base = select(ProductVariant, Product).join(Product, Product.id == ProductVariant.product_id).order_by(Product.brand, Product.canonical_name).limit(limit).offset(offset)
    count_statement = select(func.count()).select_from(ProductVariant).join(Product, Product.id == ProductVariant.product_id)
    if search:
        pattern = f"%{search.lower()}%"
        base = base.where(func.lower(Product.brand + " " + Product.canonical_name).like(pattern))
        count_statement = count_statement.where(func.lower(Product.brand + " " + Product.canonical_name).like(pattern))
    rows = (await session.execute(base)).all()
    total = int(await session.scalar(count_statement) or 0)
    items = [
        _row(
            variant_id=variant.id,
            product_id=product.id,
            brand=product.brand,
            model=product.canonical_name,
            model_code=variant.manufacturer_model_code,
            ram_gb=variant.ram_gb,
            storage_gb=variant.storage_gb,
            color=variant.color_normalized,
            condition=variant.condition,
            updated_at=variant.updated_at,
        )
        for variant, product in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def variant_detail(session: AsyncSession, variant_id: uuid.UUID) -> dict[str, Any]:
    variant = await session.get(ProductVariant, variant_id)
    if variant is None:
        raise ValueError("VARIANT_NOT_FOUND")
    product = await session.get(Product, variant.product_id)
    offers = list(await session.scalars(select(SupplierOffer).where(SupplierOffer.product_variant_id == variant_id).order_by(SupplierOffer.updated_at.desc()).limit(20)))
    inventory = await session.get(VariantInventoryState, variant_id)
    pricing = await session.get(VariantPricingState, variant_id)
    facts = await session.scalar(select(ProductContentFacts).where(ProductContentFacts.variant_id == variant_id).order_by(ProductContentFacts.created_at.desc()).limit(1))
    content = await session.scalar(select(ProductContentDraft).where(ProductContentDraft.variant_id == variant_id).order_by(ProductContentDraft.created_at.desc()).limit(1))
    image_set = await session.scalar(select(ProductImageSet).where(ProductImageSet.variant_id == variant_id).order_by(ProductImageSet.created_at.desc()).limit(1))
    listing = await session.scalar(select(GenericListingDraft).where(GenericListingDraft.variant_id == variant_id).order_by(GenericListingDraft.created_at.desc()).limit(1))
    binding = None
    job = None
    if listing is not None:
        binding = await session.scalar(select(MarketplaceListingBinding).where(MarketplaceListingBinding.generic_listing_id == listing.id).order_by(MarketplaceListingBinding.updated_at.desc()).limit(1))
        if binding is not None:
            job = await session.scalar(select(PublicationJob).join_from(PublicationJob, PublicationJob.intent).where(PublicationJob.intent.has(listing_id=listing.id)).order_by(PublicationJob.created_at.desc()).limit(1))
    audit = list(await session.scalars(select(AuditLog).where(AuditLog.entity_id.in_([variant_id, listing.id if listing else variant_id])).order_by(AuditLog.created_at.desc()).limit(20)))
    return {
        "identity": _row(
            product_id=product.id,
            variant_id=variant.id,
            brand=product.brand,
            model=product.canonical_name,
            model_code=variant.manufacturer_model_code,
            ram_gb=variant.ram_gb,
            storage_gb=variant.storage_gb,
            color_raw=variant.color_raw,
            color=variant.color_normalized,
            region=variant.region_code,
            condition=variant.condition,
            canonical_key=variant.canonical_key,
        ),
        "supplier": [_row(id=offer.id, supplier_id=offer.supplier_id, price_minor=offer.price_minor, availability=offer.availability, missing_count=offer.consecutive_missing_count, updated_at=offer.updated_at) for offer in offers],
        "inventory": _row(own_stock_total=inventory.own_stock_total, own_cost_minor=inventory.own_cost_minor, source_updated_at=inventory.source_updated_at) if inventory else None,
        "pricing": _row(final_price_minor=pricing.final_price_minor, hard_floor_minor=pricing.hard_floor_minor, stock_decision=pricing.stock_decision, fulfillment_source=pricing.fulfillment_source, calculated_at=pricing.calculated_at) if pricing else None,
        "facts": _row(completeness_score=facts.completeness_score, has_conflicts=facts.has_conflicts, requires_review=facts.requires_review, fact_hash=facts.fact_hash) if facts else None,
        "content": _row(status=content.status, title=content.title, validation_status=content.validation_status, content_hash=content.content_hash) if content else None,
        "images": _row(status=image_set.status, content_hash=image_set.content_hash, approved_at=image_set.approved_at) if image_set else None,
        "listing": _row(id=listing.id, status=listing.status, readiness=listing.generic_readiness, price_minor=listing.price_minor, reasons=listing.readiness_reasons, content_hash=listing.content_hash) if listing else None,
        "publication": {
            "binding": _row(id=binding.id, status=binding.status, sync_state=binding.sync_state, external_listing_id=binding.external_listing_id, last_error_code=binding.last_error_code) if binding else None,
            "latest_job": _row(id=job.id, status=job.status, error_code=job.error_code, dry_run=job.dry_run, payload_hash=job.payload_hash) if job else None,
            "avito_real_mutation": "DISABLED_CONTRACT_INCOMPLETE",
        },
        "audit": [_row(id=item.id, action=item.action, actor_type=item.actor_type, actor_id=item.actor_id, created_at=item.created_at) for item in audit],
    }


async def pricing_list(session: AsyncSession, *, limit: int, offset: int) -> dict[str, Any]:
    rows = (await session.execute(select(VariantPricingState, ProductVariant, Product).join(ProductVariant, ProductVariant.id == VariantPricingState.product_variant_id).join(Product, Product.id == ProductVariant.product_id).order_by(VariantPricingState.calculated_at.desc()).limit(limit).offset(offset))).all()
    total = await count_rows(session, VariantPricingState)
    return {"items": [_row(variant_id=variant.id, product=f"{product.brand} {product.canonical_name}", own_stock=None, own_cost=None, supplier_cost=state.base_cost_minor, selected_source=state.fulfillment_source, hard_floor=state.hard_floor_minor, final_price=state.final_price_minor, profit=(state.final_price_minor - state.base_cost_minor) if state.final_price_minor and state.base_cost_minor else None, status=state.stock_decision, last_recalculated=state.calculated_at) for state, variant, product in rows], "total": total, "limit": limit, "offset": offset}


async def inventory_list(session: AsyncSession, *, limit: int, offset: int) -> dict[str, Any]:
    rows = (await session.execute(select(VariantInventoryState, ProductVariant, Product).join(ProductVariant, ProductVariant.id == VariantInventoryState.variant_id).join(Product, Product.id == ProductVariant.product_id).order_by(VariantInventoryState.source_updated_at.desc()).limit(limit).offset(offset))).all()
    total = await count_rows(session, VariantInventoryState)
    return {"items": [_row(variant_id=variant.id, product=f"{product.brand} {product.canonical_name}", own_stock=state.own_stock_total, own_cost=state.own_cost_minor, source_updated_at=state.source_updated_at, stale=False) for state, variant, product in rows], "total": total, "limit": limit, "offset": offset}


async def supplier_list(session: AsyncSession, *, limit: int, offset: int) -> dict[str, Any]:
    suppliers = list(await session.scalars(select(Supplier).order_by(Supplier.name).limit(limit).offset(offset)))
    total = await count_rows(session, Supplier)
    items = []
    for supplier in suppliers:
        items.append(_row(id=supplier.id, name=supplier.name, code=supplier.code, offer_count=await count_rows(session, SupplierOffer, SupplierOffer.supplier_id == supplier.id), in_stock_count=await count_rows(session, SupplierOffer, SupplierOffer.supplier_id == supplier.id, SupplierOffer.availability == Availability.IN_STOCK), errors=0, updated_at=supplier.updated_at))
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def source_health(session: AsyncSession, *, limit: int, offset: int) -> dict[str, Any]:
    sources = list(await session.scalars(select(Source).order_by(Source.created_at.desc()).limit(limit).offset(offset)))
    total = await count_rows(session, Source)
    items = []
    for source in sources:
        job = await session.scalar(select(SourceCollectionJob).where(SourceCollectionJob.source_id == source.id).order_by(SourceCollectionJob.created_at.desc()).limit(1))
        items.append(_row(id=source.id, name=source.name, type=source.source_type, enabled=source.is_active, last_run=job.created_at if job else None, last_success=job.finished_at if job and job.status == SourceCollectionJobStatus.SUCCEEDED else None, last_failure=job.finished_at if job and job.status == SourceCollectionJobStatus.FAILED else None, status=job.status if job else None, error_summary=job.error_message if job else None))
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def publication_jobs(session: AsyncSession, *, limit: int, offset: int, status_filter: str | None) -> dict[str, Any]:
    statement = select(PublicationJob).order_by(PublicationJob.created_at.desc()).limit(limit).offset(offset)
    count_statement = select(func.count()).select_from(PublicationJob)
    if status_filter:
        statement = statement.where(PublicationJob.status == status_filter)
        count_statement = count_statement.where(PublicationJob.status == status_filter)
    jobs = list(await session.scalars(statement))
    total = int(await session.scalar(count_statement) or 0)
    return {"items": [_row(id=job.id, intent_id=job.intent_id, marketplace=job.marketplace, operation=job.job_type, status=job.status, attempts=job.attempt_count, created_at=job.created_at, updated_at=job.updated_at, error_code=job.error_code) for job in jobs], "total": total, "limit": limit, "offset": offset}


async def publication_job_detail(session: AsyncSession, job_id: uuid.UUID) -> dict[str, Any]:
    job = await session.get(PublicationJob, job_id)
    if job is None:
        raise ValueError("PUBLICATION_JOB_NOT_FOUND")
    attempts = list(await session.scalars(select(PublicationAttempt).where(PublicationAttempt.job_id == job.id).order_by(PublicationAttempt.attempt_number)))
    history = list(await session.scalars(select(PublicationStateHistory).where(PublicationStateHistory.entity_id == job.id).order_by(PublicationStateHistory.created_at)))
    return {
        "job": _row(id=job.id, intent_id=job.intent_id, status=job.status, operation=job.job_type, marketplace=job.marketplace, attempts=job.attempt_count, payload_hash=job.payload_hash, prepared_payload=job.prepared_payload, error_code=job.error_code, error_message=job.error_message, created_at=job.created_at, updated_at=job.updated_at),
        "attempts": [_row(id=item.id, attempt_number=item.attempt_number, status=item.status, error_code=item.error_code, started_at=item.started_at, finished_at=item.finished_at) for item in attempts],
        "state_history": [_row(id=item.id, event_type=item.event_type, old_status=item.old_status, new_status=item.new_status, created_at=item.created_at, metadata=item.metadata_json) for item in history],
        "avito_real_mutation": "DISABLED_CONTRACT_INCOMPLETE",
    }


async def audit_page(session: AsyncSession, *, limit: int, offset: int, action: str | None = None, entity_type: str | None = None) -> dict[str, Any]:
    statement = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    count_statement = select(func.count()).select_from(AuditLog)
    if action:
        statement = statement.where(AuditLog.action == action)
        count_statement = count_statement.where(AuditLog.action == action)
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type)
        count_statement = count_statement.where(AuditLog.entity_type == entity_type)
    rows = list(await session.scalars(statement))
    total = int(await session.scalar(count_statement) or 0)
    return {"items": [_row(id=item.id, timestamp=item.created_at, actor=f"{item.actor_type}:{item.actor_id or 'system'}", action=item.action, entity=item.entity_type, entity_id=item.entity_id, summary=item.new_value or item.old_value) for item in rows], "total": total, "limit": limit, "offset": offset}


async def alert_page(session: AsyncSession, *, limit: int, offset: int, status_filter: str | None = None) -> dict[str, Any]:
    statement = select(OperationalAlert).order_by(OperationalAlert.created_at.desc()).limit(limit).offset(offset)
    count_statement = select(func.count()).select_from(OperationalAlert)
    if status_filter:
        statement = statement.where(OperationalAlert.status == status_filter)
        count_statement = count_statement.where(OperationalAlert.status == status_filter)
    rows = list(await session.scalars(statement))
    total = int(await session.scalar(count_statement) or 0)
    return {"items": [_row(id=item.id, severity=item.severity, type=item.type, entity_type=item.entity_type, entity_id=item.entity_id, message=item.message, status=item.status, created_at=item.created_at, resolved_at=item.resolved_at) for item in rows], "total": total, "limit": limit, "offset": offset}


async def update_alert_status(session: AsyncSession, alert_id: uuid.UUID, status_value: OperationalAlertStatus) -> OperationalAlert:
    alert = await session.get(OperationalAlert, alert_id)
    if alert is None:
        raise ValueError("ALERT_NOT_FOUND")
    alert.status = status_value
    if status_value == OperationalAlertStatus.RESOLVED:
        alert.resolved_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(alert)
    return alert


async def settings_read() -> dict[str, Any]:
    settings = get_settings()
    return {
        "app_env": settings.app_env,
        "auto_prepare_publication": settings.auto_prepare_publication,
        "publication_max_attempts": settings.publication_max_attempts,
        "publication_retry_base_seconds": settings.publication_retry_base_seconds,
        "telegram_control_configured": bool(settings.telegram_operator_id_set),
        "avito_live_enabled": False,
        "backup_configured": bool(settings.backup_dir),
        "cookie_secure": settings.cookie_secure,
        "session_ttl_seconds": settings.session_ttl_seconds,
    }


async def system_health(session: AsyncSession) -> dict[str, Any]:
    database = "ok"
    redis_status = "ok"
    try:
        await session.execute(text("select 1"))
    except Exception:
        database = "error"
    try:
        Redis.from_url(get_settings().redis_url).ping()
    except Exception:
        redis_status = "error"
    return {
        "api": "ok",
        "database": database,
        "redis": redis_status,
        "worker": "configured",
        "scheduler": "configured",
        "avito_real_mutation": "DISABLED_CONTRACT_INCOMPLETE",
        "timestamp": datetime.now(UTC),
    }


async def backup_smoke(session: AsyncSession) -> dict[str, Any]:
    backup_dir = Path(get_settings().backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    path = backup_dir / f"backup-smoke-{backup_id}.json"
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "database_reachable": True,
        "products": await count_rows(session, Product),
        "variants": await count_rows(session, ProductVariant),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"status": "PASS", "backup_id": backup_id, "path": str(path), "size_bytes": path.stat().st_size}
