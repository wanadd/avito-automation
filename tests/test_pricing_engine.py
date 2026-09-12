import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.conflict import DataConflict
from app.models.enums import (
    Availability,
    ConflictStatus,
    FulfillmentSource,
    PriceRoundingMode,
    PricingMode,
    PricingReasonCode,
    ProductCondition,
    StockDecision,
)
from app.models.one_c import OneCImportRun, OneCItem, VariantInventoryState
from app.models.pricing import PricingDecisionHistory, PricingPolicy, VariantPricingOverride, VariantPricingState
from app.models.product import Product, ProductVariant
from app.models.supplier import Supplier
from app.models.supplier_offer import SupplierOffer
from app.services.canonical_key import build_canonical_key
from app.services.pricing.engine import (
    clear_manual_price,
    create_pricing_policy,
    recalculate_all_pricing,
    recalculate_variant_pricing,
    set_manual_price,
    update_pricing_policy,
)
from app.services.pricing.formulas import hard_floor, minimum_profit, price_from_cost, round_price
from app.services.pricing.types import PricingOverrideInput, PricingPolicyInput

pytestmark = pytest.mark.usefixtures("clean_database")

NOW = datetime(2026, 9, 12, 10, tzinfo=UTC)


def policy_input(**overrides):
    values = {
        "id": uuid.uuid4(),
        "mode": PricingMode.BALANCED,
        "fixed_required_cost_minor": 0,
        "reserve_minor": 0,
        "avito_fixed_cost_minor": 0,
        "avito_percent_bps": 0,
        "minimum_profit_fixed_minor": 0,
        "minimum_profit_bps": 0,
        "markup_fixed_minor": 0,
        "markup_bps": 0,
        "rounding_step_minor": 10000,
        "rounding_mode": PriceRoundingMode.UP,
    }
    values.update(overrides)
    return PricingPolicyInput(**values)


def test_min_profit_uses_max_fixed_or_percent():
    assert minimum_profit(6500000, policy_input(minimum_profit_fixed_minor=100000, minimum_profit_bps=1000)) == 650000


def test_hard_floor_fixed_costs():
    floor, required, avito, profit = hard_floor(6500000, policy_input(fixed_required_cost_minor=100000, reserve_minor=50000, avito_fixed_cost_minor=50000, minimum_profit_fixed_minor=100000))
    assert (floor, required, avito, profit) == (6800000, 150000, 50000, 100000)


def test_hard_floor_avito_percent_algebraic():
    floor, _, avito, _ = hard_floor(1000000, policy_input(avito_percent_bps=1000))
    assert floor == 1111112
    assert avito == 111112


def test_rounding_up_never_below_input():
    assert round_price(6750001, 10000, PriceRoundingMode.UP) == 6760000


def test_nearest_rounding_supported():
    assert round_price(6754000, 10000, PriceRoundingMode.NEAREST) == 6750000


def test_clearance_mode_stays_at_floor():
    decision = price_from_cost(
        base_cost_minor=6500000,
        policy=policy_input(mode=PricingMode.CLEARANCE, fixed_required_cost_minor=300000, clearance_markup_minor=0),
        override=PricingOverrideInput(),
        fulfillment_source=FulfillmentSource.OWN_STOCK,
        pricing_supplier_id=None,
        reasons=[],
    )
    assert decision.final_price_minor == decision.hard_floor_minor


def test_manual_below_floor_returns_review():
    decision = price_from_cost(
        base_cost_minor=6500000,
        policy=policy_input(fixed_required_cost_minor=300000),
        override=PricingOverrideInput(True, 6700000),
        fulfillment_source=FulfillmentSource.OWN_STOCK,
        pricing_supplier_id=None,
        reasons=[],
    )
    assert decision.stock_decision == StockDecision.REVIEW
    assert PricingReasonCode.MANUAL_PRICE_BELOW_FLOOR.value in decision.reason_codes


async def seed_variant():
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
        session.add(variant)
        await session.commit()
        return variant.id


async def seed_policy(**overrides):
    defaults = {
        "name": f"policy-{uuid.uuid4().hex[:8]}",
        "is_default": True,
        "mode": PricingMode.BALANCED,
        "fixed_required_cost_minor": 0,
        "reserve_minor": 0,
        "avito_fixed_cost_minor": 0,
        "avito_percent_bps": 0,
        "minimum_profit_fixed_minor": 100000,
        "markup_fixed_minor": 100000,
        "rounding_step_minor": 10000,
    }
    defaults.update(overrides)
    async with AsyncSessionLocal() as session:
        policy = await create_pricing_policy(session, **defaults)
        return policy.id


async def seed_inventory(variant_id, *, stock=1, cost=6500000, updated_at=NOW):
    async with AsyncSessionLocal() as session:
        run = OneCImportRun(filename="x.json", file_hash=uuid.uuid4().hex, exported_at=updated_at, mode="FULL", status="COMPLETED")
        item = OneCItem(internal_code=uuid.uuid4().hex[:8], raw_name="Samsung", normalized_name="samsung", matched_variant_id=variant_id, match_status="MATCHED")
        session.add_all([run, item])
        await session.flush()
        state = VariantInventoryState(variant_id=variant_id, own_stock_total=stock, own_cost_minor=cost, currency="RUB", source_item_id=item.id, source_updated_at=updated_at, last_import_run_id=run.id)
        session.add(state)
        await session.commit()


async def seed_supplier_offer(variant_id, *, price=6300000, availability=Availability.IN_STOCK, last_seen=NOW, supplier_code=None):
    async with AsyncSessionLocal() as session:
        supplier = Supplier(code=supplier_code or f"s-{uuid.uuid4().hex[:6]}", name="Supplier")
        session.add(supplier)
        await session.flush()
        offer = SupplierOffer(supplier_id=supplier.id, product_variant_id=variant_id, supplier_title="Samsung", price_minor=price, currency="RUB", availability=availability, first_seen_at=last_seen, last_seen_at=last_seen)
        session.add(offer)
        await session.commit()
        return supplier.id, offer.id


async def load_state(variant_id):
    async with AsyncSessionLocal() as session:
        return await session.get(VariantPricingState, variant_id)


async def count(model):
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_own_stock_priority_supplier_cheaper_does_not_replace():
    variant_id = await seed_variant()
    await seed_policy()
    await seed_inventory(variant_id, stock=2, cost=6500000)
    await seed_supplier_offer(variant_id, price=6300000)
    async with AsyncSessionLocal() as session:
        state = await recalculate_variant_pricing(session, variant_id, now=NOW)
    assert state.fulfillment_source == FulfillmentSource.OWN_STOCK
    assert state.pricing_supplier_id is None
    assert state.base_cost_minor == 6500000


async def test_supplier_fallback_selects_cheapest():
    variant_id = await seed_variant()
    await seed_policy()
    await seed_inventory(variant_id, stock=0, cost=6500000)
    a, _ = await seed_supplier_offer(variant_id, price=6400000, supplier_code="a")
    b, _ = await seed_supplier_offer(variant_id, price=6300000, supplier_code="b")
    async with AsyncSessionLocal() as session:
        state = await recalculate_variant_pricing(session, variant_id, now=NOW)
    assert state.fulfillment_source == FulfillmentSource.SUPPLIER
    assert state.pricing_supplier_id == b
    assert state.base_cost_minor == 6300000


async def test_supplier_tie_break_price_freshness_supplier_id():
    variant_id = await seed_variant()
    await seed_policy()
    old_supplier, _ = await seed_supplier_offer(variant_id, price=6300000, last_seen=NOW - timedelta(minutes=1), supplier_code="old")
    fresh_supplier, _ = await seed_supplier_offer(variant_id, price=6300000, last_seen=NOW, supplier_code="fresh")
    async with AsyncSessionLocal() as session:
        state = await recalculate_variant_pricing(session, variant_id, now=NOW)
    assert state.pricing_supplier_id == fresh_supplier
    assert state.pricing_supplier_id != old_supplier


async def test_stale_supplier_offer_pauses():
    variant_id = await seed_variant()
    await seed_policy()
    await seed_supplier_offer(variant_id, last_seen=NOW - timedelta(minutes=181))
    async with AsyncSessionLocal() as session:
        state = await recalculate_variant_pricing(session, variant_id, now=NOW)
    assert state.stock_decision == StockDecision.PAUSE
    assert PricingReasonCode.SUPPLIER_OFFER_STALE.value in state.reason_codes


async def test_no_stock_out_of_stock():
    variant_id = await seed_variant()
    await seed_policy()
    async with AsyncSessionLocal() as session:
        state = await recalculate_variant_pricing(session, variant_id, now=NOW)
    assert state.stock_decision == StockDecision.OUT_OF_STOCK


async def test_supplier_conflict_review():
    variant_id = await seed_variant()
    await seed_policy()
    supplier_id, _ = await seed_supplier_offer(variant_id)
    async with AsyncSessionLocal() as session:
        session.add(DataConflict(conflict_type="X", product_variant_id=variant_id, details={"supplier_id": str(supplier_id)}, status=ConflictStatus.OPEN))
        await session.commit()
        state = await recalculate_variant_pricing(session, variant_id, now=NOW)
    assert state.stock_decision == StockDecision.REVIEW
    assert PricingReasonCode.SUPPLIER_CONFLICT.value in state.reason_codes


@pytest.mark.parametrize("availability", [Availability.SUSPECT_MISSING, Availability.OUT_OF_STOCK, Availability.UNKNOWN])
async def test_only_in_stock_supplier_is_eligible(availability):
    variant_id = await seed_variant()
    await seed_policy()
    await seed_supplier_offer(variant_id, availability=availability)
    async with AsyncSessionLocal() as session:
        state = await recalculate_variant_pricing(session, variant_id, now=NOW)
    assert state.stock_decision == StockDecision.OUT_OF_STOCK


async def test_hard_floor_applied_when_markup_below_floor():
    variant_id = await seed_variant()
    await seed_policy(fixed_required_cost_minor=300000, minimum_profit_fixed_minor=0, markup_fixed_minor=0)
    await seed_inventory(variant_id, stock=1, cost=6500000)
    async with AsyncSessionLocal() as session:
        state = await recalculate_variant_pricing(session, variant_id, now=NOW)
    assert state.hard_floor_minor == 6800000
    assert state.final_price_minor == 6800000
    assert PricingReasonCode.HARD_FLOOR_APPLIED.value in state.reason_codes


async def test_manual_valid_applied():
    variant_id = await seed_variant()
    await seed_policy()
    await seed_inventory(variant_id, stock=1, cost=6500000)
    async with AsyncSessionLocal() as session:
        await set_manual_price(session, variant_id, 7000000)
        state = await session.get(VariantPricingState, variant_id)
    assert state.pricing_mode == PricingMode.MANUAL
    assert state.final_price_minor == 7000000


async def test_manual_below_floor_blocks():
    variant_id = await seed_variant()
    await seed_policy(fixed_required_cost_minor=300000)
    await seed_inventory(variant_id, stock=1, cost=6500000)
    async with AsyncSessionLocal() as session:
        await set_manual_price(session, variant_id, 6700000)
        state = await session.get(VariantPricingState, variant_id)
    assert state.stock_decision == StockDecision.REVIEW
    assert PricingReasonCode.MANUAL_PRICE_BELOW_FLOOR.value in state.reason_codes


async def test_history_created_only_on_material_change():
    variant_id = await seed_variant()
    await seed_policy()
    await seed_inventory(variant_id)
    async with AsyncSessionLocal() as session:
        await recalculate_variant_pricing(session, variant_id, now=NOW)
        await recalculate_variant_pricing(session, variant_id, now=NOW + timedelta(minutes=1))
    assert await count(PricingDecisionHistory) == 1


async def test_supplier_price_update_recalc_changes_history():
    variant_id = await seed_variant()
    await seed_policy()
    _, offer_id = await seed_supplier_offer(variant_id, price=6300000)
    async with AsyncSessionLocal() as session:
        await recalculate_variant_pricing(session, variant_id, now=NOW)
        offer = await session.get(SupplierOffer, offer_id)
        offer.price_minor = 6200000
        offer.last_seen_at = NOW + timedelta(minutes=1)
        await session.commit()
        await recalculate_variant_pricing(session, variant_id, now=NOW + timedelta(minutes=1))
    assert await count(PricingDecisionHistory) == 2


async def test_default_policy_uniqueness_guard():
    await seed_policy(name="default-a")
    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError, match="Default"):
            await create_pricing_policy(session, name="default-b", is_default=True)


async def test_policy_update_audit():
    policy_id = await seed_policy()
    async with AsyncSessionLocal() as session:
        await update_pricing_policy(session, policy_id, {"markup_fixed_minor": 200000})
    assert await count(AuditLog) >= 1


async def test_bulk_recalculate():
    first = await seed_variant()
    second = await seed_variant()
    await seed_policy()
    await seed_inventory(first)
    await seed_supplier_offer(second)
    async with AsyncSessionLocal() as session:
        result = await recalculate_all_pricing(session)
    assert result["updated"] == 2


async def test_zero_stock_retains_own_cost_but_supplier_cost_used():
    variant_id = await seed_variant()
    await seed_policy()
    await seed_inventory(variant_id, stock=0, cost=6500000)
    await seed_supplier_offer(variant_id, price=6300000)
    async with AsyncSessionLocal() as session:
        state = await recalculate_variant_pricing(session, variant_id, now=NOW)
        inventory = await session.get(VariantInventoryState, variant_id)
    assert inventory.own_cost_minor == 6500000
    assert state.base_cost_minor == 6300000


async def test_restore_supplier_stock_active_again():
    variant_id = await seed_variant()
    await seed_policy()
    supplier_id, offer_id = await seed_supplier_offer(variant_id, availability=Availability.OUT_OF_STOCK)
    async with AsyncSessionLocal() as session:
        first = await recalculate_variant_pricing(session, variant_id, now=NOW)
        first_decision = first.stock_decision
        offer = await session.get(SupplierOffer, offer_id)
        offer.availability = Availability.IN_STOCK
        offer.last_seen_at = NOW
        await session.commit()
        second = await recalculate_variant_pricing(session, variant_id, now=NOW)
        second_decision = second.stock_decision
        second_supplier = second.pricing_supplier_id
    assert first_decision == StockDecision.OUT_OF_STOCK
    assert second_decision == StockDecision.ACTIVE
    assert second_supplier == supplier_id


async def test_api_pricing_flow(client):
    variant_id = await seed_variant()
    await seed_inventory(variant_id)
    policy = await client.post("/api/v1/pricing/policies", json={"name": "Default", "is_default": True, "minimum_profit_fixed_minor": 100000, "markup_fixed_minor": 100000})
    recalc = await client.post(f"/api/v1/pricing/variants/{variant_id}/recalculate")
    get_state = await client.get(f"/api/v1/pricing/variants/{variant_id}")
    history = await client.get(f"/api/v1/pricing/variants/{variant_id}/history")
    manual = await client.put(f"/api/v1/pricing/variants/{variant_id}/manual-price", json={"manual_price_minor": 7000000})
    clear = await client.delete(f"/api/v1/pricing/variants/{variant_id}/manual-price")
    bulk = await client.post("/api/v1/pricing/recalculate")
    assert policy.status_code == 201
    assert recalc.status_code == get_state.status_code == history.status_code == manual.status_code == clear.status_code == bulk.status_code == 200


async def test_pricing_e2e_sequence():
    variant_id = await seed_variant()
    await seed_policy(fixed_required_cost_minor=100000, minimum_profit_fixed_minor=100000, markup_fixed_minor=100000)
    await seed_inventory(variant_id, stock=1, cost=6500000)
    supplier_a, offer_a = await seed_supplier_offer(variant_id, price=6400000, supplier_code="a")
    supplier_b, offer_b = await seed_supplier_offer(variant_id, price=6300000, supplier_code="b")
    async with AsyncSessionLocal() as session:
        own = await recalculate_variant_pricing(session, variant_id, now=NOW)
        own_source = own.fulfillment_source
        inventory = await session.get(VariantInventoryState, variant_id)
        inventory.own_stock_total = 0
        await session.commit()
        supplier_b_selected = await recalculate_variant_pricing(session, variant_id, now=NOW)
        supplier_b_selected_id = supplier_b_selected.pricing_supplier_id
        offer_b_row = await session.get(SupplierOffer, offer_b)
        offer_b_row.availability = Availability.SUSPECT_MISSING
        await session.commit()
        supplier_a_selected = await recalculate_variant_pricing(session, variant_id, now=NOW)
        supplier_a_selected_id = supplier_a_selected.pricing_supplier_id
        offer_a_row = await session.get(SupplierOffer, offer_a)
        offer_a_row.availability = Availability.OUT_OF_STOCK
        offer_b_row.availability = Availability.OUT_OF_STOCK
        await session.commit()
        out = await recalculate_variant_pricing(session, variant_id, now=NOW)
        out_decision = out.stock_decision
        offer_b_row.availability = Availability.IN_STOCK
        offer_b_row.price_minor = 6250000
        offer_b_row.last_seen_at = NOW
        await session.commit()
        restored = await recalculate_variant_pricing(session, variant_id, now=NOW)
        restored_decision = restored.stock_decision
        restored_cost = restored.base_cost_minor
        await set_manual_price(session, variant_id, 7000000)
        manual_valid = await session.get(VariantPricingState, variant_id)
        manual_valid_price = manual_valid.final_price_minor
        await set_manual_price(session, variant_id, 6000000)
        manual_blocked = await session.get(VariantPricingState, variant_id)
        manual_blocked_decision = manual_blocked.stock_decision
    assert own_source == FulfillmentSource.OWN_STOCK
    assert supplier_b_selected_id == supplier_b
    assert supplier_a_selected_id == supplier_a
    assert out_decision == StockDecision.OUT_OF_STOCK
    assert restored_decision == StockDecision.ACTIVE
    assert restored_cost == 6250000
    assert manual_valid_price == 7000000
    assert manual_blocked_decision == StockDecision.REVIEW
