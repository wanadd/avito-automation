"""initial schema

Revision ID: 202609110001
Revises:
Create Date: 2026-09-11 00:01:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


source_type = postgresql.ENUM("TELEGRAM", "WEBSITE", "MANUAL", "IMPORT", name="source_type", create_type=False)
processing_status = postgresql.ENUM("NEW", "PARSED", "PARTIAL", "FAILED", name="processing_status", create_type=False)
product_condition = postgresql.ENUM("NEW", "USED", "REFURBISHED", name="product_condition", create_type=False)
availability = postgresql.ENUM(
    "IN_STOCK", "OUT_OF_STOCK", "UNKNOWN", "SUSPECT_MISSING", name="availability", create_type=False
)
review_status = postgresql.ENUM("PENDING", "ACCEPTED", "REJECTED", name="review_status", create_type=False)
conflict_status = postgresql.ENUM("OPEN", "RESOLVED", "IGNORED", name="conflict_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    source_type.create(bind, checkfirst=True)
    processing_status.create(bind, checkfirst=True)
    product_condition.create(bind, checkfirst=True)
    availability.create(bind, checkfirst=True)
    review_status.create(bind, checkfirst=True)
    conflict_status.create(bind, checkfirst=True)

    op.create_table(
        "suppliers",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
    )
    op.create_index(op.f("ix_suppliers_code"), "suppliers", ["code"], unique=True)

    op.create_table(
        "products",
        sa.Column("brand", sa.String(length=120), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("model_family", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
    )
    op.create_index(op.f("ix_products_brand"), "products", ["brand"], unique=False)
    op.create_index(op.f("ix_products_canonical_name"), "products", ["canonical_name"], unique=False)

    op.create_table(
        "sources",
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name=op.f("fk_sources_supplier_id_suppliers"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
    )

    op.create_table(
        "product_variants",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manufacturer_model_code", sa.String(length=120), nullable=True),
        sa.Column("ram_gb", sa.Integer(), nullable=True),
        sa.Column("storage_gb", sa.Integer(), nullable=True),
        sa.Column("color_raw", sa.String(length=120), nullable=True),
        sa.Column("color_normalized", sa.String(length=120), nullable=True),
        sa.Column("region_code", sa.String(length=32), nullable=True),
        sa.Column("condition", product_condition, nullable=False),
        sa.Column("canonical_key", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_product_variants_product_id_products"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_variants")),
    )
    op.create_index(op.f("ix_product_variants_canonical_key"), "product_variants", ["canonical_key"], unique=True)

    op.create_table(
        "raw_source_records",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_record_id", sa.String(length=255), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("processing_status", processing_status, server_default="NEW", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_raw_source_records_source_id_sources"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_source_records")),
    )
    op.create_index(op.f("ix_raw_source_records_content_hash"), "raw_source_records", ["content_hash"], unique=False)
    op.create_index("uq_raw_source_records_source_external_record", "raw_source_records", ["source_id", "external_record_id"], unique=True, postgresql_where=sa.text("external_record_id IS NOT NULL"))

    op.create_table(
        "product_aliases",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_variant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("(product_id IS NOT NULL AND product_variant_id IS NULL) OR (product_id IS NULL AND product_variant_id IS NOT NULL)", name=op.f("ck_product_aliases_exactly_one_product_target")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_product_aliases_product_id_products"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_variant_id"], ["product_variants.id"], name=op.f("fk_product_aliases_product_variant_id_product_variants"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_product_aliases_source_id_sources"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_aliases")),
        sa.UniqueConstraint("normalized_alias", "source_id", name="uq_product_aliases_normalized_source"),
    )
    op.create_index(op.f("ix_product_aliases_normalized_alias"), "product_aliases", ["normalized_alias"], unique=False)

    op.create_table(
        "supplier_offers",
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_sku", sa.String(length=120), nullable=True),
        sa.Column("supplier_title", sa.String(length=512), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), server_default="RUB", nullable=False),
        sa.Column("availability", availability, nullable=False),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_variant_id"], ["product_variants.id"], name=op.f("fk_supplier_offers_product_variant_id_product_variants"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_supplier_offers_source_id_sources")),
        sa.ForeignKeyConstraint(["source_record_id"], ["raw_source_records.id"], name=op.f("fk_supplier_offers_source_record_id_raw_source_records")),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name=op.f("fk_supplier_offers_supplier_id_suppliers"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_offers")),
    )
    op.create_index("ix_supplier_offers_variant_supplier", "supplier_offers", ["product_variant_id", "supplier_id"], unique=False)
    op.create_index("uq_supplier_offers_supplier_sku", "supplier_offers", ["supplier_id", "supplier_sku"], unique=True, postgresql_where=sa.text("supplier_sku IS NOT NULL"))

    op.create_table(
        "data_conflicts",
        sa.Column("conflict_type", sa.String(length=120), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_variant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_source_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", conflict_status, server_default="OPEN", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["product_variant_id"], ["product_variants.id"], name=op.f("fk_data_conflicts_product_variant_id_product_variants")),
        sa.ForeignKeyConstraint(["raw_source_record_id"], ["raw_source_records.id"], name=op.f("fk_data_conflicts_raw_source_record_id_raw_source_records")),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_data_conflicts_source_id_sources")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_conflicts")),
    )
    op.create_index(op.f("ix_data_conflicts_conflict_type"), "data_conflicts", ["conflict_type"], unique=False)

    op.create_table(
        "match_reviews",
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_offer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_variant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("status", review_status, server_default="PENDING", nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_variant_id"], ["product_variants.id"], name=op.f("fk_match_reviews_candidate_variant_id_product_variants")),
        sa.ForeignKeyConstraint(["source_record_id"], ["raw_source_records.id"], name=op.f("fk_match_reviews_source_record_id_raw_source_records")),
        sa.ForeignKeyConstraint(["supplier_offer_id"], ["supplier_offers.id"], name=op.f("fk_match_reviews_supplier_offer_id_supplier_offers")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_match_reviews")),
    )

    op.create_table(
        "supplier_offer_snapshots",
        sa.Column("supplier_offer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("availability", availability, nullable=False),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["source_record_id"], ["raw_source_records.id"], name=op.f("fk_supplier_offer_snapshots_source_record_id_raw_source_records")),
        sa.ForeignKeyConstraint(["supplier_offer_id"], ["supplier_offers.id"], name=op.f("fk_supplier_offer_snapshots_supplier_offer_id_supplier_offers"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_offer_snapshots")),
    )
    op.create_index("ix_supplier_offer_snapshots_offer_captured", "supplier_offer_snapshots", ["supplier_offer_id", "captured_at"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("entity_type", sa.String(length=120), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actor_type", sa.String(length=120), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_entity_id"), "audit_logs", ["entity_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_entity_type"), "audit_logs", ["entity_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_entity_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_entity_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_supplier_offer_snapshots_offer_captured", table_name="supplier_offer_snapshots")
    op.drop_table("supplier_offer_snapshots")
    op.drop_table("match_reviews")
    op.drop_index(op.f("ix_data_conflicts_conflict_type"), table_name="data_conflicts")
    op.drop_table("data_conflicts")
    op.drop_index("uq_supplier_offers_supplier_sku", table_name="supplier_offers")
    op.drop_index("ix_supplier_offers_variant_supplier", table_name="supplier_offers")
    op.drop_table("supplier_offers")
    op.drop_index(op.f("ix_product_aliases_normalized_alias"), table_name="product_aliases")
    op.drop_table("product_aliases")
    op.drop_index("uq_raw_source_records_source_external_record", table_name="raw_source_records")
    op.drop_index(op.f("ix_raw_source_records_content_hash"), table_name="raw_source_records")
    op.drop_table("raw_source_records")
    op.drop_index(op.f("ix_product_variants_canonical_key"), table_name="product_variants")
    op.drop_table("product_variants")
    op.drop_table("sources")
    op.drop_index(op.f("ix_products_canonical_name"), table_name="products")
    op.drop_index(op.f("ix_products_brand"), table_name="products")
    op.drop_table("products")
    op.drop_index(op.f("ix_suppliers_code"), table_name="suppliers")
    op.drop_table("suppliers")

    bind = op.get_bind()
    conflict_status.drop(bind, checkfirst=True)
    review_status.drop(bind, checkfirst=True)
    availability.drop(bind, checkfirst=True)
    product_condition.drop(bind, checkfirst=True)
    processing_status.drop(bind, checkfirst=True)
    source_type.drop(bind, checkfirst=True)
