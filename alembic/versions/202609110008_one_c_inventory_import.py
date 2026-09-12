"""add one c read only inventory import

Revision ID: 202609110008
Revises: 202609110007
Create Date: 2026-09-11 00:08:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110008"
down_revision: str | None = "202609110007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

item_status = postgresql.ENUM("MATCHED", "UNMATCHED", "AMBIGUOUS", "IGNORED", name="one_c_item_match_status", create_type=False)
item_strategy = postgresql.ENUM(
    "MANUAL", "INTERNAL_CODE", "BARCODE_EXACT", "SKU_EXACT", "MODEL_CODE_EXACT", "NAME_EXACT", "FUZZY_NAME",
    name="one_c_item_match_strategy",
    create_type=False,
)
run_status = postgresql.ENUM(
    "PENDING", "PROCESSING", "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "REJECTED", "DUPLICATE",
    name="one_c_import_run_status",
    create_type=False,
)
import_mode = postgresql.ENUM("FULL", "PARTIAL", name="one_c_import_mode", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    item_status.create(bind, checkfirst=True)
    item_strategy.create(bind, checkfirst=True)
    run_status.create(bind, checkfirst=True)
    import_mode.create(bind, checkfirst=True)
    op.execute("ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'ONE_C'")

    op.create_table(
        "one_c_items",
        sa.Column("internal_code", sa.String(length=120), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("barcode", sa.String(length=255), nullable=True),
        sa.Column("raw_name", sa.String(length=512), nullable=False),
        sa.Column("normalized_name", sa.String(length=512), nullable=False),
        sa.Column("matched_variant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("match_status", item_status, server_default="UNMATCHED", nullable=False),
        sa.Column("match_strategy", item_strategy, nullable=True),
        sa.Column("match_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("explicit_mapping", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["matched_variant_id"], ["product_variants.id"], name="fk_one_c_items_matched_variant", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_one_c_items")),
        sa.UniqueConstraint("internal_code", name="uq_one_c_items_internal_code"),
    )
    op.create_index("ix_one_c_items_internal_code", "one_c_items", ["internal_code"])
    op.create_index("ix_one_c_items_sku", "one_c_items", ["sku"])
    op.create_index("ix_one_c_items_barcode", "one_c_items", ["barcode"])
    op.create_index("ix_one_c_items_normalized_name", "one_c_items", ["normalized_name"])

    op.create_table(
        "one_c_import_runs",
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", run_status, server_default="PENDING", nullable=False),
        sa.Column("mode", import_mode, nullable=False),
        sa.Column("dry_run", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invalid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matched_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unmatched_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ambiguous_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("would_update_stock", sa.Integer(), server_default="0", nullable=False),
        sa.Column("would_update_cost", sa.Integer(), server_default="0", nullable=False),
        sa.Column("would_zero_missing", sa.Integer(), server_default="0", nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_one_c_import_runs")),
    )
    op.create_index("ix_one_c_import_runs_file_hash", "one_c_import_runs", ["file_hash"])

    op.create_table(
        "variant_inventory_states",
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("own_stock_total", sa.Integer(), nullable=False),
        sa.Column("own_cost_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_import_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["last_import_run_id"], ["one_c_import_runs.id"], name="fk_inventory_state_run"),
        sa.ForeignKeyConstraint(["source_item_id"], ["one_c_items.id"], name="fk_inventory_state_source_item"),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], name="fk_inventory_state_variant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("variant_id", name=op.f("pk_variant_inventory_states")),
    )

    op.create_table(
        "variant_stock_snapshots",
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stock_total", sa.Integer(), nullable=False),
        sa.Column("stock_by_store", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["import_run_id"], ["one_c_import_runs.id"], name="fk_stock_snapshots_run"),
        sa.ForeignKeyConstraint(["source_item_id"], ["one_c_items.id"], name="fk_stock_snapshots_source_item"),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], name="fk_stock_snapshots_variant"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_variant_stock_snapshots")),
    )

    op.create_table(
        "variant_cost_snapshots",
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cost_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["import_run_id"], ["one_c_import_runs.id"], name="fk_cost_snapshots_run"),
        sa.ForeignKeyConstraint(["source_item_id"], ["one_c_items.id"], name="fk_cost_snapshots_source_item"),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], name="fk_cost_snapshots_variant"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_variant_cost_snapshots")),
    )


def downgrade() -> None:
    op.drop_table("variant_cost_snapshots")
    op.drop_table("variant_stock_snapshots")
    op.drop_table("variant_inventory_states")
    op.drop_index("ix_one_c_import_runs_file_hash", table_name="one_c_import_runs")
    op.drop_table("one_c_import_runs")
    op.drop_index("ix_one_c_items_normalized_name", table_name="one_c_items")
    op.drop_index("ix_one_c_items_barcode", table_name="one_c_items")
    op.drop_index("ix_one_c_items_sku", table_name="one_c_items")
    op.drop_index("ix_one_c_items_internal_code", table_name="one_c_items")
    op.drop_table("one_c_items")
    bind = op.get_bind()
    import_mode.drop(bind, checkfirst=True)
    run_status.drop(bind, checkfirst=True)
    item_strategy.drop(bind, checkfirst=True)
    item_status.drop(bind, checkfirst=True)
