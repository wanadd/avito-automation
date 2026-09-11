"""add parsed supplier items

Revision ID: 202609110002
Revises: 202609110001
Create Date: 2026-09-11 00:02:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110002"
down_revision: str | None = "202609110001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

parse_status = postgresql.ENUM("PARSED", "PARTIAL", "REVIEW", "CONFLICT", "IGNORED", name="parse_status", create_type=False)
product_condition = postgresql.ENUM("NEW", "USED", "REFURBISHED", name="product_condition", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    parse_status.create(bind, checkfirst=True)

    op.create_table(
        "parsed_supplier_items",
        sa.Column("raw_source_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("raw_line", sa.Text(), nullable=False),
        sa.Column("section_raw", sa.String(length=255), nullable=True),
        sa.Column("section_normalized", sa.String(length=120), nullable=True),
        sa.Column("brand_raw", sa.String(length=120), nullable=True),
        sa.Column("brand_normalized", sa.String(length=120), nullable=True),
        sa.Column("model_raw", sa.String(length=255), nullable=True),
        sa.Column("model_normalized", sa.String(length=255), nullable=True),
        sa.Column("manufacturer_model_code", sa.String(length=120), nullable=True),
        sa.Column("ram_gb", sa.Integer(), nullable=True),
        sa.Column("storage_gb", sa.Integer(), nullable=True),
        sa.Column("color_raw", sa.String(length=120), nullable=True),
        sa.Column("color_normalized", sa.String(length=120), nullable=True),
        sa.Column("region_raw", sa.String(length=32), nullable=True),
        sa.Column("region_code", sa.String(length=32), nullable=True),
        sa.Column("condition", product_condition, nullable=True),
        sa.Column("price_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), server_default="RUB", nullable=False),
        sa.Column("parse_confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("parse_status", parse_status, nullable=False),
        sa.Column("parse_flags", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("parsed_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parsed_identity_key", sa.String(length=768), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_source_record_id"], ["raw_source_records.id"], name=op.f("fk_parsed_supplier_items_raw_source_record_id_raw_source_records"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_parsed_supplier_items_source_id_sources"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name=op.f("fk_parsed_supplier_items_supplier_id_suppliers"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parsed_supplier_items")),
    )
    op.create_index("ix_parsed_supplier_items_raw_line", "parsed_supplier_items", ["raw_source_record_id", "line_number"], unique=False)
    op.create_index("ix_parsed_supplier_items_identity", "parsed_supplier_items", ["raw_source_record_id", "parsed_identity_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_parsed_supplier_items_identity", table_name="parsed_supplier_items")
    op.drop_index("ix_parsed_supplier_items_raw_line", table_name="parsed_supplier_items")
    op.drop_table("parsed_supplier_items")
    parse_status.drop(op.get_bind(), checkfirst=True)
