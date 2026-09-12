import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.models.enums import FulfillmentSource, PriceRoundingMode, PricingMode, StockDecision


@dataclass(frozen=True)
class PricingPolicyInput:
    id: uuid.UUID
    mode: PricingMode
    fixed_required_cost_minor: int = 0
    reserve_minor: int = 0
    avito_fixed_cost_minor: int = 0
    avito_percent_bps: int = 0
    minimum_profit_fixed_minor: int = 0
    minimum_profit_bps: int = 0
    markup_fixed_minor: int = 0
    markup_bps: int = 0
    margin_markup_minor: int = 0
    aggressive_markup_minor: int = 0
    clearance_markup_minor: int = 0
    rounding_step_minor: int = 10000
    rounding_mode: PriceRoundingMode = PriceRoundingMode.UP


@dataclass(frozen=True)
class InventoryInput:
    own_stock_total: int
    own_cost_minor: int | None
    source_updated_at: datetime | None = None


@dataclass(frozen=True)
class SupplierOfferInput:
    supplier_id: uuid.UUID
    price_minor: int
    availability: str
    last_seen_at: datetime
    has_open_conflict: bool = False


@dataclass(frozen=True)
class PricingOverrideInput:
    manual_mode_enabled: bool = False
    manual_price_minor: int | None = None


@dataclass(frozen=True)
class PricingDecision:
    policy_id: uuid.UUID
    pricing_mode: PricingMode
    fulfillment_source: FulfillmentSource
    pricing_supplier_id: uuid.UUID | None
    base_cost_minor: int | None
    required_costs_minor: int | None
    avito_costs_minor: int | None
    minimum_profit_minor: int | None
    hard_floor_minor: int | None
    markup_minor: int | None
    recommended_price_minor: int | None
    manual_price_minor: int | None
    final_price_minor: int | None
    stock_decision: StockDecision
    reason_codes: list[str] = field(default_factory=list)
    source_inventory_updated_at: datetime | None = None
    source_supplier_updated_at: datetime | None = None
    evidence: dict = field(default_factory=dict)
