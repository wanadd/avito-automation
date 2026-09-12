import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import FulfillmentSource, PriceRoundingMode, PricingMode, StockDecision
from app.schemas.common import ORMModel


class PricingPolicyCreate(BaseModel):
    name: str
    is_default: bool = False
    mode: PricingMode = PricingMode.BALANCED
    fixed_required_cost_minor: int = Field(default=0, ge=0)
    reserve_minor: int = Field(default=0, ge=0)
    avito_fixed_cost_minor: int = Field(default=0, ge=0)
    avito_percent_bps: int = Field(default=0, ge=0, lt=10000)
    minimum_profit_fixed_minor: int = Field(default=0, ge=0)
    minimum_profit_bps: int = Field(default=0, ge=0)
    markup_fixed_minor: int = Field(default=0, ge=0)
    markup_bps: int = Field(default=0, ge=0)
    margin_markup_minor: int = Field(default=0, ge=0)
    aggressive_markup_minor: int = Field(default=0, ge=0)
    clearance_markup_minor: int = Field(default=0, ge=0)
    rounding_step_minor: int = Field(default=10000, ge=1)
    rounding_mode: PriceRoundingMode = PriceRoundingMode.UP
    enabled: bool = True


class PricingPolicyPatch(BaseModel):
    name: str | None = None
    is_default: bool | None = None
    mode: PricingMode | None = None
    fixed_required_cost_minor: int | None = Field(default=None, ge=0)
    reserve_minor: int | None = Field(default=None, ge=0)
    avito_fixed_cost_minor: int | None = Field(default=None, ge=0)
    avito_percent_bps: int | None = Field(default=None, ge=0, lt=10000)
    minimum_profit_fixed_minor: int | None = Field(default=None, ge=0)
    minimum_profit_bps: int | None = Field(default=None, ge=0)
    markup_fixed_minor: int | None = Field(default=None, ge=0)
    markup_bps: int | None = Field(default=None, ge=0)
    margin_markup_minor: int | None = Field(default=None, ge=0)
    aggressive_markup_minor: int | None = Field(default=None, ge=0)
    clearance_markup_minor: int | None = Field(default=None, ge=0)
    rounding_step_minor: int | None = Field(default=None, ge=1)
    rounding_mode: PriceRoundingMode | None = None
    enabled: bool | None = None


class PricingPolicyRead(ORMModel):
    id: uuid.UUID
    name: str
    is_default: bool
    mode: PricingMode
    fixed_required_cost_minor: int
    reserve_minor: int
    avito_fixed_cost_minor: int
    avito_percent_bps: int
    minimum_profit_fixed_minor: int
    minimum_profit_bps: int
    markup_fixed_minor: int
    markup_bps: int
    margin_markup_minor: int
    aggressive_markup_minor: int
    clearance_markup_minor: int
    rounding_step_minor: int
    rounding_mode: PriceRoundingMode
    enabled: bool
    created_at: datetime
    updated_at: datetime


class VariantPricingStateRead(ORMModel):
    product_variant_id: uuid.UUID
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
    reason_codes: list[str]
    calculated_at: datetime
    source_inventory_updated_at: datetime | None
    source_supplier_updated_at: datetime | None


class PricingDecisionHistoryRead(ORMModel):
    id: uuid.UUID
    product_variant_id: uuid.UUID
    policy_id: uuid.UUID
    pricing_supplier_id: uuid.UUID | None
    previous_final_price_minor: int | None
    base_cost_minor: int | None
    hard_floor_minor: int | None
    recommended_price_minor: int | None
    final_price_minor: int | None
    stock_decision: StockDecision
    reason_codes: list[str]
    evidence: dict
    created_at: datetime


class ManualPriceRequest(BaseModel):
    manual_price_minor: int = Field(ge=0)
    note: str | None = None


class BulkPricingResult(BaseModel):
    updated: int
