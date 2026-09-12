import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.content import GenericListingDraft, ProductContentDraft, ProductContentFacts, ProductImageAsset, ProductImageSet
from app.models.enums import (
    ContentDraftStatus,
    ContentFactSource,
    ContentValidationStatus,
    FulfillmentSource,
    GenericReadinessStatus,
    ImageAssetSourceType,
    ImageSetStatus,
    MarketplaceReadinessStatus,
    PriceRoundingMode,
    PricingMode,
    PricingReasonCode,
    ProductCondition,
    StockDecision,
)
from app.models.pricing import PricingPolicy, VariantPricingState
from app.models.product import Product, ProductVariant
from app.services.canonical_key import build_canonical_key
from app.services.content import (
    AvitoListingAdapter,
    approve_content_draft,
    approve_image_set,
    approve_listing,
    build_generic_listing,
    create_image_asset,
    create_image_set,
    generate_content_draft,
    latest_facts,
    rebuild_content_facts,
    recalculate_listing_readiness_bulk,
    set_manual_fact_override,
    stable_hash,
    validate_content_draft,
    validate_image_set,
)

pytestmark = pytest.mark.usefixtures("clean_database")

NOW = datetime(2026, 9, 12, 10, tzinfo=UTC)


async def seed_variant(*, condition=None, color="Silverblue", storage=256, stock_decision=StockDecision.ACTIVE, final_price=7000000):
    async with AsyncSessionLocal() as session:
        product = Product(brand="Samsung", canonical_name=f"Galaxy S25 Ultra {uuid.uuid4().hex[:6]}", category="smartphone")
        session.add(product)
        await session.flush()
        variant = ProductVariant(
            product_id=product.id,
            manufacturer_model_code="S938B",
            ram_gb=12,
            storage_gb=storage,
            color_raw=color,
            color_normalized=color.lower() if color else None,
            region_code=None,
            condition=condition,
            canonical_key=build_canonical_key(
                brand=product.brand,
                canonical_name=product.canonical_name,
                manufacturer_model_code="S938B",
                ram_gb=12,
                storage_gb=storage,
                color_normalized=color.lower() if color else None,
                region_code=None,
                condition=condition,
            ),
        )
        policy = PricingPolicy(
            name=f"policy-{uuid.uuid4().hex[:8]}",
            is_default=False,
            mode=PricingMode.BALANCED,
            rounding_mode=PriceRoundingMode.UP,
            minimum_profit_fixed_minor=100000,
            markup_fixed_minor=100000,
        )
        session.add_all([variant, policy])
        await session.flush()
        pricing = VariantPricingState(
            product_variant_id=variant.id,
            policy_id=policy.id,
            pricing_mode=PricingMode.BALANCED,
            fulfillment_source=FulfillmentSource.OWN_STOCK if stock_decision == StockDecision.ACTIVE else FulfillmentSource.NONE,
            pricing_supplier_id=None,
            base_cost_minor=6500000 if final_price else None,
            required_costs_minor=0,
            avito_costs_minor=0,
            minimum_profit_minor=100000,
            hard_floor_minor=6600000 if final_price else None,
            markup_minor=100000,
            recommended_price_minor=final_price,
            manual_price_minor=None,
            final_price_minor=final_price,
            stock_decision=stock_decision,
            reason_codes=[],
            calculated_at=NOW,
        )
        session.add(pricing)
        await session.commit()
        return variant.id


async def count(model):
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def prepare_approved_listing(variant_id):
    async with AsyncSessionLocal() as session:
        facts = await rebuild_content_facts(session, variant_id)
        draft = await generate_content_draft(session, variant_id)
        draft = await validate_content_draft(session, draft.id)
        await approve_content_draft(session, draft.id)
        asset = await create_image_asset(
            session,
            variant_id,
            source_type=ImageAssetSourceType.MANUAL_UPLOAD,
            sha256=stable_hash({"image": str(variant_id)}),
            mime_type="image/png",
            size_bytes=10,
            width=1,
            height=1,
        )
        image_set = await create_image_set(session, variant_id, [asset.id])
        image_set = await validate_image_set(session, image_set.id)
        await approve_image_set(session, image_set.id)
        listing = await build_generic_listing(session, variant_id)
        return facts.id, draft.id, image_set.id, listing.id


async def test_content_facts_preserve_unknown_condition_warranty_and_package():
    variant_id = await seed_variant(condition=None)
    async with AsyncSessionLocal() as session:
        facts = await rebuild_content_facts(session, variant_id)
    assert facts.condition is None
    assert facts.warranty_status == "UNKNOWN"
    assert facts.package_contents_status == "UNKNOWN"
    assert facts.additional_facts["fact_state"]["condition"] == "UNKNOWN"


async def test_known_explicit_condition_is_preserved():
    for condition in (ProductCondition.NEW, ProductCondition.USED, ProductCondition.REFURBISHED):
        variant_id = await seed_variant(condition=condition)
        async with AsyncSessionLocal() as session:
            facts = await rebuild_content_facts(session, variant_id)
        assert facts.condition == condition


async def test_manual_override_has_manual_provenance_and_precedence_for_missing_fact():
    variant_id = await seed_variant(condition=None)
    async with AsyncSessionLocal() as session:
        await set_manual_fact_override(session, variant_id, "region", "EU", "operator-1", "box label")
        facts = await rebuild_content_facts(session, variant_id)
    assert facts.region == "EU"
    assert any(source["field"] == "region" and source["source"] == ContentFactSource.MANUAL.value for source in facts.fact_sources)


async def test_conflicting_manual_identity_override_requires_review():
    variant_id = await seed_variant(color="Silverblue")
    async with AsyncSessionLocal() as session:
        await set_manual_fact_override(session, variant_id, "color", "Black", "operator-1")
        facts = await rebuild_content_facts(session, variant_id)
    assert facts.has_conflicts is True
    assert facts.requires_review is True
    assert facts.additional_facts["conflicts"][0]["field"] == "color"


async def test_fact_hash_deterministic_and_rebuild_idempotent():
    variant_id = await seed_variant()
    async with AsyncSessionLocal() as session:
        first = await rebuild_content_facts(session, variant_id)
        second = await rebuild_content_facts(session, variant_id)
    assert first.id == second.id
    assert first.fact_hash == second.fact_hash
    assert await count(ProductContentFacts) == 1


async def test_no_ai_factual_provenance():
    variant_id = await seed_variant()
    async with AsyncSessionLocal() as session:
        facts = await rebuild_content_facts(session, variant_id)
    assert all(source["source"] != "AI_GENERATED" for source in facts.fact_sources)


async def test_deterministic_content_omits_unknowns_and_preserves_known_tokens():
    variant_id = await seed_variant(condition=None)
    async with AsyncSessionLocal() as session:
        await rebuild_content_facts(session, variant_id)
        draft = await generate_content_draft(session, variant_id)
    assert "Samsung" in draft.title
    assert "S938B" in draft.title
    assert "12GB/256GB" in draft.title
    assert "Silverblue" in draft.title
    assert "Unknown" not in draft.description
    assert "Warranty" not in draft.description
    assert "Condition" not in draft.description


async def test_duplicate_generate_same_inputs_same_content_hash_no_duplicate():
    variant_id = await seed_variant()
    async with AsyncSessionLocal() as session:
        await rebuild_content_facts(session, variant_id)
        first = await generate_content_draft(session, variant_id)
        second = await generate_content_draft(session, variant_id)
    assert first.id == second.id
    assert await count(ProductContentDraft) == 1


async def test_unsupported_high_risk_claim_rejected():
    variant_id = await seed_variant(condition=None)
    async with AsyncSessionLocal() as session:
        await rebuild_content_facts(session, variant_id)
        draft = await generate_content_draft(session, variant_id)
        draft.description = "Новый смартфон с официальной гарантией 1 год"
        await session.commit()
        validated = await validate_content_draft(session, draft.id)
    assert validated.validation_status == ContentValidationStatus.INVALID
    assert {error["code"] for error in validated.validation_errors} >= {"UNSUPPORTED_CONDITION_CLAIM", "UNSUPPORTED_WARRANTY_CLAIM"}


async def test_contradictory_storage_and_color_rejected():
    variant_id = await seed_variant(storage=256, color="Silverblue")
    async with AsyncSessionLocal() as session:
        await rebuild_content_facts(session, variant_id)
        draft = await generate_content_draft(session, variant_id)
        draft.description = "Samsung Galaxy S25 Ultra 512GB black"
        await session.commit()
        validated = await validate_content_draft(session, draft.id)
    errors = {(error["code"], error.get("field")) for error in validated.validation_errors}
    assert ("FACT_CONTRADICTION", "storage") in errors
    assert ("FACT_CONTRADICTION", "color") in errors


async def test_image_asset_duplicate_and_image_set_validation_and_approval():
    variant_id = await seed_variant()
    sha = "a" * 64
    async with AsyncSessionLocal() as session:
        first = await create_image_asset(session, variant_id, source_type=ImageAssetSourceType.MANUAL_UPLOAD, sha256=sha, mime_type="image/png", size_bytes=12, width=1, height=1)
        second = await create_image_asset(session, variant_id, source_type=ImageAssetSourceType.MANUAL_UPLOAD, sha256=sha, mime_type="image/png", size_bytes=12, width=1, height=1)
        image_set = await create_image_set(session, variant_id, [first.id])
        validated = await validate_image_set(session, image_set.id)
        approved = await approve_image_set(session, validated.id)
    assert first.id == second.id
    assert await count(ProductImageAsset) == 1
    assert approved.status == ImageSetStatus.APPROVED


async def test_invalid_image_set_rejected_when_no_images():
    variant_id = await seed_variant()
    async with AsyncSessionLocal() as session:
        image_set = await create_image_set(session, variant_id, [])
        validated = await validate_image_set(session, image_set.id)
    assert validated.status == ImageSetStatus.REVIEW_REQUIRED


async def test_e2e_own_stock_generic_ready_avito_disabled():
    variant_id = await seed_variant(condition=None, stock_decision=StockDecision.ACTIVE, final_price=7000000)
    _, _, _, listing_id = await prepare_approved_listing(variant_id)
    async with AsyncSessionLocal() as session:
        listing = await session.get(GenericListingDraft, listing_id)
    assert listing.generic_readiness == GenericReadinessStatus.READY
    assert listing.avito_readiness == MarketplaceReadinessStatus.DISABLED_CONTRACT_INCOMPLETE
    assert "UNKNOWN_CONDITION" in listing.readiness_reasons


async def test_supplier_fallback_stock_can_be_generic_ready():
    variant_id = await seed_variant(stock_decision=StockDecision.ACTIVE, final_price=7100000)
    async with AsyncSessionLocal() as session:
        pricing = await session.get(VariantPricingState, variant_id)
        pricing.fulfillment_source = FulfillmentSource.SUPPLIER
        await session.commit()
    _, _, _, listing_id = await prepare_approved_listing(variant_id)
    async with AsyncSessionLocal() as session:
        listing = await session.get(GenericListingDraft, listing_id)
    assert listing.generic_readiness == GenericReadinessStatus.READY
    assert listing.fulfillment_source == FulfillmentSource.SUPPLIER.value


@pytest.mark.parametrize(
    ("decision", "reason"),
    [
        (StockDecision.OUT_OF_STOCK, "NO_STOCK"),
        (StockDecision.PAUSE, "SUPPLIER_STALE"),
        (StockDecision.REVIEW, "PRICING_REVIEW"),
    ],
)
async def test_pricing_and_stock_block_readiness(decision, reason):
    variant_id = await seed_variant(stock_decision=decision, final_price=7000000)
    _, _, _, listing_id = await prepare_approved_listing(variant_id)
    async with AsyncSessionLocal() as session:
        listing = await session.get(GenericListingDraft, listing_id)
    assert listing.generic_readiness != GenericReadinessStatus.READY
    assert reason in listing.readiness_reasons


async def test_manual_price_below_hard_floor_never_ready():
    variant_id = await seed_variant(stock_decision=StockDecision.REVIEW, final_price=6700000)
    async with AsyncSessionLocal() as session:
        pricing = await session.get(VariantPricingState, variant_id)
        pricing.reason_codes = [PricingReasonCode.MANUAL_PRICE_BELOW_FLOOR.value]
        await session.commit()
    _, _, _, listing_id = await prepare_approved_listing(variant_id)
    async with AsyncSessionLocal() as session:
        listing = await session.get(GenericListingDraft, listing_id)
    assert listing.generic_readiness == GenericReadinessStatus.REVIEW_REQUIRED
    assert "BELOW_HARD_FLOOR" in listing.readiness_reasons


async def test_fact_change_supersedes_approved_content_and_stales_listing():
    variant_id = await seed_variant(color="Silverblue")
    _, draft_id, _, listing_id = await prepare_approved_listing(variant_id)
    async with AsyncSessionLocal() as session:
        variant = await session.get(ProductVariant, variant_id)
        variant.color_raw = "Black"
        variant.color_normalized = "black"
        await session.commit()
        new_facts = await rebuild_content_facts(session, variant_id)
        old_draft = await session.get(ProductContentDraft, draft_id)
        old_listing = await session.get(GenericListingDraft, listing_id)
    assert new_facts.color == "Black"
    assert old_draft.status == ContentDraftStatus.SUPERSEDED
    assert old_listing.generic_readiness == GenericReadinessStatus.STALE


async def test_stock_loss_stales_ready_listing_without_content_regeneration():
    variant_id = await seed_variant(stock_decision=StockDecision.ACTIVE)
    _, _, _, _ = await prepare_approved_listing(variant_id)
    before = await count(ProductContentDraft)
    async with AsyncSessionLocal() as session:
        pricing = await session.get(VariantPricingState, variant_id)
        pricing.stock_decision = StockDecision.OUT_OF_STOCK
        pricing.final_price_minor = None
        await session.commit()
        listing = await build_generic_listing(session, variant_id)
    assert listing.generic_readiness == GenericReadinessStatus.NOT_READY
    assert "NO_PRICE" in listing.readiness_reasons
    assert await count(ProductContentDraft) == before


async def test_price_change_creates_new_listing_without_content_spam():
    variant_id = await seed_variant(stock_decision=StockDecision.ACTIVE, final_price=7000000)
    _, _, _, _ = await prepare_approved_listing(variant_id)
    before_drafts = await count(ProductContentDraft)
    async with AsyncSessionLocal() as session:
        pricing = await session.get(VariantPricingState, variant_id)
        pricing.final_price_minor = 7100000
        pricing.recommended_price_minor = 7100000
        await session.commit()
        listing = await build_generic_listing(session, variant_id)
    assert listing.price_minor == 7100000
    assert listing.generic_readiness == GenericReadinessStatus.READY
    assert await count(ProductContentDraft) == before_drafts


async def test_duplicate_listing_build_idempotent_and_bulk_counts():
    variant_id = await seed_variant()
    await prepare_approved_listing(variant_id)
    before = await count(GenericListingDraft)
    async with AsyncSessionLocal() as session:
        first = await build_generic_listing(session, variant_id)
        second = await build_generic_listing(session, variant_id)
        bulk = await recalculate_listing_readiness_bulk(session)
    assert first.id == second.id
    assert await count(GenericListingDraft) == before
    assert bulk["processed"] == 1
    assert bulk["unchanged"] == 1


async def test_avito_adapter_boundary_never_prepares_payload():
    variant_id = await seed_variant()
    _, _, _, listing_id = await prepare_approved_listing(variant_id)
    async with AsyncSessionLocal() as session:
        listing = await session.get(GenericListingDraft, listing_id)
    adapter = AvitoListingAdapter()
    assert adapter.validate_contract()["status"] == MarketplaceReadinessStatus.DISABLED_CONTRACT_INCOMPLETE.value
    assert adapter.publication_readiness(listing) == MarketplaceReadinessStatus.DISABLED_CONTRACT_INCOMPLETE
    with pytest.raises(ValueError, match="AVITO_CONTRACT_INCOMPLETE"):
        adapter.prepare_payload(listing)


async def test_api_content_listing_flow(client):
    variant_id = await seed_variant(condition=None)
    facts = await client.post(f"/api/v1/content/variants/{variant_id}/facts/rebuild")
    get_facts = await client.get(f"/api/v1/content/variants/{variant_id}/facts")
    override = await client.post(
        f"/api/v1/content/variants/{variant_id}/facts/manual-override",
        json={"field": "region", "value": "EU", "operator": "qa"},
    )
    draft = await client.post(f"/api/v1/content/variants/{variant_id}/generate")
    draft_id = draft.json()["id"]
    validate = await client.post(f"/api/v1/content/drafts/{draft_id}/validate")
    approve = await client.post(f"/api/v1/content/drafts/{draft_id}/approve")
    asset = await client.post(
        f"/api/v1/content/variants/{variant_id}/image-assets",
        json={"source_type": "MANUAL_UPLOAD", "mime_type": "image/png", "size_bytes": 10, "sha256": "b" * 64, "width": 1, "height": 1},
    )
    image_set = await client.post(
        f"/api/v1/content/variants/{variant_id}/image-sets",
        json={"image_asset_ids": [asset.json()["id"]]},
    )
    image_set_id = image_set.json()["id"]
    image_validate = await client.post(f"/api/v1/content/image-sets/{image_set_id}/validate")
    image_approve = await client.post(f"/api/v1/content/image-sets/{image_set_id}/approve")
    listing = await client.post(f"/api/v1/listings/variants/{variant_id}/build")
    listing_id = listing.json()["id"]
    listing_validate = await client.post(f"/api/v1/listings/{listing_id}/validate")
    listing_approve = await client.post(f"/api/v1/listings/{listing_id}/approve")
    bulk = await client.post("/api/v1/listings/bulk/recalculate")
    review_query = await client.get("/api/v1/listings?readiness=READY")
    assert facts.status_code == get_facts.status_code == draft.status_code == validate.status_code == approve.status_code == 200
    assert override.status_code == 200
    assert asset.status_code == image_set.status_code == 201
    assert image_validate.status_code == image_approve.status_code == listing.status_code == listing_validate.status_code == listing_approve.status_code == bulk.status_code == review_query.status_code == 200


async def test_material_events_are_audited_without_noop_spam():
    variant_id = await seed_variant()
    await prepare_approved_listing(variant_id)
    first_count = await count(AuditLog)
    async with AsyncSessionLocal() as session:
        await rebuild_content_facts(session, variant_id)
        await generate_content_draft(session, variant_id)
        await build_generic_listing(session, variant_id)
    assert await count(AuditLog) == first_count
