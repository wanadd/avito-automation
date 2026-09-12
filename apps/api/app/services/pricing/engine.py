import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.conflict import DataConflict
from app.models.enums import (
    Availability,
    ConflictStatus,
    FulfillmentSource,
    PricingMode,
    PricingReasonCode,
    StockDecision,
)
from app.models.one_c import VariantInventoryState
from app.models.pricing import PricingDecisionHistory, PricingPolicy, VariantPricingOverride, VariantPricingState
from app.models.product import ProductVariant
from app.models.supplier_offer import SupplierOffer
from app.services.pricing.formulas import price_from_cost
from app.services.pricing.types import InventoryInput, PricingDecision, PricingOverrideInput, PricingPolicyInput, SupplierOfferInput


async def create_pricing_policy(session: AsyncSession, **values) -> PricingPolicy:
    policy = PricingPolicy(**values)
    if policy.is_default:
        existing = await default_policy(session)
        if existing is not None:
            raise ValueError("Default pricing policy already exists")
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy


async def update_pricing_policy(session: AsyncSession, policy_id: uuid.UUID, values: dict) -> PricingPolicy:
    policy = await session.get(PricingPolicy, policy_id)
    if policy is None:
        raise ValueError("PricingPolicy not found")
    if values.get("is_default") is True and not policy.is_default:
        existing = await default_policy(session)
        if existing is not None:
            raise ValueError("Default pricing policy already exists")
    old = policy_snapshot(policy)
    for key, value in values.items():
        if value is not None:
            setattr(policy, key, value)
    session.add(AuditLog(entity_type="PricingPolicy", entity_id=policy.id, action="PRICING_POLICY_CHANGED", old_value=old, new_value=json_safe(values), actor_type="USER"))
    await session.commit()
    await session.refresh(policy)
    return policy


async def default_policy(session: AsyncSession) -> PricingPolicy | None:
    return await session.scalar(select(PricingPolicy).where(PricingPolicy.enabled.is_(True), PricingPolicy.is_default.is_(True)))


async def get_or_create_default_policy(session: AsyncSession) -> PricingPolicy:
    policy = await default_policy(session)
    if policy:
        return policy
    return await create_pricing_policy(
        session,
        name="Default",
        is_default=True,
        mode=PricingMode.BALANCED,
        minimum_profit_fixed_minor=100000,
        markup_bps=500,
    )


async def recalculate_variant_pricing(
    session: AsyncSession,
    variant_id: uuid.UUID,
    *,
    policy: PricingPolicy | None = None,
    now: datetime | None = None,
) -> VariantPricingState:
    now = now or datetime.now(UTC)
    variant = await session.get(ProductVariant, variant_id)
    if variant is None:
        raise ValueError("ProductVariant not found")
    policy = policy or await get_or_create_default_policy(session)
    override = await session.get(VariantPricingOverride, variant_id)
    decision = await build_decision(session, variant_id, policy, override, now=now)
    state = await persist_decision(session, variant_id, decision, now)
    return state


async def recalculate_all_pricing(session: AsyncSession, *, limit: int = 1000) -> dict:
    variants = list(await session.scalars(select(ProductVariant).order_by(ProductVariant.created_at).limit(limit)))
    updated = 0
    for variant in variants:
        await recalculate_variant_pricing(session, variant.id)
        updated += 1
    return {"updated": updated}


async def build_decision(
    session: AsyncSession,
    variant_id: uuid.UUID,
    policy: PricingPolicy,
    override: VariantPricingOverride | None,
    *,
    now: datetime,
) -> PricingDecision:
    inventory = await session.get(VariantInventoryState, variant_id)
    policy_input = policy_to_input(policy)
    override_input = override_to_input(override)
    if inventory and inventory.own_stock_total > 0:
        if inventory.own_cost_minor is None:
            return inactive_decision(policy_input, override_input, FulfillmentSource.OWN_STOCK, StockDecision.REVIEW, [PricingReasonCode.OWN_COST_MISSING.value], inventory)
        return price_from_cost(
            base_cost_minor=inventory.own_cost_minor,
            policy=policy_input,
            override=override_input,
            fulfillment_source=FulfillmentSource.OWN_STOCK,
            pricing_supplier_id=None,
            reasons=[PricingReasonCode.OWN_STOCK_AVAILABLE.value],
            source_inventory_updated_at=inventory.source_updated_at,
            evidence={"own_stock_total": inventory.own_stock_total, "own_cost_minor": inventory.own_cost_minor},
        )

    supplier_inputs, stale_seen, conflict_seen = await supplier_candidates(session, variant_id, now)
    if supplier_inputs:
        selected = sorted(supplier_inputs, key=lambda offer: (offer.price_minor, -offer.last_seen_at.timestamp(), str(offer.supplier_id)))[0]
        return price_from_cost(
            base_cost_minor=selected.price_minor,
            policy=policy_input,
            override=override_input,
            fulfillment_source=FulfillmentSource.SUPPLIER,
            pricing_supplier_id=selected.supplier_id,
            reasons=[PricingReasonCode.SUPPLIER_STOCK_AVAILABLE.value, PricingReasonCode.SUPPLIER_SELECTED_LOWEST_PRICE.value],
            source_inventory_updated_at=inventory.source_updated_at if inventory else None,
            source_supplier_updated_at=selected.last_seen_at,
            evidence={"supplier_id": str(selected.supplier_id), "supplier_price_minor": selected.price_minor},
        )
    if conflict_seen:
        return inactive_decision(policy_input, override_input, FulfillmentSource.NONE, StockDecision.REVIEW, [PricingReasonCode.SUPPLIER_CONFLICT.value], inventory)
    if stale_seen:
        return inactive_decision(policy_input, override_input, FulfillmentSource.NONE, StockDecision.PAUSE, [PricingReasonCode.SUPPLIER_OFFER_STALE.value], inventory)
    return inactive_decision(policy_input, override_input, FulfillmentSource.NONE, StockDecision.OUT_OF_STOCK, [PricingReasonCode.NO_AVAILABLE_STOCK.value], inventory)


async def supplier_candidates(session: AsyncSession, variant_id: uuid.UUID, now: datetime) -> tuple[list[SupplierOfferInput], bool, bool]:
    freshness_cutoff = now - timedelta(minutes=get_settings().supplier_offer_freshness_minutes)
    offers = list(await session.scalars(select(SupplierOffer).where(SupplierOffer.product_variant_id == variant_id)))
    candidates: list[SupplierOfferInput] = []
    stale_seen = False
    conflict_seen = False
    for offer in offers:
        if offer.availability != Availability.IN_STOCK:
            continue
        if await offer_has_open_conflict(session, offer):
            conflict_seen = True
            continue
        if offer.last_seen_at < freshness_cutoff:
            stale_seen = True
            continue
        candidates.append(SupplierOfferInput(offer.supplier_id, offer.price_minor, offer.availability.value, offer.last_seen_at))
    return candidates, stale_seen, conflict_seen


async def offer_has_open_conflict(session: AsyncSession, offer: SupplierOffer) -> bool:
    conflict = await session.scalar(
        select(DataConflict).where(
            DataConflict.status == ConflictStatus.OPEN,
            DataConflict.product_variant_id == offer.product_variant_id,
            or_(
                DataConflict.source_id == offer.source_id,
                DataConflict.details["supplier_id"].astext == str(offer.supplier_id),
            ),
        )
    )
    return conflict is not None


def inactive_decision(policy: PricingPolicyInput, override: PricingOverrideInput, source: FulfillmentSource, stock_decision: StockDecision, reasons: list[str], inventory=None) -> PricingDecision:
    return PricingDecision(
        policy_id=policy.id,
        pricing_mode=PricingMode.MANUAL if override.manual_mode_enabled else policy.mode,
        fulfillment_source=source,
        pricing_supplier_id=None,
        base_cost_minor=None,
        required_costs_minor=None,
        avito_costs_minor=None,
        minimum_profit_minor=None,
        hard_floor_minor=None,
        markup_minor=None,
        recommended_price_minor=None,
        manual_price_minor=override.manual_price_minor if override.manual_mode_enabled else None,
        final_price_minor=None,
        stock_decision=stock_decision,
        reason_codes=reasons,
        source_inventory_updated_at=inventory.source_updated_at if inventory else None,
        evidence={},
    )


async def persist_decision(session: AsyncSession, variant_id: uuid.UUID, decision: PricingDecision, calculated_at: datetime) -> VariantPricingState:
    state = await session.get(VariantPricingState, variant_id)
    changed = state is None or material_snapshot(state) != decision_snapshot(decision)
    previous_price = state.final_price_minor if state else None
    if state is None:
        state = VariantPricingState(product_variant_id=variant_id, policy_id=decision.policy_id)
        session.add(state)
    state.policy_id = decision.policy_id
    state.pricing_mode = decision.pricing_mode
    state.fulfillment_source = decision.fulfillment_source
    state.pricing_supplier_id = decision.pricing_supplier_id
    state.base_cost_minor = decision.base_cost_minor
    state.required_costs_minor = decision.required_costs_minor
    state.avito_costs_minor = decision.avito_costs_minor
    state.minimum_profit_minor = decision.minimum_profit_minor
    state.hard_floor_minor = decision.hard_floor_minor
    state.markup_minor = decision.markup_minor
    state.recommended_price_minor = decision.recommended_price_minor
    state.manual_price_minor = decision.manual_price_minor
    state.final_price_minor = decision.final_price_minor
    state.stock_decision = decision.stock_decision
    state.reason_codes = decision.reason_codes
    state.calculated_at = calculated_at
    state.source_inventory_updated_at = decision.source_inventory_updated_at
    state.source_supplier_updated_at = decision.source_supplier_updated_at
    if changed:
        session.add(
            PricingDecisionHistory(
                product_variant_id=variant_id,
                policy_id=decision.policy_id,
                pricing_supplier_id=decision.pricing_supplier_id,
                previous_final_price_minor=previous_price,
                base_cost_minor=decision.base_cost_minor,
                hard_floor_minor=decision.hard_floor_minor,
                recommended_price_minor=decision.recommended_price_minor,
                final_price_minor=decision.final_price_minor,
                stock_decision=decision.stock_decision,
                reason_codes=decision.reason_codes,
                evidence=decision.evidence,
            )
        )
        session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action="PRICING_RECALCULATED", old_value={"final_price_minor": previous_price}, new_value=decision_snapshot(decision), actor_type="SYSTEM"))
    await session.commit()
    await session.refresh(state)
    return state


async def set_manual_price(session: AsyncSession, variant_id: uuid.UUID, manual_price_minor: int, note: str | None = None) -> VariantPricingOverride:
    override = await session.get(VariantPricingOverride, variant_id)
    if override is None:
        override = VariantPricingOverride(product_variant_id=variant_id)
    old = {"manual_price_minor": override.manual_price_minor, "manual_mode_enabled": override.manual_mode_enabled}
    override.manual_price_minor = manual_price_minor
    override.manual_mode_enabled = True
    override.note = note
    session.add(override)
    session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action="PRICING_MANUAL_OVERRIDE_SET", old_value=old, new_value={"manual_price_minor": manual_price_minor}, actor_type="USER"))
    await session.commit()
    await session.refresh(override)
    await recalculate_variant_pricing(session, variant_id)
    return override


async def clear_manual_price(session: AsyncSession, variant_id: uuid.UUID) -> None:
    override = await session.get(VariantPricingOverride, variant_id)
    if override is None:
        return
    old = {"manual_price_minor": override.manual_price_minor, "manual_mode_enabled": override.manual_mode_enabled}
    await session.delete(override)
    session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action="PRICING_MANUAL_OVERRIDE_REMOVED", old_value=old, new_value=None, actor_type="USER"))
    await session.commit()
    await recalculate_variant_pricing(session, variant_id)


def policy_to_input(policy: PricingPolicy) -> PricingPolicyInput:
    return PricingPolicyInput(
        id=policy.id,
        mode=policy.mode,
        fixed_required_cost_minor=policy.fixed_required_cost_minor,
        reserve_minor=policy.reserve_minor,
        avito_fixed_cost_minor=policy.avito_fixed_cost_minor,
        avito_percent_bps=policy.avito_percent_bps,
        minimum_profit_fixed_minor=policy.minimum_profit_fixed_minor,
        minimum_profit_bps=policy.minimum_profit_bps,
        markup_fixed_minor=policy.markup_fixed_minor,
        markup_bps=policy.markup_bps,
        margin_markup_minor=policy.margin_markup_minor,
        aggressive_markup_minor=policy.aggressive_markup_minor,
        clearance_markup_minor=policy.clearance_markup_minor,
        rounding_step_minor=policy.rounding_step_minor,
        rounding_mode=policy.rounding_mode,
    )


def override_to_input(override: VariantPricingOverride | None) -> PricingOverrideInput:
    return PricingOverrideInput(
        manual_mode_enabled=override.manual_mode_enabled if override else False,
        manual_price_minor=override.manual_price_minor if override else None,
    )


def policy_snapshot(policy: PricingPolicy) -> dict:
    return json_safe({key: getattr(policy, key) for key in ("name", "is_default", "mode", "enabled")})


def json_safe(value):
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def material_snapshot(state: VariantPricingState) -> dict:
    return {
        "policy_id": str(state.policy_id),
        "pricing_mode": state.pricing_mode.value,
        "fulfillment_source": state.fulfillment_source.value,
        "pricing_supplier_id": str(state.pricing_supplier_id) if state.pricing_supplier_id else None,
        "base_cost_minor": state.base_cost_minor,
        "hard_floor_minor": state.hard_floor_minor,
        "recommended_price_minor": state.recommended_price_minor,
        "manual_price_minor": state.manual_price_minor,
        "final_price_minor": state.final_price_minor,
        "stock_decision": state.stock_decision.value,
        "reason_codes": sorted(state.reason_codes),
    }


def decision_snapshot(decision: PricingDecision) -> dict:
    return {
        "policy_id": str(decision.policy_id),
        "pricing_mode": decision.pricing_mode.value,
        "fulfillment_source": decision.fulfillment_source.value,
        "pricing_supplier_id": str(decision.pricing_supplier_id) if decision.pricing_supplier_id else None,
        "base_cost_minor": decision.base_cost_minor,
        "hard_floor_minor": decision.hard_floor_minor,
        "recommended_price_minor": decision.recommended_price_minor,
        "manual_price_minor": decision.manual_price_minor,
        "final_price_minor": decision.final_price_minor,
        "stock_decision": decision.stock_decision.value,
        "reason_codes": sorted(decision.reason_codes),
    }
