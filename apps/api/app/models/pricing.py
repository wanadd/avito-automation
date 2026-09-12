import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FulfillmentSource, PriceRoundingMode, PricingMode, StockDecision


class PricingPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pricing_policies"

    name: Mapped[str] = mapped_column(String(255), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    mode: Mapped[PricingMode] = mapped_column(Enum(PricingMode, name="pricing_mode"), default=PricingMode.BALANCED)
    fixed_required_cost_minor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reserve_minor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    avito_fixed_cost_minor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    avito_percent_bps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    minimum_profit_fixed_minor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    minimum_profit_bps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    markup_fixed_minor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    markup_bps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    margin_markup_minor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    aggressive_markup_minor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    clearance_markup_minor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rounding_step_minor: Mapped[int] = mapped_column(Integer, default=10000, server_default="10000")
    rounding_mode: Mapped[PriceRoundingMode] = mapped_column(
        Enum(PriceRoundingMode, name="price_rounding_mode"), default=PriceRoundingMode.UP, server_default=PriceRoundingMode.UP
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class VariantPricingOverride(TimestampMixin, Base):
    __tablename__ = "variant_pricing_overrides"

    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), primary_key=True
    )
    manual_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)


class VariantPricingState(Base):
    __tablename__ = "variant_pricing_states"

    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), primary_key=True
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pricing_policies.id"))
    pricing_mode: Mapped[PricingMode] = mapped_column(Enum(PricingMode, name="pricing_mode"))
    fulfillment_source: Mapped[FulfillmentSource] = mapped_column(Enum(FulfillmentSource, name="fulfillment_source"))
    pricing_supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    base_cost_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_costs_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avito_costs_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minimum_profit_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hard_floor_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    markup_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_decision: Mapped[StockDecision] = mapped_column(Enum(StockDecision, name="stock_decision"))
    reason_codes: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_inventory_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_supplier_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    variant = relationship("ProductVariant")
    policy = relationship("PricingPolicy")


class PricingDecisionHistory(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pricing_decision_history"

    product_variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id"))
    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pricing_policies.id"))
    pricing_supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    previous_final_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_cost_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hard_floor_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_decision: Mapped[StockDecision] = mapped_column(Enum(StockDecision, name="stock_decision"))
    reason_codes: Mapped[list] = mapped_column(JSONB)
    evidence: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
