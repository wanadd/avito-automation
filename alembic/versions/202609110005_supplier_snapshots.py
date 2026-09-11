"""add supplier snapshots and availability state fields

Revision ID: 202609110005
Revises: 202609110004
Create Date: 2026-09-11 00:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110005"
down_revision: str | None = "202609110004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

snapshot_type = postgresql.ENUM("FULL", "PARTIAL", name="supplier_snapshot_type", create_type=False)
snapshot_status = postgresql.ENUM("PENDING", "PROCESSING", "COMPLETED", "FAILED", "REJECTED", name="supplier_snapshot_status", create_type=False)
snapshot_item_status = postgresql.ENUM("SEEN", "REVIEW", "CONFLICT", "REJECTED", name="supplier_snapshot_item_status", create_type=False)
match_status = postgresql.ENUM("EXACT_MATCH", "AUTO_CREATED", "REVIEW", "REJECTED", "CONFLICT_BLOCKED", name="match_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    snapshot_type.create(bind, checkfirst=True)
    snapshot_status.create(bind, checkfirst=True)
    snapshot_item_status.create(bind, checkfirst=True)
    match_status.create(bind, checkfirst=True)

    op.create_table(
        "supplier_snapshots",
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_source_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_snapshot_id", sa.String(length=255), nullable=True),
        sa.Column("snapshot_type", snapshot_type, nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", snapshot_status, server_default="PENDING", nullable=False),
        sa.Column("total_lines", sa.Integer(), server_default="0", nullable=False),
        sa.Column("parsed_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matched_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("offers_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("conflicts_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("review_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("parser_error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("quality_gate_reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_source_record_id"], ["raw_source_records.id"], name=op.f("fk_supplier_snapshots_raw_source_record_id_raw_source_records"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_supplier_snapshots_source_id_sources"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name=op.f("fk_supplier_snapshots_supplier_id_suppliers"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_snapshots")),
        sa.UniqueConstraint("supplier_id", "source_id", "raw_source_record_id", name="uq_supplier_snapshots_raw_identity"),
    )
    op.create_index("ix_supplier_snapshots_supplier_id", "supplier_snapshots", ["supplier_id"])
    op.create_index("ix_supplier_snapshots_source_id", "supplier_snapshots", ["source_id"])
    op.create_index("ix_supplier_snapshots_captured_at", "supplier_snapshots", ["captured_at"])
    op.create_index("ix_supplier_snapshots_status", "supplier_snapshots", ["status"])

    op.add_column("supplier_offers", sa.Column("consecutive_missing_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("supplier_offers", sa.Column("last_seen_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("supplier_offers", sa.Column("last_missing_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("supplier_offers", sa.Column("last_availability_change_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("supplier_offers", sa.Column("last_processed_snapshot_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(op.f("fk_supplier_offers_last_seen_snapshot_id_supplier_snapshots"), "supplier_offers", "supplier_snapshots", ["last_seen_snapshot_id"], ["id"])
    op.create_foreign_key(op.f("fk_supplier_offers_last_missing_snapshot_id_supplier_snapshots"), "supplier_offers", "supplier_snapshots", ["last_missing_snapshot_id"], ["id"])

    op.create_table(
        "supplier_snapshot_items",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parsed_supplier_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_offer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_variant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("match_status", match_status, nullable=False),
        sa.Column("item_status", snapshot_item_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["parsed_supplier_item_id"], ["parsed_supplier_items.id"], name=op.f("fk_supplier_snapshot_items_parsed_supplier_item_id_parsed_supplier_items"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_variant_id"], ["product_variants.id"], name=op.f("fk_supplier_snapshot_items_product_variant_id_product_variants")),
        sa.ForeignKeyConstraint(["snapshot_id"], ["supplier_snapshots.id"], name=op.f("fk_supplier_snapshot_items_snapshot_id_supplier_snapshots"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_offer_id"], ["supplier_offers.id"], name=op.f("fk_supplier_snapshot_items_supplier_offer_id_supplier_offers")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_snapshot_items")),
        sa.UniqueConstraint("snapshot_id", "parsed_supplier_item_id", name="uq_supplier_snapshot_items_snapshot_parsed"),
    )
    op.create_index("ix_supplier_snapshot_items_snapshot_id", "supplier_snapshot_items", ["snapshot_id"])
    op.create_index("ix_supplier_snapshot_items_offer_id", "supplier_snapshot_items", ["supplier_offer_id"])


def downgrade() -> None:
    op.drop_index("ix_supplier_snapshot_items_offer_id", table_name="supplier_snapshot_items")
    op.drop_index("ix_supplier_snapshot_items_snapshot_id", table_name="supplier_snapshot_items")
    op.drop_table("supplier_snapshot_items")
    op.drop_constraint(op.f("fk_supplier_offers_last_missing_snapshot_id_supplier_snapshots"), "supplier_offers", type_="foreignkey")
    op.drop_constraint(op.f("fk_supplier_offers_last_seen_snapshot_id_supplier_snapshots"), "supplier_offers", type_="foreignkey")
    op.drop_column("supplier_offers", "last_processed_snapshot_at")
    op.drop_column("supplier_offers", "last_availability_change_at")
    op.drop_column("supplier_offers", "last_missing_snapshot_id")
    op.drop_column("supplier_offers", "last_seen_snapshot_id")
    op.drop_column("supplier_offers", "consecutive_missing_count")
    op.drop_index("ix_supplier_snapshots_status", table_name="supplier_snapshots")
    op.drop_index("ix_supplier_snapshots_captured_at", table_name="supplier_snapshots")
    op.drop_index("ix_supplier_snapshots_source_id", table_name="supplier_snapshots")
    op.drop_index("ix_supplier_snapshots_supplier_id", table_name="supplier_snapshots")
    op.drop_table("supplier_snapshots")
    bind = op.get_bind()
    match_status.drop(bind, checkfirst=True)
    snapshot_item_status.drop(bind, checkfirst=True)
    snapshot_status.drop(bind, checkfirst=True)
    snapshot_type.drop(bind, checkfirst=True)
