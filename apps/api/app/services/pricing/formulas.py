from app.models.enums import PriceRoundingMode, PricingMode, PricingReasonCode, StockDecision
from app.services.pricing.types import PricingDecision, PricingOverrideInput, PricingPolicyInput

BPS_DENOMINATOR = 10_000


def ceil_div(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return -(-numerator // denominator)


def bps_amount(base_minor: int, bps: int) -> int:
    return ceil_div(base_minor * bps, BPS_DENOMINATOR)


def round_price(price_minor: int, step_minor: int, mode: PriceRoundingMode) -> int:
    if step_minor <= 0:
        return price_minor
    remainder = price_minor % step_minor
    if remainder == 0:
        return price_minor
    if mode == PriceRoundingMode.NEAREST:
        down = price_minor - remainder
        up = down + step_minor
        return up if price_minor - down >= up - price_minor else down
    return price_minor + step_minor - remainder


def minimum_profit(base_cost_minor: int, policy: PricingPolicyInput) -> int:
    return max(policy.minimum_profit_fixed_minor, bps_amount(base_cost_minor, policy.minimum_profit_bps))


def automatic_markup(base_cost_minor: int, policy: PricingPolicyInput) -> int:
    base_markup = max(policy.markup_fixed_minor, bps_amount(base_cost_minor, policy.markup_bps))
    if policy.mode == PricingMode.MARGIN:
        return base_markup + policy.margin_markup_minor
    if policy.mode == PricingMode.AGGRESSIVE:
        return policy.aggressive_markup_minor
    if policy.mode == PricingMode.CLEARANCE:
        return policy.clearance_markup_minor
    return base_markup


def hard_floor(base_cost_minor: int, policy: PricingPolicyInput) -> tuple[int, int, int, int]:
    if policy.avito_percent_bps >= BPS_DENOMINATOR:
        raise ValueError("avito_percent_bps must be below 10000")
    required = policy.fixed_required_cost_minor + policy.reserve_minor
    profit = minimum_profit(base_cost_minor, policy)
    non_percent_floor = base_cost_minor + required + policy.avito_fixed_cost_minor + profit
    floor = ceil_div(non_percent_floor * BPS_DENOMINATOR, BPS_DENOMINATOR - policy.avito_percent_bps)
    avito_costs = policy.avito_fixed_cost_minor + bps_amount(floor, policy.avito_percent_bps)
    return floor, required, avito_costs, profit


def price_from_cost(
    *,
    base_cost_minor: int,
    policy: PricingPolicyInput,
    override: PricingOverrideInput,
    fulfillment_source,
    pricing_supplier_id,
    reasons: list[str],
    source_inventory_updated_at=None,
    source_supplier_updated_at=None,
    evidence=None,
) -> PricingDecision:
    try:
        floor, required, avito_costs, profit = hard_floor(base_cost_minor, policy)
    except ValueError:
        return PricingDecision(
            policy_id=policy.id,
            pricing_mode=policy.mode,
            fulfillment_source=fulfillment_source,
            pricing_supplier_id=pricing_supplier_id,
            base_cost_minor=base_cost_minor,
            required_costs_minor=None,
            avito_costs_minor=None,
            minimum_profit_minor=None,
            hard_floor_minor=None,
            markup_minor=None,
            recommended_price_minor=None,
            manual_price_minor=override.manual_price_minor,
            final_price_minor=None,
            stock_decision=StockDecision.REVIEW,
            reason_codes=[*reasons, PricingReasonCode.INVALID_PRICING_POLICY.value],
            source_inventory_updated_at=source_inventory_updated_at,
            source_supplier_updated_at=source_supplier_updated_at,
            evidence=evidence or {},
        )
    markup = automatic_markup(base_cost_minor, policy)
    recommended_raw = max(floor, base_cost_minor + required + avito_costs + profit + markup)
    recommended = max(floor, round_price(recommended_raw, policy.rounding_step_minor, policy.rounding_mode))
    final_price = recommended
    decision_reasons = list(reasons)
    if final_price == floor or recommended_raw < floor:
        decision_reasons.append(PricingReasonCode.HARD_FLOOR_APPLIED.value)
    if override.manual_mode_enabled:
        if override.manual_price_minor is None or override.manual_price_minor < floor:
            return PricingDecision(
                policy_id=policy.id,
                pricing_mode=PricingMode.MANUAL,
                fulfillment_source=fulfillment_source,
                pricing_supplier_id=pricing_supplier_id,
                base_cost_minor=base_cost_minor,
                required_costs_minor=required,
                avito_costs_minor=avito_costs,
                minimum_profit_minor=profit,
                hard_floor_minor=floor,
                markup_minor=markup,
                recommended_price_minor=recommended,
                manual_price_minor=override.manual_price_minor,
                final_price_minor=override.manual_price_minor,
                stock_decision=StockDecision.REVIEW,
                reason_codes=[*decision_reasons, PricingReasonCode.MANUAL_PRICE_BELOW_FLOOR.value],
                source_inventory_updated_at=source_inventory_updated_at,
                source_supplier_updated_at=source_supplier_updated_at,
                evidence=evidence or {},
            )
        final_price = override.manual_price_minor
        decision_reasons.append(PricingReasonCode.MANUAL_PRICE_APPLIED.value)
    return PricingDecision(
        policy_id=policy.id,
        pricing_mode=PricingMode.MANUAL if override.manual_mode_enabled else policy.mode,
        fulfillment_source=fulfillment_source,
        pricing_supplier_id=pricing_supplier_id,
        base_cost_minor=base_cost_minor,
        required_costs_minor=required,
        avito_costs_minor=avito_costs,
        minimum_profit_minor=profit,
        hard_floor_minor=floor,
        markup_minor=markup,
        recommended_price_minor=recommended,
        manual_price_minor=override.manual_price_minor if override.manual_mode_enabled else None,
        final_price_minor=final_price,
        stock_decision=StockDecision.ACTIVE,
        reason_codes=decision_reasons,
        source_inventory_updated_at=source_inventory_updated_at,
        source_supplier_updated_at=source_supplier_updated_at,
        evidence=evidence or {},
    )
