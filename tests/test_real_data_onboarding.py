from pathlib import Path
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.conflict import DataConflict
from app.models.content import GenericListingDraft, ProductContentFacts, ProductFactOverride, ProductImageAsset
from app.models.enums import (
    Availability,
    ConflictStatus,
    FulfillmentSource,
    ImageAssetSourceType,
    PriceRoundingMode,
    PricingMode,
    PricingReasonCode,
    ProductCondition,
    PublicationJobStatus,
    ReviewStatus,
    StockDecision,
)
from app.models.manual_import import ManualImportBatch
from app.models.match_review import MatchReview
from app.models.one_c import OneCItem, VariantInventoryState
from app.models.pricing import PricingDecisionHistory, PricingPolicy, VariantPricingState
from app.models.product import ProductAlias, ProductVariant
from app.models.publication import PublicationIntent
from app.models.raw_source_record import RawSourceRecord
from app.models.supplier_offer import SupplierOffer
from app.models.supplier_snapshot import SupplierSnapshot
from app.services.content import (
    approve_content_draft,
    approve_image_set,
    approve_listing,
    build_generic_listing,
    create_image_asset,
    create_image_set,
    generate_content_draft,
    latest_facts,
    rebuild_content_facts,
    set_manual_fact_override,
    stable_hash,
    validate_content_draft,
    validate_image_set,
)
from app.services.pricing.engine import create_pricing_policy, recalculate_variant_pricing, set_manual_price
from tests.test_publication_control import seed_approved_listing

pytestmark = pytest.mark.usefixtures("clean_database")


FIXTURES = Path(__file__).parent / "fixtures"


async def count(model) -> int:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def create_source(client):
    supplier = await client.post("/api/v1/suppliers", json={"code": "real-onboarding", "name": "Real Onboarding"})
    assert supplier.status_code == 201, supplier.text
    source = await client.post(
        "/api/v1/sources",
        json={
            "supplier_id": supplier.json()["id"],
            "source_type": "TELEGRAM",
            "external_key": "manual-telegram",
            "name": "Manual Telegram",
            "telegram_enabled": True,
            "snapshot_type": "FULL",
        },
    )
    assert source.status_code == 201, source.text
    return source.json()


async def create_named_source(client, code: str, name: str):
    supplier = await client.post("/api/v1/suppliers", json={"code": code, "name": name})
    assert supplier.status_code == 201, supplier.text
    source = await client.post(
        "/api/v1/sources",
        json={
            "supplier_id": supplier.json()["id"],
            "source_type": "TELEGRAM",
            "external_key": f"{code}-manual",
            "name": f"{name} manual",
            "telegram_enabled": True,
            "snapshot_type": "FULL",
        },
    )
    assert source.status_code == 201, source.text
    return supplier.json(), source.json()


async def onboard_variant(
    client,
    code: str,
    *,
    brand="Samsung",
    model=None,
    storage=256,
    color="black",
    color_normalized: str | None = None,
    condition="NEW",
):
    model = model or f"{brand} Pilot {code}"
    response = await client.post(
        "/api/v1/onboarding/products",
        json={
            "product": {"brand": brand, "canonical_name": model, "category": "smartphone"},
            "variant": {
                "manufacturer_model_code": code,
                "ram_gb": 8,
                "storage_gb": storage,
                "color_raw": color,
                "color_normalized": color_normalized or color.lower(),
                "condition": condition,
            },
            "aliases": [{"alias": code}],
            "actor": "acceptance",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["variant"]["id"]


async def telegram_preview_confirm(client, source_id: str, text: str):
    preview = await client.post(
        "/api/v1/onboarding/telegram/preview",
        json={"source_id": source_id, "raw_text": text, "snapshot_type": "FULL", "actor": "acceptance"},
    )
    assert preview.status_code == 200, preview.text
    confirm = await client.post(f"/api/v1/onboarding/telegram/{preview.json()['id']}/confirm", json={"actor": "acceptance"})
    assert confirm.status_code == 200, confirm.text
    return preview.json(), confirm.json()


async def one_c_preview_confirm(client, content: dict, *, filename: str):
    raw = json.dumps(content, ensure_ascii=False)
    preview = await client.post("/api/v1/onboarding/1c/preview", json={"filename": filename, "content": raw, "mode": "PARTIAL", "actor": "acceptance"})
    assert preview.status_code == 200, preview.text
    confirm = await client.post(f"/api/v1/onboarding/1c/{preview.json()['id']}/confirm", json={"actor": "acceptance"})
    assert confirm.status_code == 200, confirm.text
    return preview.json(), confirm.json()


async def test_manual_telegram_preview_confirm_and_idempotency(client):
    source = await create_source(client)
    raw_text = (FIXTURES / "telegram_realistic_price.txt").read_text(encoding="utf-8")

    preview = await client.post(
        "/api/v1/onboarding/telegram/preview",
        json={"source_id": source["id"], "raw_text": raw_text, "snapshot_type": "FULL", "actor": "qa"},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["status"] == "PREVIEWED"
    assert body["preview"]["candidate_product_lines"] == 2
    assert body["preview"]["valid_seen_items"] == 2
    assert body["preview"]["items"][0]["condition"] is None

    repeat_preview = await client.post(
        "/api/v1/onboarding/telegram/preview",
        json={"source_id": source["id"], "raw_text": raw_text, "snapshot_type": "FULL", "actor": "qa"},
    )
    assert repeat_preview.json()["id"] == body["id"]

    before_raw = await count(RawSourceRecord)
    before_snapshots = await count(SupplierSnapshot)
    confirm = await client.post(f"/api/v1/onboarding/telegram/{body['id']}/confirm", json={"actor": "qa"})
    assert confirm.status_code == 200, confirm.text
    confirmed = confirm.json()
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["raw_source_record_id"] is not None
    assert confirmed["supplier_snapshot_id"] is not None
    assert confirmed["result"]["snapshot"]["quality_gate_passed"] is True
    assert await count(RawSourceRecord) == before_raw + 1
    assert await count(SupplierSnapshot) == before_snapshots + 1

    second_confirm = await client.post(f"/api/v1/onboarding/telegram/{body['id']}/confirm", json={"actor": "qa"})
    assert second_confirm.status_code == 200
    assert await count(RawSourceRecord) == before_raw + 1
    assert await count(SupplierSnapshot) == before_snapshots + 1


async def test_one_c_preview_confirm_product_onboarding_and_inventory(client):
    content = (FIXTURES / "onec_realistic.json").read_text(encoding="utf-8")
    onboard = await client.post(
        "/api/v1/onboarding/products",
        json={
            "product": {"brand": "Samsung", "canonical_name": "Samsung Galaxy S25 Ultra S938B", "category": "smartphone"},
            "variant": {
                "manufacturer_model_code": "S938B",
                "ram_gb": 12,
                "storage_gb": 256,
                "color_raw": "Silverblue",
                "color_normalized": "silverblue",
                "condition": "NEW",
            },
            "aliases": [{"alias": "BAR-S938B"}],
            "actor": "qa",
        },
    )
    assert onboard.status_code == 200, onboard.text
    variant_id = onboard.json()["variant"]["id"]
    assert onboard.json()["aliases_created"] == 1

    preview = await client.post("/api/v1/onboarding/1c/preview", json={"filename": "onec_realistic.json", "content": content, "mode": "PARTIAL"})
    assert preview.status_code == 200, preview.text
    assert preview.json()["preview"]["matched_rows"] == 1
    assert preview.json()["preview"]["would_update_stock"] == 1

    confirm = await client.post(f"/api/v1/onboarding/1c/{preview.json()['id']}/confirm", json={"actor": "qa"})
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["result"]["status"] == "COMPLETED"
    async with AsyncSessionLocal() as session:
        item = await session.scalar(select(OneCItem).where(OneCItem.internal_code == "1C-S938B-256"))
        inventory = await session.get(VariantInventoryState, variant_id)
    assert item is not None
    assert inventory is not None
    assert inventory.own_stock_total == 3
    assert inventory.own_cost_minor == 6100000


async def test_dry_run_validation_and_pilot_readiness_endpoint(client):
    _variant_id, listing_id = await seed_approved_listing()
    dry_run = await client.post(f"/api/v1/control/listings/{listing_id}/dry-run", json={"requested_by": "qa"})
    assert dry_run.status_code == 200, dry_run.text

    validation = await client.get(f"/api/v1/control/listings/{listing_id}/dry-run-validation")
    assert validation.status_code == 200
    assert validation.json()["status"] == "INTERNAL_DRY_RUN_VALIDATED"
    assert validation.json()["checks"]["avito_contract_disabled"] is True

    readiness = await client.get("/api/v1/operator/pilot-readiness")
    assert readiness.status_code == 200
    assert readiness.json()["status"] == "READY_FOR_PILOT"


async def test_onboarding_imports_are_operator_protected(unauthenticated_client):
    response = await unauthenticated_client.get("/api/v1/onboarding/imports")
    assert response.status_code == 401


async def test_sprint_1_2_operational_e2e_acceptance(client):
    now = datetime(2026, 9, 14, 10, tzinfo=UTC)
    codes = {
        "local": "S938B",
        "supplier": "A3101",
        "conflict": "XIAO13",
        "review": "UNKREV",
        "stale": "STALE1",
        "nostock": "NOSTK1",
    }
    local_id = await onboard_variant(
        client,
        codes["local"],
        model="Galaxy S25 Ultra",
        color="silverblue",
        color_normalized="Silver Blue",
        condition=None,
    )
    supplier_id = await onboard_variant(client, codes["supplier"], brand="Apple", model="iPhone 15 Pro", color="black", color_normalized="Black", condition=None)
    conflict_id = await onboard_variant(client, codes["conflict"], brand="Xiaomi", model="Xiaomi 13", color="black")
    stale_id = await onboard_variant(client, codes["stale"], brand="Samsung", model="Samsung Galaxy A55", color="blue")
    nostock_id = await onboard_variant(client, codes["nostock"], brand="Xiaomi", model="Xiaomi Redmi Note 13", color="black")

    async with AsyncSessionLocal() as session:
        await create_pricing_policy(
            session,
            name=f"acceptance-policy-{uuid.uuid4().hex[:8]}",
            is_default=True,
            mode=PricingMode.BALANCED,
            fixed_required_cost_minor=100000,
            reserve_minor=50000,
            avito_fixed_cost_minor=50000,
            minimum_profit_fixed_minor=200000,
            markup_fixed_minor=300000,
            rounding_step_minor=10000,
            rounding_mode=PriceRoundingMode.UP,
        )

    one_c_initial = {
        "exported_at": now.isoformat(),
        "source": "1c",
        "items": [
            {"internal_code": "1C-LOCAL", "sku": codes["local"], "barcode": "BAR-LOCAL", "name": "Samsung Galaxy S25 Ultra S938B 8/256 Silverblue", "stock_total": 3, "cost": "61000.00", "currency": "RUB", "updated_at": now.isoformat()},
            {"internal_code": "1C-SUPPLIER", "sku": codes["supplier"], "barcode": "BAR-SUPPLIER", "name": "Apple iPhone 15 Pro A3101 8/256 Black", "stock_total": 0, "cost": "70000.00", "currency": "RUB", "updated_at": now.isoformat()},
            {"internal_code": "1C-UNMATCHED-A", "sku": "UNMATCH-A", "barcode": "BAR-UNMATCH-A", "name": "Unmatched Accessory Alpha", "stock_total": 2, "cost": "1200.00", "currency": "RUB", "updated_at": now.isoformat()},
            {"internal_code": "1C-UNMATCHED-B", "sku": "UNMATCH-B", "barcode": "BAR-UNMATCH-B", "name": "Unmatched Accessory Beta", "stock_total": 0, "cost": "0", "currency": "RUB", "updated_at": now.isoformat()},
            {"internal_code": "1C-DUP", "sku": "DUP-A", "barcode": "BAR-DUP-A", "name": "Duplicate A", "stock_total": 1, "cost": "1000.00", "currency": "RUB", "updated_at": now.isoformat()},
            {"internal_code": "1C-DUP", "sku": "DUP-B", "barcode": "BAR-DUP-B", "name": "Duplicate B", "stock_total": 2, "cost": "1100.00", "currency": "RUB", "updated_at": now.isoformat()},
            {"internal_code": "", "name": "", "stock_total": "bad", "cost": "bad", "currency": "RUB", "updated_at": now.isoformat()},
        ],
    }
    one_c_preview, one_c_confirm = await one_c_preview_confirm(client, one_c_initial, filename="pilot-acceptance-1c.json")
    assert one_c_preview["preview"]["valid_rows"] >= 4
    assert one_c_preview["preview"]["invalid_rows"] >= 1
    assert one_c_preview["preview"]["unmatched_rows"] >= 2
    assert one_c_confirm["result"]["status"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}

    supplier, source = await create_named_source(client, "pilot-supplier-fresh", "Pilot Supplier Fresh")
    clean_supplier_text = "\n".join(
        [
            "Apple",
            f"iPhone 15 Pro {codes['supplier']} 8/256 black - 90000",
            "Samsung",
            f"Galaxy S25 Ultra {codes['local']} 8/256 silverblue - 88000",
        ]
    )
    telegram_preview, telegram_confirm = await telegram_preview_confirm(client, source["id"], clean_supplier_text)
    assert telegram_preview["preview"]["valid_seen_items"] == 2
    assert telegram_confirm["result"]["snapshot"]["quality_gate_passed"] is True

    supplier_repeat_preview = await client.post(
        "/api/v1/onboarding/telegram/preview",
        json={"source_id": source["id"], "raw_text": clean_supplier_text, "snapshot_type": "FULL", "actor": "acceptance"},
    )
    supplier_repeat_confirm = await client.post(
        f"/api/v1/onboarding/telegram/{supplier_repeat_preview.json()['id']}/confirm",
        json={"actor": "acceptance"},
    )
    assert supplier_repeat_preview.json()["id"] == telegram_preview["id"]
    assert supplier_repeat_confirm.json()["raw_source_record_id"] == telegram_confirm["raw_source_record_id"]

    conflict_supplier, conflict_source = await create_named_source(client, "pilot-supplier-conflict", "Pilot Supplier Conflict")
    conflict_text = "\n".join(
        [
            "Xiaomi",
            f"Xiaomi 13 {codes['conflict']} 8/256 black - 50000",
            f"Xiaomi 13 {codes['conflict']} 8/256 black - 51000",
        ]
    )
    await telegram_preview_confirm(client, conflict_source["id"], conflict_text)

    review_supplier, review_source = await create_named_source(client, "pilot-supplier-review", "Pilot Supplier Review")
    review_text = "Samsung\nGalaxy UnknownReview UNKREV - 50000"
    await telegram_preview_confirm(client, review_source["id"], review_text)

    async with AsyncSessionLocal() as session:
        unmatched_items = list(await session.scalars(select(OneCItem).where(OneCItem.match_status == "UNMATCHED").order_by(OneCItem.internal_code)))
        assert len(unmatched_items) >= 2
        linked_item = unmatched_items[0]

    linked_variant = await client.post(
        "/api/v1/onboarding/products",
        json={
            "product": {"brand": "Pilot", "canonical_name": "Pilot Linked 1C Item", "category": "accessory"},
            "variant": {"manufacturer_model_code": "LINK1C", "storage_gb": 64, "condition": "NEW"},
            "aliases": [{"alias": "LINK1C"}],
            "one_c_item_id": str(linked_item.id),
            "actor": "acceptance",
        },
    )
    assert linked_variant.status_code == 200, linked_variant.text
    linked_variant_id = linked_variant.json()["variant"]["id"]
    one_c_linked = {
        "exported_at": (now + timedelta(minutes=5)).isoformat(),
        "source": "1c",
        "items": [
            {"internal_code": linked_item.internal_code, "sku": linked_item.sku, "barcode": linked_item.barcode, "name": linked_item.raw_name, "stock_total": 4, "cost": "1300.00", "currency": "RUB", "updated_at": (now + timedelta(minutes=5)).isoformat()},
        ],
    }
    await one_c_preview_confirm(client, one_c_linked, filename="pilot-linked-1c.json")

    async with AsyncSessionLocal() as session:
        linked_state = await session.get(VariantInventoryState, linked_variant_id)
        assert linked_state and linked_state.own_stock_total == 4
        assert await session.scalar(select(AuditLog).where(AuditLog.action == "ONE_C_ITEM_MAPPED")) is not None

    async with AsyncSessionLocal() as session:
        review = await session.scalar(select(MatchReview).where(MatchReview.status == ReviewStatus.PENDING))
        assert review is not None
    review_variant = await onboard_variant(client, codes["review"], brand="Samsung", model="Samsung Galaxy Unknown Review", storage=128)
    accept_review = await client.post(
        f"/api/v1/match-reviews/{review.id}/accept",
        json={"variant_id": review_variant, "alias": "Galaxy UnknownReview UNKREV", "actor": "acceptance"},
    )
    assert accept_review.status_code == 200, accept_review.text
    assert accept_review.json()["status"] == "ACCEPTED"

    async with AsyncSessionLocal() as session:
        alias = await session.scalar(select(ProductAlias).where(ProductAlias.alias == "Galaxy UnknownReview UNKREV"))
        assert alias is not None
        assert await session.scalar(select(AuditLog).where(AuditLog.action == "MATCH_REVIEW_ACCEPTED")) is not None
        parsed_conflict = DataConflict(
            conflict_type="ACCEPTANCE_SUPPLIER_PRICE_CONFLICT",
            source_id=uuid.UUID(conflict_source["id"]),
            product_variant_id=uuid.UUID(conflict_id),
            details={"supplier_id": supplier["id"], "reason": "sanitized acceptance conflict"},
            status=ConflictStatus.OPEN,
        )
        conflict_offer = SupplierOffer(
            supplier_id=uuid.UUID(supplier["id"]),
            product_variant_id=uuid.UUID(conflict_id),
            source_id=uuid.UUID(conflict_source["id"]),
            supplier_sku="conflict-offer",
            supplier_title="Xiaomi 13 conflict",
            price_minor=5000000,
            currency="RUB",
            availability=Availability.IN_STOCK,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add_all([parsed_conflict, conflict_offer])
        await session.commit()
        parsed_conflict_id = parsed_conflict.id

    async with AsyncSessionLocal() as session:
        conflict_state = await recalculate_variant_pricing(session, uuid.UUID(conflict_id), now=now)
        assert conflict_state.stock_decision == StockDecision.REVIEW
        assert PricingReasonCode.SUPPLIER_CONFLICT.value in conflict_state.reason_codes
    resolve = await client.post(
        f"/api/v1/conflicts/{parsed_conflict_id}/resolve",
        json={"actor": "acceptance", "resolution": "sanitized pilot chose no supplier price overwrite"},
    )
    assert resolve.status_code == 200, resolve.text
    assert resolve.json()["status"] == "RESOLVED"

    async with AsyncSessionLocal() as session:
        for variant_id in (local_id, supplier_id, conflict_id, stale_id, nostock_id, linked_variant_id, review_variant):
            await recalculate_variant_pricing(session, uuid.UUID(variant_id), now=now)
        local_state = await session.get(VariantPricingState, uuid.UUID(local_id))
        supplier_state = await session.get(VariantPricingState, uuid.UUID(supplier_id))
        no_stock_state = await session.get(VariantPricingState, uuid.UUID(nostock_id))
        assert local_state.fulfillment_source == FulfillmentSource.OWN_STOCK
        assert local_state.final_price_minor >= local_state.hard_floor_minor
        assert local_state.hard_floor_minor == 6100000 + 100000 + 50000 + 50000 + 200000
        assert supplier_state.fulfillment_source == FulfillmentSource.SUPPLIER
        assert supplier_state.pricing_supplier_id == uuid.UUID(supplier["id"])
        assert no_stock_state.stock_decision == StockDecision.OUT_OF_STOCK

        stale_offer = SupplierOffer(
            supplier_id=uuid.UUID(supplier["id"]),
            product_variant_id=uuid.UUID(stale_id),
            supplier_sku="stale-offer",
            supplier_title="stale supplier",
            price_minor=3000000,
            currency="RUB",
            availability=Availability.IN_STOCK,
            first_seen_at=now - timedelta(days=3),
            last_seen_at=now - timedelta(days=3),
        )
        session.add(stale_offer)
        await session.commit()
        stale_state = await recalculate_variant_pricing(session, uuid.UUID(stale_id), now=now)
        assert stale_state.stock_decision == StockDecision.PAUSE
        assert PricingReasonCode.SUPPLIER_OFFER_STALE.value in stale_state.reason_codes

        await set_manual_price(session, uuid.UUID(local_id), local_state.hard_floor_minor - 10000, note="acceptance below floor")
        below_floor = await session.get(VariantPricingState, uuid.UUID(local_id))
        assert below_floor.stock_decision == StockDecision.REVIEW
        assert PricingReasonCode.MANUAL_PRICE_BELOW_FLOOR.value in below_floor.reason_codes
        # Remove manual override side-effect by recalculating after deleting override through the tested clear path is covered elsewhere.

    async with AsyncSessionLocal() as session:
        await set_manual_fact_override(session, uuid.UUID(local_id), "warranty_text", "Seller warranty 14 days", "acceptance", "sanitized pilot")
        facts = await rebuild_content_facts(session, uuid.UUID(local_id))
        assert facts.brand == "Samsung"
        assert facts.storage == "256GB"
        assert facts.color == "silverblue"
        assert facts.condition is None
        assert any(source["source"] == "MANUAL" for source in facts.fact_sources)
        assert await session.scalar(select(ProductFactOverride).where(ProductFactOverride.operator == "acceptance")) is not None

        # Recalculate after below-floor guard so the main listing can become ready.
        from app.services.pricing.engine import clear_manual_price

        await clear_manual_price(session, uuid.UUID(local_id))
        local_state = await session.get(VariantPricingState, uuid.UUID(local_id))
        assert local_state.stock_decision == StockDecision.ACTIVE

        draft = await generate_content_draft(session, uuid.UUID(local_id))
        draft = await validate_content_draft(session, draft.id)
        assert draft.validation_errors == []
        assert "100% оригинал" not in draft.description.lower()
        draft = await approve_content_draft(session, draft.id)
        image_hash = stable_hash({"pilot": "local", "variant_id": local_id})
        asset_one = await create_image_asset(
            session,
            uuid.UUID(local_id),
            source_type=ImageAssetSourceType.MANUAL_UPLOAD,
            sha256=image_hash,
            mime_type="image/png",
            size_bytes=68,
            width=1,
            height=1,
            source_reference="sanitized-fixture:1x1-png",
            original_filename="pilot-1x1.png",
        )
        asset_two = await create_image_asset(
            session,
            uuid.UUID(local_id),
            source_type=ImageAssetSourceType.MANUAL_UPLOAD,
            sha256=image_hash,
            mime_type="image/png",
            size_bytes=68,
            width=1,
            height=1,
            source_reference="sanitized-fixture:1x1-png",
            original_filename="pilot-1x1.png",
        )
        assert asset_one.id == asset_two.id
        image_set = await create_image_set(session, uuid.UUID(local_id), [asset_one.id])
        image_set = await validate_image_set(session, image_set.id)
        image_set = await approve_image_set(session, image_set.id)
        listing = await build_generic_listing(session, uuid.UUID(local_id))
        assert listing.generic_readiness.name == "READY"
        listing = await approve_listing(session, listing.id)
        listing_id = listing.id

    dry_run = await client.post(f"/api/v1/control/listings/{listing_id}/dry-run", json={"requested_by": "acceptance"})
    assert dry_run.status_code == 200, dry_run.text
    assert dry_run.json()["status"] == PublicationJobStatus.DRY_RUN_SUCCESS.value
    validation = await client.get(f"/api/v1/control/listings/{listing_id}/dry-run-validation")
    assert validation.status_code == 200
    assert validation.json()["status"] == "INTERNAL_DRY_RUN_VALIDATED"
    for key in ("IDENTITY", "STOCK", "PRICE", "CONTENT", "IMAGES", "CONFLICTS", "HASHES"):
        assert validation.json()["checks"][key] is True

    async with AsyncSessionLocal() as session:
        intent = await session.scalar(select(PublicationIntent).where(PublicationIntent.listing_id == listing_id))
        assert intent is not None
        assert intent.approved_snapshot_hash
        assert intent.content_hash
        assert intent.image_set_hash

    before_readiness = await client.get("/api/v1/operator/pilot-readiness")
    assert before_readiness.status_code == 200
    before_checks = before_readiness.json()["checks"]
    assert before_checks["TOTAL"] >= 7
    assert before_checks["DRY_RUN_VALIDATED"] >= 1
    assert before_checks["PRICING_READY"] >= 2

    one_c_cost_change = {
        "exported_at": (now + timedelta(minutes=10)).isoformat(),
        "source": "1c",
        "items": [
            {"internal_code": "1C-LOCAL", "sku": codes["local"], "barcode": "BAR-LOCAL", "name": "Samsung Galaxy S25 Ultra S938B 8/256 Silverblue", "stock_total": 3, "cost": "62000.00", "currency": "RUB", "updated_at": (now + timedelta(minutes=10)).isoformat()},
        ],
    }
    await one_c_preview_confirm(client, one_c_cost_change, filename="pilot-cost-change-1c.json")
    async with AsyncSessionLocal() as session:
        updated_local = await recalculate_variant_pricing(session, uuid.UUID(local_id), now=now + timedelta(minutes=10))
        assert updated_local.base_cost_minor == 6200000
        rebuilt = await build_generic_listing(session, uuid.UUID(local_id))
        assert rebuilt.content_hash != (await session.get(GenericListingDraft, listing_id)).content_hash

    one_c_stock_zero = {
        "exported_at": (now + timedelta(minutes=20)).isoformat(),
        "source": "1c",
        "items": [
            {"internal_code": "1C-LOCAL", "sku": codes["local"], "barcode": "BAR-LOCAL", "name": "Samsung Galaxy S25 Ultra S938B 8/256 Silverblue", "stock_total": 0, "cost": "62000.00", "currency": "RUB", "updated_at": (now + timedelta(minutes=20)).isoformat()},
        ],
    }
    await one_c_preview_confirm(client, one_c_stock_zero, filename="pilot-stock-zero-1c.json")
    async with AsyncSessionLocal() as session:
        fallback = await recalculate_variant_pricing(session, uuid.UUID(local_id), now=now + timedelta(minutes=20))
        assert fallback.fulfillment_source == FulfillmentSource.SUPPLIER
        assert fallback.pricing_supplier_id == uuid.UUID(supplier["id"])
        assert await session.scalar(select(PricingDecisionHistory).where(PricingDecisionHistory.product_variant_id == uuid.UUID(local_id))) is not None

    system_health = await client.get("/api/v1/operator/system/health")
    assert system_health.status_code == 200
    assert system_health.json()["avito_real_mutation"] == "DISABLED_CONTRACT_INCOMPLETE"

    async with AsyncSessionLocal() as session:
        assert await session.scalar(select(ManualImportBatch).where(ManualImportBatch.import_type == "TELEGRAM")) is not None
        assert await session.scalar(select(ProductImageAsset).where(ProductImageAsset.sha256 == image_hash)) is not None
        assert await session.scalar(select(AuditLog).where(AuditLog.action == "DATA_CONFLICT_RESOLVED")) is not None
