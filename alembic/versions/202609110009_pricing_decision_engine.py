"""add pricing decision engine

Revision ID: 202609110009
Revises: 202609110008
Create Date: 2026-09-11 00:09:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110009"
down_revision: str | None = "202609110008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

pricing_mode = postgresql.ENUM("BALANCED", "MARGIN", "AGGRESSIVE", "CLEARANCE", "MANUAL", name="pricing_mode", create_type=False)
fulfillment_source = postgresql.ENUM("OWN_STOCK", "SUPPLIER", "NONE", name="fulfillment_source", create_type=False)
stock_decision = postgresql.ENUM("ACTIVE", "PAUSE", "OUT_OF_STOCK", "REVIEW", name="stock_decision", create_type=False)
rounding_mode = postgresql.ENUM("UP", "NEAREST", name="price_rounding_mode", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    pricing_mode.create(bind, checkfirst=True)
    fulfillment_source.create(bind, checkfirst=True)
    stock_decision.create(bind, checkfirst=True)
    rounding_mode.create(bind, checkfirst=True)

    op.create_table(
        "pricing_policies",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("mode", pricing_mode, nullable=False),
        sa.Column("fixed_required_cost_minor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reserve_minor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("avito_fixed_cost_minor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("avito_percent_bps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("minimum_profit_fixed_minor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("minimum_profit_bps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("markup_fixed_minor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("markup_bps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("margin_markup_minor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("aggressive_markup_minor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("clearance_markup_minor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rounding_step_minor", sa.Integer(), server_default="10000", nullable=False),
        sa.Column("rounding_mode", rounding_mode, server_default="UP", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_policies")),
        sa.UniqueConstraint("name", name=op.f("uq_pricing_policies_name")),
    )
    op.create_index("uq_pricing_policies_one_default", "pricing_policies", ["is_default"], unique=True, postgresql_where=sa.text("is_default AND enabled"))

    op.create_table(
        "variant_pricing_overrides",
        sa.Column("product_variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manual_price_minor", sa.Integer(), nullable=True),
        sa.Column("manual_mode_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_variant_id"], ["product_variants.id"], name="fk_pricing_overrides_variant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("product_variant_id", name=op.f("pk_variant_pricing_overrides")),
    )

    op.create_table(
        "variant_pricing_states",
        sa.Column("product_variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pricing_mode", pricing_mode, nullable=False),
        sa.Column("fulfillment_source", fulfillment_source, nullable=False),
        sa.Column("pricing_supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("base_cost_minor", sa.Integer(), nullable=True),
        sa.Column("required_costs_minor", sa.Integer(), nullable=True),
        sa.Column("avito_costs_minor", sa.Integer(), nullable=True),
        sa.Column("minimum_profit_minor", sa.Integer(), nullable=True),
        sa.Column("hard_floor_minor", sa.Integer(), nullable=True),
        sa.Column("markup_minor", sa.Integer(), nullable=True),
        sa.Column("recommended_price_minor", sa.Integer(), nullable=True),
        sa.Column("manual_price_minor", sa.Integer(), nullable=True),
        sa.Column("final_price_minor", sa.Integer(), nullable=True),
        sa.Column("stock_decision", stock_decision, nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source_inventory_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_supplier_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["policy_id"], ["pricing_policies.id"], name="fk_pricing_states_policy"),
        sa.ForeignKeyConstraint(["pricing_supplier_id"], ["suppliers.id"], name="fk_pricing_states_supplier"),
        sa.ForeignKeyConstraint(["product_variant_id"], ["product_variants.id"], name="fk_pricing_states_variant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("product_variant_id", name=op.f("pk_variant_pricing_states")),
    )

    op.create_table(
        "pricing_decision_history",
        sa.Column("product_variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pricing_supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("previous_final_price_minor", sa.Integer(), nullable=True),
        sa.Column("base_cost_minor", sa.Integer(), nullable=True),
        sa.Column("hard_floor_minor", sa.Integer(), nullable=True),
        sa.Column("recommended_price_minor", sa.Integer(), nullable=True),
        sa.Column("final_price_minor", sa.Integer(), nullable=True),
        sa.Column("stock_decision", stock_decision, nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["pricing_policies.id"], name="fk_pricing_history_policy"),
        sa.ForeignKeyConstraint(["pricing_supplier_id"], ["suppliers.id"], name="fk_pricing_history_supplier"),
        sa.ForeignKeyConstraint(["product_variant_id"], ["product_variants.id"], name="fk_pricing_history_variant"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_decision_history")),
    )


def downgrade() -> None:
    op.drop_table("pricing_decision_history")
    op.drop_table("variant_pricing_states")
    op.drop_table("variant_pricing_overrides")
    op.drop_index("uq_pricing_policies_one_default", table_name="pricing_policies")
    op.drop_table("pricing_policies")
    bind = op.get_bind()
    rounding_mode.drop(bind, checkfirst=True)
    stock_decision.drop(bind, checkfirst=True)
    fulfillment_source.drop(bind, checkfirst=True)
    pricing_mode.drop(bind, checkfirst=True)
