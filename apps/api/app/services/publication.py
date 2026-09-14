import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.content import GenericListingDraft, ProductContentDraft, ProductImageSet
from app.models.enums import (
    ContentDraftStatus,
    GenericReadinessStatus,
    ImageSetStatus,
    ListingSyncState,
    Marketplace,
    MarketplaceBindingStatus,
    OperationalAlertSeverity,
    OperationalAlertStatus,
    PublicationErrorCode,
    PublicationIntentStatus,
    PublicationIntentType,
    PublicationJobStatus,
    ReconciliationAction,
)
from app.models.pricing import VariantPricingState
from app.models.publication import (
    MarketplaceListingBinding,
    OperationalAlert,
    PublicationAttempt,
    PublicationIntent,
    PublicationJob,
    PublicationStateHistory,
)
from app.services.content import stable_hash

AVITO_ADAPTER_VERSION = "avito-disabled-v1"
TERMINAL_JOB_STATUSES = {
    PublicationJobStatus.DRY_RUN_SUCCESS,
    PublicationJobStatus.BLOCKED,
    PublicationJobStatus.FAILED,
    PublicationJobStatus.CANCELLED,
    PublicationJobStatus.SUCCEEDED,
}
CANCELLABLE_JOB_STATUSES = {PublicationJobStatus.PENDING, PublicationJobStatus.QUEUED, PublicationJobStatus.RETRY_WAIT}
RETRYABLE_JOB_STATUSES = {PublicationJobStatus.FAILED, PublicationJobStatus.RETRY_WAIT}


def utc_now() -> datetime:
    return datetime.now(UTC)


def safe_error(message: str | None) -> str | None:
    if message is None:
        return None
    value = message.replace("\n", " ").strip()
    for token in ("authorization", "cookie", "access_token", "refresh_token", "password", "session"):
        value = value.replace(token, "[redacted]")
    return value[:512]


def listing_snapshot(listing: GenericListingDraft) -> dict:
    return {
        "listing_id": str(listing.id),
        "variant_id": str(listing.variant_id),
        "content_hash": listing.content_hash,
        "content_draft_id": str(listing.content_draft_id) if listing.content_draft_id else None,
        "image_set_id": str(listing.image_set_id) if listing.image_set_id else None,
        "price_minor": listing.price_minor,
        "stock_decision": listing.stock_decision,
        "fulfillment_source": listing.fulfillment_source,
        "generic_readiness": listing.generic_readiness.value,
        "status": listing.status.value,
    }


async def current_listing_context(session: AsyncSession, listing_id: uuid.UUID) -> tuple[GenericListingDraft, ProductContentDraft | None, ProductImageSet | None, VariantPricingState | None]:
    listing = await session.get(GenericListingDraft, listing_id)
    if listing is None:
        raise ValueError("GenericListingDraft not found")
    content = await session.get(ProductContentDraft, listing.content_draft_id) if listing.content_draft_id else None
    image_set = await session.get(ProductImageSet, listing.image_set_id) if listing.image_set_id else None
    pricing = await session.get(VariantPricingState, listing.variant_id)
    return listing, content, image_set, pricing


async def get_or_create_binding(session: AsyncSession, listing: GenericListingDraft, marketplace: Marketplace) -> MarketplaceListingBinding:
    binding = await session.scalar(
        select(MarketplaceListingBinding).where(
            MarketplaceListingBinding.marketplace == marketplace,
            MarketplaceListingBinding.generic_listing_id == listing.id,
        )
    )
    if binding:
        return binding
    binding = MarketplaceListingBinding(
        variant_id=listing.variant_id,
        generic_listing_id=listing.id,
        marketplace=marketplace,
        external_listing_id=None,
        status=MarketplaceBindingStatus.PREPARED,
        sync_state=ListingSyncState.READY_FOR_INTENT,
        adapter_version=AVITO_ADAPTER_VERSION if marketplace == Marketplace.AVITO else "unknown",
    )
    session.add(binding)
    await session.flush()
    add_history(session, "MarketplaceListingBinding", binding.id, "BINDING_RECONCILED", None, binding.status.value)
    return binding


async def create_publication_intent(
    session: AsyncSession,
    listing_id: uuid.UUID,
    *,
    marketplace: Marketplace = Marketplace.AVITO,
    intent_type: PublicationIntentType = PublicationIntentType.CREATE,
    requested_by: str = "operator",
    reason: str | None = None,
    dry_run: bool = True,
) -> tuple[PublicationIntent, PublicationJob, bool]:
    listing, content, image_set, pricing = await current_listing_context(session, listing_id)
    binding = await get_or_create_binding(session, listing, marketplace)
    snap = listing_snapshot(listing)
    approved_snapshot_hash = stable_hash(snap)
    pricing_hash = stable_hash({"price_minor": pricing.final_price_minor, "stock_decision": pricing.stock_decision.value, "reason_codes": sorted(pricing.reason_codes)}) if pricing else None
    image_hash = image_set.content_hash if image_set else None
    content_hash = content.content_hash if content else None
    idempotency_key = stable_hash({"listing": str(listing_id), "marketplace": marketplace.value, "intent_type": intent_type.value, "snapshot": approved_snapshot_hash})
    existing = await session.scalar(select(PublicationIntent).where(PublicationIntent.idempotency_key == idempotency_key))
    if existing:
        job = await session.scalar(select(PublicationJob).where(PublicationJob.intent_id == existing.id))
        return existing, job, False
    intent = PublicationIntent(
        listing_id=listing.id,
        binding_id=binding.id,
        marketplace=marketplace,
        intent_type=intent_type,
        status=PublicationIntentStatus.PENDING,
        requested_by=requested_by,
        approved_snapshot_hash=approved_snapshot_hash,
        listing_hash=listing.content_hash,
        pricing_hash=pricing_hash,
        content_hash=content_hash,
        image_set_hash=image_hash,
        reason=reason,
        metadata_json={"dry_run": dry_run, "snapshot": snap},
        idempotency_key=idempotency_key,
    )
    session.add(intent)
    await session.flush()
    add_history(session, "PublicationIntent", intent.id, "INTENT_CREATED", None, intent.status.value)
    session.add(AuditLog(entity_type="PublicationIntent", entity_id=intent.id, action="PUBLICATION_INTENT_CREATED", old_value=None, new_value={"listing_id": str(listing.id), "intent_type": intent_type.value}, actor_type="USER", actor_id=requested_by))
    job = PublicationJob(
        intent_id=intent.id,
        marketplace=marketplace,
        job_type=intent_type,
        status=PublicationJobStatus.PENDING,
        max_attempts=get_settings().publication_max_attempts,
        idempotency_key=f"job:{idempotency_key}",
        dry_run=dry_run,
    )
    session.add(job)
    await session.flush()
    intent.status = PublicationIntentStatus.JOB_CREATED
    binding.sync_state = ListingSyncState.INTENT_PENDING
    add_history(session, "PublicationJob", job.id, "JOB_CREATED", None, job.status.value)
    session.add(AuditLog(entity_type="PublicationJob", entity_id=job.id, action="PUBLICATION_JOB_CREATED", old_value=None, new_value={"intent_id": str(intent.id)}, actor_type="SYSTEM"))
    await session.commit()
    await session.refresh(intent)
    await session.refresh(job)
    return intent, job, True


async def enqueue_publication_job(session: AsyncSession, job: PublicationJob, queue) -> PublicationJob:
    if job.status in TERMINAL_JOB_STATUSES:
        raise ValueError(PublicationErrorCode.JOB_ALREADY_TERMINAL.value)
    queue.enqueue_job(str(job.id))
    old = job.status.value
    job.status = PublicationJobStatus.QUEUED
    job.next_attempt_at = utc_now()
    add_history(session, "PublicationJob", job.id, "QUEUED", old, job.status.value)
    await session.commit()
    await session.refresh(job)
    return job


async def process_publication_job(session: AsyncSession, job_id: uuid.UUID, *, execute_real: bool = False) -> PublicationJob:
    job = await session.scalar(select(PublicationJob).where(PublicationJob.id == job_id).with_for_update())
    if job is None:
        raise ValueError("PublicationJob not found")
    if job.status in TERMINAL_JOB_STATUSES:
        return job
    intent = await session.get(PublicationIntent, job.intent_id)
    listing, content, image_set, pricing = await current_listing_context(session, intent.listing_id)
    binding = await session.get(MarketplaceListingBinding, intent.binding_id) if intent.binding_id else await get_or_create_binding(session, listing, intent.marketplace)
    old_status = job.status.value
    job.status = PublicationJobStatus.RUNNING
    job.started_at = utc_now()
    job.attempt_count += 1
    add_history(session, "PublicationJob", job.id, "RUNNING", old_status, job.status.value)
    session.add(AuditLog(entity_type="PublicationJob", entity_id=job.id, action="PUBLICATION_JOB_STARTED", old_value={"status": old_status}, new_value={"attempt": job.attempt_count}, actor_type="SYSTEM"))
    await session.flush()

    attempt = PublicationAttempt(
        job_id=job.id,
        attempt_number=job.attempt_count,
        status=PublicationJobStatus.RUNNING,
        adapter="AVITO",
        adapter_version=AVITO_ADAPTER_VERSION,
        request_summary={"listing_id": str(listing.id), "operation": job.job_type.value},
        dry_run=job.dry_run,
    )
    session.add(attempt)
    await session.flush()

    error = validate_intent_context(intent, listing, content, image_set, pricing)
    if error:
        return await block_job(session, job, attempt, binding, PublicationErrorCode.STALE_INPUT if error == "STALE_INPUT" else PublicationErrorCode.LISTING_NOT_READY, error, "PUBLICATION_STALE")
    if execute_real or not job.dry_run:
        return await block_job(session, job, attempt, binding, PublicationErrorCode.AVITO_CONTRACT_INCOMPLETE, "AVITO_CONTRACT_INCOMPLETE", "BLOCKED_CONTRACT")

    payload = prepare_internal_payload(listing, content, image_set, pricing, job.job_type)
    payload_hash = stable_hash(payload)
    job.prepared_payload = payload
    job.payload_hash = payload_hash
    job.status = PublicationJobStatus.DRY_RUN_SUCCESS
    job.finished_at = utc_now()
    job.error_code = None
    job.error_message = None
    attempt.status = PublicationJobStatus.DRY_RUN_SUCCESS
    attempt.finished_at = job.finished_at
    attempt.request_summary = {"payload_hash": payload_hash, "operation": job.job_type.value, "dry_run": True}
    attempt.response_summary = {"status": "DRY_RUN_SUCCESS", "network_mutation": False}
    binding.status = MarketplaceBindingStatus.PREPARED
    binding.sync_state = ListingSyncState.DRY_RUN_OK
    binding.last_known_price_minor = listing.price_minor
    binding.last_known_stock_state = listing.stock_decision
    binding.last_content_hash = content.content_hash if content else None
    binding.last_image_set_hash = image_set.content_hash if image_set else None
    binding.last_payload_hash = payload_hash
    binding.last_sync_at = job.finished_at
    add_history(session, "PublicationJob", job.id, "DRY_RUN_SUCCESS", PublicationJobStatus.RUNNING.value, job.status.value, {"payload_hash": payload_hash})
    session.add(AuditLog(entity_type="PublicationJob", entity_id=job.id, action="PUBLICATION_DRY_RUN_SUCCESS", old_value=None, new_value={"payload_hash": payload_hash}, actor_type="SYSTEM"))
    await resolve_alert(session, f"publication:{job.id}")
    await session.commit()
    await session.refresh(job)
    return job


def validate_intent_context(intent: PublicationIntent, listing: GenericListingDraft, content: ProductContentDraft | None, image_set: ProductImageSet | None, pricing: VariantPricingState | None) -> str | None:
    if intent.approved_snapshot_hash != stable_hash(listing_snapshot(listing)):
        return "STALE_INPUT"
    if listing.generic_readiness != GenericReadinessStatus.APPROVED:
        return "LISTING_NOT_READY"
    if content is None or content.status != ContentDraftStatus.APPROVED:
        return "CONTENT_NOT_APPROVED"
    if image_set is None or image_set.status != ImageSetStatus.APPROVED:
        return "IMAGES_NOT_APPROVED"
    if pricing is None or pricing.final_price_minor is None:
        return "PRICING_NOT_READY"
    return None


def prepare_internal_payload(listing: GenericListingDraft, content: ProductContentDraft | None, image_set: ProductImageSet | None, pricing: VariantPricingState | None, operation: PublicationIntentType) -> dict:
    return {
        "marketplace": Marketplace.AVITO.value,
        "operation": operation.value,
        "generic_listing_id": str(listing.id),
        "title": listing.title,
        "description": listing.description,
        "price_minor": listing.price_minor,
        "images": [str(image_set.id)] if image_set else [],
        "internal_category": listing.generic_category.value,
        "attributes": listing.generic_attributes,
        "contract_status": "DISABLED_CONTRACT_INCOMPLETE",
        "not_avito_compatible_payload": True,
    }


async def block_job(session: AsyncSession, job: PublicationJob, attempt: PublicationAttempt, binding: MarketplaceListingBinding, code: PublicationErrorCode, message: str, event: str) -> PublicationJob:
    now = utc_now()
    job.status = PublicationJobStatus.BLOCKED
    job.finished_at = now
    job.error_code = code.value
    job.error_message = safe_error(message)
    attempt.status = PublicationJobStatus.BLOCKED
    attempt.finished_at = now
    attempt.error_code = code.value
    attempt.error_message = safe_error(message)
    attempt.response_summary = {"status": "BLOCKED", "error_code": code.value, "network_mutation": False}
    binding.status = MarketplaceBindingStatus.BLOCKED
    binding.sync_state = ListingSyncState.BLOCKED_EXTERNAL if code == PublicationErrorCode.AVITO_CONTRACT_INCOMPLETE else ListingSyncState.STALE
    binding.last_error_at = now
    binding.last_error_code = code.value
    binding.last_error_message = safe_error(message)
    add_history(session, "PublicationJob", job.id, event, PublicationJobStatus.RUNNING.value, job.status.value, {"error_code": code.value})
    session.add(AuditLog(entity_type="PublicationJob", entity_id=job.id, action="PUBLICATION_BLOCKED" if code == PublicationErrorCode.AVITO_CONTRACT_INCOMPLETE else "PUBLICATION_STALE", old_value=None, new_value={"error_code": code.value}, actor_type="SYSTEM"))
    if code != PublicationErrorCode.AVITO_CONTRACT_INCOMPLETE:
        await open_alert(session, type=code.value, severity=OperationalAlertSeverity.ERROR, entity_type="PublicationJob", entity_id=job.id, message=message)
    await session.commit()
    await session.refresh(job)
    return job


async def cancel_publication_job(session: AsyncSession, job_id: uuid.UUID, *, requested_by: str = "operator") -> PublicationJob:
    job = await session.get(PublicationJob, job_id)
    if job is None:
        raise ValueError("PublicationJob not found")
    if job.status not in CANCELLABLE_JOB_STATUSES:
        raise ValueError(PublicationErrorCode.JOB_ALREADY_TERMINAL.value)
    old = job.status.value
    job.status = PublicationJobStatus.CANCELLED
    job.finished_at = utc_now()
    job.error_code = PublicationErrorCode.JOB_CANCELLED.value
    add_history(session, "PublicationJob", job.id, "CANCELLED", old, job.status.value)
    session.add(AuditLog(entity_type="PublicationJob", entity_id=job.id, action="PUBLICATION_CANCELLED", old_value={"status": old}, new_value={"requested_by": requested_by}, actor_type="USER", actor_id=requested_by))
    await session.commit()
    await session.refresh(job)
    return job


async def retry_publication_job(session: AsyncSession, job_id: uuid.UUID, *, requested_by: str = "operator") -> PublicationJob:
    old = await session.get(PublicationJob, job_id)
    if old is None:
        raise ValueError("PublicationJob not found")
    if old.status not in RETRYABLE_JOB_STATUSES or old.error_code in {PublicationErrorCode.AVITO_CONTRACT_INCOMPLETE.value, PublicationErrorCode.STALE_INPUT.value, PublicationErrorCode.LISTING_NOT_READY.value}:
        raise ValueError(PublicationErrorCode.UNSUPPORTED_OPERATION.value)
    retry = PublicationJob(
        intent_id=old.intent_id,
        marketplace=old.marketplace,
        job_type=old.job_type,
        status=PublicationJobStatus.PENDING,
        max_attempts=old.max_attempts,
        idempotency_key=f"retry:{old.id}:{old.attempt_count + 1}",
        dry_run=old.dry_run,
    )
    session.add(retry)
    await session.flush()
    add_history(session, "PublicationJob", retry.id, "RETRY_SCHEDULED", None, retry.status.value)
    session.add(AuditLog(entity_type="PublicationJob", entity_id=retry.id, action="PUBLICATION_RETRY_SCHEDULED", old_value={"job_id": str(old.id)}, new_value={"requested_by": requested_by}, actor_type="USER", actor_id=requested_by))
    await session.commit()
    await session.refresh(retry)
    return retry


async def reconcile_listing(session: AsyncSession, listing_id: uuid.UUID, *, marketplace: Marketplace = Marketplace.AVITO) -> dict:
    listing, content, image_set, pricing = await current_listing_context(session, listing_id)
    binding = await get_or_create_binding(session, listing, marketplace)
    reasons: list[str] = []
    actions: list[ReconciliationAction] = []
    if listing.generic_readiness not in {GenericReadinessStatus.READY, GenericReadinessStatus.APPROVED}:
        actions.append(ReconciliationAction.REVIEW_REQUIRED)
    elif binding.last_payload_hash is None:
        actions.append(ReconciliationAction.CREATE_REQUIRED)
    else:
        if content and binding.last_content_hash and content.content_hash != binding.last_content_hash:
            actions.append(ReconciliationAction.CONTENT_UPDATE_REQUIRED)
        if image_set and binding.last_image_set_hash and image_set.content_hash != binding.last_image_set_hash:
            actions.append(ReconciliationAction.CONTENT_UPDATE_REQUIRED)
        if pricing and binding.last_known_price_minor != pricing.final_price_minor:
            actions.append(ReconciliationAction.PRICE_UPDATE_REQUIRED)
        if pricing and binding.last_known_stock_state != pricing.stock_decision.value:
            actions.append(ReconciliationAction.STOCK_UPDATE_REQUIRED)
            if pricing.stock_decision.value != "ACTIVE":
                actions.append(ReconciliationAction.PAUSE_REQUIRED)
            else:
                actions.append(ReconciliationAction.RESUME_REQUIRED)
    if len(set(actions)) > 1 and ReconciliationAction.CREATE_REQUIRED not in actions:
        result = ReconciliationAction.MULTIPLE_CHANGES
    elif actions:
        result = actions[0]
    else:
        result = ReconciliationAction.NO_ACTION
    if result != ReconciliationAction.NO_ACTION and binding.last_payload_hash is not None:
        binding.status = MarketplaceBindingStatus.STALE
        binding.sync_state = ListingSyncState.STALE
    add_history(session, "MarketplaceListingBinding", binding.id, "BINDING_RECONCILED", None, binding.sync_state.value, {"action": result.value})
    await session.commit()
    return {"listing_id": listing.id, "binding_id": binding.id, "action": result.value, "reasons": reasons, "sync_state": binding.sync_state.value}


async def control_overview(session: AsyncSession) -> dict:
    return {
        "generic_ready": await count_listing(session, GenericReadinessStatus.READY),
        "review_required": await count_listing(session, GenericReadinessStatus.REVIEW_REQUIRED),
        "not_ready": await count_listing(session, GenericReadinessStatus.NOT_READY),
        "approved": await count_listing(session, GenericReadinessStatus.APPROVED),
        "publication_intent_pending": await session.scalar(select(func.count()).select_from(PublicationIntent).where(PublicationIntent.status == PublicationIntentStatus.PENDING)),
        "jobs_queued": await count_job(session, PublicationJobStatus.QUEUED),
        "jobs_retrying": await count_job(session, PublicationJobStatus.RETRY_WAIT),
        "jobs_blocked": await count_job(session, PublicationJobStatus.BLOCKED),
        "jobs_failed": await count_job(session, PublicationJobStatus.FAILED),
        "dry_run_success": await count_job(session, PublicationJobStatus.DRY_RUN_SUCCESS),
        "stale_bindings": await session.scalar(select(func.count()).select_from(MarketplaceListingBinding).where(MarketplaceListingBinding.status == MarketplaceBindingStatus.STALE)),
        "open_alerts": await session.scalar(select(func.count()).select_from(OperationalAlert).where(OperationalAlert.status == OperationalAlertStatus.OPEN)),
    }


async def count_listing(session: AsyncSession, status: GenericReadinessStatus) -> int:
    return await session.scalar(select(func.count()).select_from(GenericListingDraft).where(GenericListingDraft.generic_readiness == status))


async def count_job(session: AsyncSession, status: PublicationJobStatus) -> int:
    return await session.scalar(select(func.count()).select_from(PublicationJob).where(PublicationJob.status == status))


async def review_queue(session: AsyncSession, *, limit: int = 20) -> list[dict]:
    listings = list(
        await session.scalars(
            select(GenericListingDraft)
            .where(GenericListingDraft.generic_readiness.in_([GenericReadinessStatus.REVIEW_REQUIRED, GenericReadinessStatus.NOT_READY, GenericReadinessStatus.STALE]))
            .order_by(GenericListingDraft.updated_at.desc())
            .limit(min(limit, 100))
        )
    )
    return [
        {
            "listing_id": listing.id,
            "variant_id": listing.variant_id,
            "title": listing.title,
            "reason": listing.readiness_reasons[0] if listing.readiness_reasons else None,
            "generic_readiness": listing.generic_readiness.value,
            "price_minor": listing.price_minor,
            "stock_source": listing.fulfillment_source,
        }
        for listing in listings
    ]


async def open_alert(session: AsyncSession, *, type: str, severity: OperationalAlertSeverity, entity_type: str, entity_id: uuid.UUID, message: str, metadata: dict | None = None) -> OperationalAlert:
    dedupe_key = f"{type}:{entity_type}:{entity_id}"
    existing = await session.scalar(select(OperationalAlert).where(OperationalAlert.dedupe_key == dedupe_key, OperationalAlert.status == OperationalAlertStatus.OPEN))
    if existing:
        return existing
    alert = OperationalAlert(type=type, severity=severity, entity_type=entity_type, entity_id=entity_id, status=OperationalAlertStatus.OPEN, dedupe_key=dedupe_key, message=safe_error(message) or type, metadata_json=metadata or {})
    session.add(alert)
    await session.flush()
    add_history(session, "OperationalAlert", alert.id, "ALERT_OPENED", None, alert.status.value)
    session.add(AuditLog(entity_type="OperationalAlert", entity_id=alert.id, action="ALERT_OPENED", old_value=None, new_value={"type": type, "severity": severity.value}, actor_type="SYSTEM"))
    return alert


async def resolve_alert(session: AsyncSession, dedupe_key: str) -> None:
    alert = await session.scalar(select(OperationalAlert).where(OperationalAlert.dedupe_key == dedupe_key, OperationalAlert.status == OperationalAlertStatus.OPEN))
    if not alert:
        return
    alert.status = OperationalAlertStatus.RESOLVED
    alert.resolved_at = utc_now()
    add_history(session, "OperationalAlert", alert.id, "ALERT_RESOLVED", OperationalAlertStatus.OPEN.value, alert.status.value)
    session.add(AuditLog(entity_type="OperationalAlert", entity_id=alert.id, action="ALERT_RESOLVED", old_value=None, new_value={}, actor_type="SYSTEM"))


def add_history(session: AsyncSession, entity_type: str, entity_id: uuid.UUID, event_type: str, old_status: str | None, new_status: str | None, metadata: dict | None = None) -> None:
    session.add(PublicationStateHistory(entity_type=entity_type, entity_id=entity_id, event_type=event_type, old_status=old_status, new_status=new_status, metadata_json=metadata or {}))


async def auto_prepare_ready_listings(session: AsyncSession, *, limit: int = 100) -> dict:
    if not get_settings().auto_prepare_publication:
        return {"processed": 0, "created": 0, "updated": 0, "unchanged": 0, "review_required": 0, "failed": 0, "skipped": 0}
    listings = list(await session.scalars(select(GenericListingDraft).where(GenericListingDraft.generic_readiness == GenericReadinessStatus.APPROVED).limit(min(limit, 500))))
    result = {"processed": 0, "created": 0, "updated": 0, "unchanged": 0, "review_required": 0, "failed": 0, "skipped": 0}
    for listing in listings:
        _, _, created = await create_publication_intent(session, listing.id, requested_by="SYSTEM_AUTO_PREPARE")
        result["processed"] += 1
        result["created" if created else "unchanged"] += 1
    return result
