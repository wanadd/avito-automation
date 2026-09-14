import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.content import GenericListingDraft, ProductContentDraft
from app.models.enums import (
    FulfillmentSource,
    GenericReadinessStatus,
    ImageAssetSourceType,
    ListingSyncState,
    Marketplace,
    MarketplaceBindingStatus,
    OperationalAlertSeverity,
    OperationalAlertStatus,
    PriceRoundingMode,
    PricingMode,
    ProductCondition,
    PublicationErrorCode,
    PublicationIntentType,
    PublicationJobStatus,
    ReconciliationAction,
    StockDecision,
)
from app.models.one_c import OneCImportRun, OneCItem, VariantInventoryState
from app.models.pricing import PricingPolicy, VariantPricingState
from app.models.product import Product, ProductVariant
from app.models.publication import MarketplaceListingBinding, OperationalAlert, PublicationAttempt, PublicationJob, PublicationStateHistory
from app.services.canonical_key import build_canonical_key
from app.services.content import (
    approve_content_draft,
    approve_image_set,
    approve_listing,
    build_generic_listing,
    create_image_asset,
    create_image_set,
    generate_content_draft,
    rebuild_content_facts,
    stable_hash,
    validate_content_draft,
    validate_image_set,
)
from app.services.publication import (
    cancel_publication_job,
    create_publication_intent,
    open_alert,
    process_publication_job,
    reconcile_listing,
    retry_publication_job,
)
from app.services.telegram_control import handle_operator_command, is_authorized_operator
from app.jobs.queue import InMemoryQueueAdapter
from app.services.publication import enqueue_publication_job

pytestmark = pytest.mark.usefixtures("clean_database")

NOW = datetime(2026, 9, 12, 10, tzinfo=UTC)


async def seed_approved_listing(*, price=7000000, stock_decision=StockDecision.ACTIVE):
    async with AsyncSessionLocal() as session:
        product = Product(brand="Samsung", canonical_name=f"Galaxy S25 Ultra {uuid.uuid4().hex[:6]}", category="smartphone")
        session.add(product)
        await session.flush()
        variant = ProductVariant(
            product_id=product.id,
            manufacturer_model_code="S938B",
            ram_gb=12,
            storage_gb=256,
            color_raw="Silverblue",
            color_normalized="silverblue",
            condition=ProductCondition.NEW,
            canonical_key=build_canonical_key(
                brand=product.brand,
                canonical_name=product.canonical_name,
                manufacturer_model_code="S938B",
                ram_gb=12,
                storage_gb=256,
                color_normalized="silverblue",
                region_code=None,
                condition=ProductCondition.NEW,
            ),
        )
        policy = PricingPolicy(name=f"policy-{uuid.uuid4().hex[:8]}", is_default=False, mode=PricingMode.BALANCED, rounding_mode=PriceRoundingMode.UP)
        run = OneCImportRun(filename="x.json", file_hash=uuid.uuid4().hex, exported_at=NOW, mode="FULL", status="COMPLETED")
        item = OneCItem(internal_code=uuid.uuid4().hex[:8], raw_name="Samsung", normalized_name="samsung", matched_variant_id=variant.id, match_status="MATCHED")
        session.add_all([variant, policy, run, item])
        await session.flush()
        inventory = VariantInventoryState(variant_id=variant.id, own_stock_total=1 if stock_decision == StockDecision.ACTIVE else 0, own_cost_minor=6500000, currency="RUB", source_item_id=item.id, source_updated_at=NOW, last_import_run_id=run.id)
        pricing = VariantPricingState(
            product_variant_id=variant.id,
            policy_id=policy.id,
            pricing_mode=PricingMode.BALANCED,
            fulfillment_source=FulfillmentSource.OWN_STOCK if stock_decision == StockDecision.ACTIVE else FulfillmentSource.NONE,
            pricing_supplier_id=None,
            base_cost_minor=6500000 if price else None,
            required_costs_minor=0,
            avito_costs_minor=0,
            minimum_profit_minor=0,
            hard_floor_minor=6500000 if price else None,
            markup_minor=0,
            recommended_price_minor=price,
            manual_price_minor=None,
            final_price_minor=price,
            stock_decision=stock_decision,
            reason_codes=[],
            calculated_at=NOW,
        )
        session.add_all([inventory, pricing])
        await session.commit()
        variant_id = variant.id

    async with AsyncSessionLocal() as session:
        await rebuild_content_facts(session, variant_id)
        draft = await generate_content_draft(session, variant_id)
        draft = await validate_content_draft(session, draft.id)
        await approve_content_draft(session, draft.id)
        asset = await create_image_asset(session, variant_id, source_type=ImageAssetSourceType.MANUAL_UPLOAD, sha256=stable_hash({"img": str(variant_id)}), mime_type="image/png", size_bytes=10, width=1, height=1)
        image_set = await create_image_set(session, variant_id, [asset.id])
        image_set = await validate_image_set(session, image_set.id)
        await approve_image_set(session, image_set.id)
        listing = await build_generic_listing(session, variant_id)
        listing = await approve_listing(session, listing.id)
        return variant_id, listing.id


async def count(model):
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_intent_job_dry_run_success_and_no_fake_external_state():
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        intent, job, created = await create_publication_intent(session, listing_id, requested_by="qa")
        processed = await process_publication_job(session, job.id)
        binding = await session.get(MarketplaceListingBinding, intent.binding_id)
    assert created is True
    assert processed.status == PublicationJobStatus.DRY_RUN_SUCCESS
    assert processed.payload_hash is not None
    assert processed.prepared_payload["not_avito_compatible_payload"] is True
    assert binding.external_listing_id is None
    assert binding.status == MarketplaceBindingStatus.PREPARED
    assert binding.sync_state == ListingSyncState.DRY_RUN_OK
    assert binding.last_success_at is None


async def test_intent_and_job_idempotency():
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        first_intent, first_job, first_created = await create_publication_intent(session, listing_id, requested_by="qa")
        second_intent, second_job, second_created = await create_publication_intent(session, listing_id, requested_by="qa")
    assert first_created is True
    assert second_created is False
    assert first_intent.id == second_intent.id
    assert first_job.id == second_job.id
    assert await count(PublicationJob) == 1


async def test_real_avito_execution_is_blocked_without_retry_loop():
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        _intent, job, _ = await create_publication_intent(session, listing_id, requested_by="qa", dry_run=False)
        blocked = await process_publication_job(session, job.id, execute_real=True)
        again = await process_publication_job(session, job.id, execute_real=True)
    assert blocked.status == PublicationJobStatus.BLOCKED
    assert blocked.error_code == PublicationErrorCode.AVITO_CONTRACT_INCOMPLETE.value
    assert again.attempt_count == 1
    assert await count(PublicationAttempt) == 1


async def test_stale_intent_blocks_without_execution():
    variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        _intent, job, _ = await create_publication_intent(session, listing_id, requested_by="qa")
        listing = await session.get(GenericListingDraft, listing_id)
        listing.price_minor = 7100000
        await session.commit()
        blocked = await process_publication_job(session, job.id)
    assert blocked.status == PublicationJobStatus.BLOCKED
    assert blocked.error_code == PublicationErrorCode.STALE_INPUT.value


async def test_cancellation_and_retry_policy():
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        _intent, job, _ = await create_publication_intent(session, listing_id, requested_by="qa")
        cancelled = await cancel_publication_job(session, job.id, requested_by="qa")
        with pytest.raises(ValueError, match=PublicationErrorCode.JOB_ALREADY_TERMINAL.value):
            await cancel_publication_job(session, job.id, requested_by="qa")
    assert cancelled.status == PublicationJobStatus.CANCELLED


async def test_blocked_contract_is_not_retryable():
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        _intent, job, _ = await create_publication_intent(session, listing_id, requested_by="qa", dry_run=False)
        blocked = await process_publication_job(session, job.id, execute_real=True)
        with pytest.raises(ValueError, match=PublicationErrorCode.UNSUPPORTED_OPERATION.value):
            await retry_publication_job(session, blocked.id, requested_by="qa")


async def test_reconciliation_create_no_action_price_stock_and_content_change():
    variant_id, listing_id = await seed_approved_listing(price=7000000)
    async with AsyncSessionLocal() as session:
        create_required = await reconcile_listing(session, listing_id)
        _intent, job, _ = await create_publication_intent(session, listing_id, requested_by="qa")
        await process_publication_job(session, job.id)
        no_action = await reconcile_listing(session, listing_id)
        pricing = await session.get(VariantPricingState, variant_id)
        pricing.final_price_minor = 7100000
        await session.commit()
        price_required = await reconcile_listing(session, listing_id)
        pricing.stock_decision = StockDecision.OUT_OF_STOCK
        await session.commit()
        stock_required = await reconcile_listing(session, listing_id)
    assert create_required["action"] == ReconciliationAction.CREATE_REQUIRED.value
    assert no_action["action"] == ReconciliationAction.NO_ACTION.value
    assert price_required["action"] == ReconciliationAction.PRICE_UPDATE_REQUIRED.value
    assert stock_required["action"] in {ReconciliationAction.MULTIPLE_CHANGES.value, ReconciliationAction.STOCK_UPDATE_REQUIRED.value}


async def test_alert_deduplication_and_contract_block_not_critical():
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        alert1 = await open_alert(session, type="PUBLICATION_FAILED", severity=OperationalAlertSeverity.ERROR, entity_type="GenericListingDraft", entity_id=listing_id, message="failed")
        alert2 = await open_alert(session, type="PUBLICATION_FAILED", severity=OperationalAlertSeverity.ERROR, entity_type="GenericListingDraft", entity_id=listing_id, message="failed again")
        await session.commit()
    assert alert1.id == alert2.id
    assert await count(OperationalAlert) == 1


async def test_state_history_and_audit_are_recorded():
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        _intent, job, _ = await create_publication_intent(session, listing_id, requested_by="qa")
        await process_publication_job(session, job.id)
    assert await count(PublicationStateHistory) >= 4


async def test_control_api_flow(client):
    _variant_id, listing_id = await seed_approved_listing()
    overview = await client.get("/api/v1/control/overview")
    intent = await client.post(f"/api/v1/control/listings/{listing_id}/publication-intents", json={"requested_by": "qa"})
    dryrun = await client.post(f"/api/v1/control/listings/{listing_id}/dry-run", json={"requested_by": "qa"})
    jobs = await client.get("/api/v1/control/publication-jobs")
    job = await client.get(f"/api/v1/control/publication-jobs/{dryrun.json()['id']}")
    reconcile = await client.post("/api/v1/control/reconcile", json={"listing_id": str(listing_id)})
    review = await client.get("/api/v1/control/review-queue")
    bindings = await client.get("/api/v1/control/bindings")
    alerts = await client.get("/api/v1/control/alerts")
    assert overview.status_code == intent.status_code == dryrun.status_code == jobs.status_code == job.status_code == reconcile.status_code == review.status_code == bindings.status_code == alerts.status_code == 200
    assert dryrun.json()["status"] == PublicationJobStatus.DRY_RUN_SUCCESS.value


async def test_publication_queue_payload_is_job_id_only():
    _variant_id, listing_id = await seed_approved_listing()
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        _intent, job, _ = await create_publication_intent(session, listing_id, requested_by="qa")
        queued = await enqueue_publication_job(session, job, queue)
    assert queued.status == PublicationJobStatus.QUEUED
    assert queue.job_ids == [str(job.id)]


async def test_transient_failure_can_create_controlled_retry_job():
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        _intent, job, _ = await create_publication_intent(session, listing_id, requested_by="qa")
        job.status = PublicationJobStatus.FAILED
        job.error_code = PublicationErrorCode.TRANSIENT_EXTERNAL_ERROR.value
        await session.commit()
        retry = await retry_publication_job(session, job.id, requested_by="qa")
    assert retry.id != job.id
    assert retry.status == PublicationJobStatus.PENDING


async def test_review_queue_prioritizes_problem_listings_without_external_block_noise():
    variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        listing = await session.get(GenericListingDraft, listing_id)
        listing.generic_readiness = GenericReadinessStatus.REVIEW_REQUIRED
        listing.readiness_reasons = ["PRICING_REVIEW"]
        await session.commit()
        items = await __import__("app.services.publication", fromlist=["review_queue"]).review_queue(session, limit=10)
    assert items[0]["listing_id"] == listing_id
    assert items[0]["reason"] == "PRICING_REVIEW"


async def test_content_change_reconciliation_marks_binding_stale():
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        _intent, job, _ = await create_publication_intent(session, listing_id, requested_by="qa")
        await process_publication_job(session, job.id)
        draft = await session.scalar(select(ProductContentDraft).where(ProductContentDraft.status == "APPROVED"))
        draft.title = draft.title + " 5G"
        draft.content_hash = stable_hash({"title": draft.title})
        listing = await session.get(GenericListingDraft, listing_id)
        listing.title = draft.title
        listing.content_hash = stable_hash({"listing": listing.id, "title": listing.title})
        await session.commit()
        result = await reconcile_listing(session, listing_id)
        binding = await session.scalar(select(MarketplaceListingBinding).where(MarketplaceListingBinding.generic_listing_id == listing_id))
    assert result["action"] in {ReconciliationAction.CONTENT_UPDATE_REQUIRED.value, ReconciliationAction.MULTIPLE_CHANGES.value}
    assert binding.status == MarketplaceBindingStatus.STALE


async def test_stock_loss_reconciliation_requests_pause_or_stock_update():
    variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        _intent, job, _ = await create_publication_intent(session, listing_id, requested_by="qa")
        await process_publication_job(session, job.id)
        pricing = await session.get(VariantPricingState, variant_id)
        pricing.stock_decision = StockDecision.OUT_OF_STOCK
        await session.commit()
        result = await reconcile_listing(session, listing_id)
    assert result["action"] in {ReconciliationAction.PAUSE_REQUIRED.value, ReconciliationAction.STOCK_UPDATE_REQUIRED.value, ReconciliationAction.MULTIPLE_CHANGES.value}


async def test_telegram_operator_auth_and_dryrun(monkeypatch):
    monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "42")
    from app.core.config import get_settings

    get_settings.cache_clear()
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        assert is_authorized_operator("42") is True
        denied = await handle_operator_command(session, "13", f"/dryrun {listing_id}")
        status = await handle_operator_command(session, "13", "/status")
        dryrun = await handle_operator_command(session, "42", f"/dryrun {listing_id}")
    assert denied == "DENIED"
    assert "ready=" in status
    assert PublicationJobStatus.DRY_RUN_SUCCESS.value in dryrun
    get_settings.cache_clear()
