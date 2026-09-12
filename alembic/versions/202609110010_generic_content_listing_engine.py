"""add generic content listing engine

Revision ID: 202609110010
Revises: 202609110009
Create Date: 2026-09-11 00:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110010"
down_revision: str | None = "202609110009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

content_draft_status = postgresql.ENUM("DRAFT", "GENERATED", "VALID", "REVIEW_REQUIRED", "APPROVED", "REJECTED", "SUPERSEDED", name="content_draft_status", create_type=False)
content_validation_status = postgresql.ENUM("NOT_VALIDATED", "VALID", "INVALID", "REVIEW_REQUIRED", name="content_validation_status", create_type=False)
image_asset_source_type = postgresql.ENUM("MANUAL_UPLOAD", "SUPPLIER", "PRODUCT_LIBRARY", "GENERATED", "OTHER", name="image_asset_source_type", create_type=False)
image_asset_status = postgresql.ENUM("READY", "INVALID", "DUPLICATE", name="image_asset_status", create_type=False)
image_set_status = postgresql.ENUM("DRAFT", "READY", "REVIEW_REQUIRED", "APPROVED", "SUPERSEDED", name="image_set_status", create_type=False)
generic_category = postgresql.ENUM("SMARTPHONE", "TABLET", "SMART_WATCH", "HEADPHONES", "LAPTOP", "POWER_STATION", "GENERATOR", "ACCESSORY", "OTHER", name="generic_category", create_type=False)
generic_listing_status = postgresql.ENUM("DRAFT", "READY", "REVIEW_REQUIRED", "NOT_READY", "APPROVED", "STALE", "REJECTED", name="generic_listing_status", create_type=False)
generic_readiness_status = postgresql.ENUM("NOT_READY", "REVIEW_REQUIRED", "READY", "APPROVED", "STALE", name="generic_readiness_status", create_type=False)
marketplace_readiness_status = postgresql.ENUM("DISABLED_CONTRACT_INCOMPLETE", name="marketplace_readiness_status", create_type=False)
product_condition = postgresql.ENUM("NEW", "USED", "REFURBISHED", name="product_condition", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (
        content_draft_status,
        content_validation_status,
        image_asset_source_type,
        image_asset_status,
        image_set_status,
        generic_category,
        generic_listing_status,
        generic_readiness_status,
        marketplace_readiness_status,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "product_content_facts",
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand", sa.String(length=120), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("model_code", sa.String(length=120), nullable=True),
        sa.Column("ram", sa.String(length=32), nullable=True),
        sa.Column("storage", sa.String(length=32), nullable=True),
        sa.Column("color", sa.String(length=120), nullable=True),
        sa.Column("region", sa.String(length=32), nullable=True),
        sa.Column("condition", product_condition, nullable=True),
        sa.Column("canonical_product_name", sa.String(length=255), nullable=True),
        sa.Column("canonical_variant_name", sa.String(length=512), nullable=True),
        sa.Column("known_attributes", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("warranty_status", sa.String(length=32), server_default="UNKNOWN", nullable=False),
        sa.Column("warranty_text", sa.Text(), nullable=True),
        sa.Column("package_contents_status", sa.String(length=32), server_default="UNKNOWN", nullable=False),
        sa.Column("package_contents", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("additional_facts", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("fact_sources", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("fact_hash", sa.String(length=64), nullable=False),
        sa.Column("completeness_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("has_conflicts", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("requires_review", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], name="fk_content_facts_variant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_content_facts")),
        sa.UniqueConstraint("variant_id", "fact_hash", name="uq_content_facts_variant_hash"),
    )
    op.create_index(op.f("ix_product_content_facts_variant_id"), "product_content_facts", ["variant_id"])
    op.create_index(op.f("ix_product_content_facts_fact_hash"), "product_content_facts", ["fact_hash"])
    op.create_index(op.f("ix_product_content_facts_requires_review"), "product_content_facts", ["requires_review"])
    op.create_index(op.f("ix_product_content_facts_has_conflicts"), "product_content_facts", ["has_conflicts"])

    op.create_table(
        "product_fact_overrides",
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field", sa.String(length=120), nullable=False),
        sa.Column("value", sa.String(length=512), nullable=False),
        sa.Column("operator", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], name="fk_fact_overrides_variant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_fact_overrides")),
        sa.UniqueConstraint("variant_id", "field", name="uq_fact_overrides_variant_field"),
    )
    op.create_index(op.f("ix_product_fact_overrides_variant_id"), "product_fact_overrides", ["variant_id"])
    op.create_index(op.f("ix_product_fact_overrides_field"), "product_fact_overrides", ["field"])

    op.create_table(
        "product_content_drafts",
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("facts_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", content_draft_status, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("title_generation_mode", sa.String(length=64), nullable=False),
        sa.Column("description_generation_mode", sa.String(length=64), nullable=False),
        sa.Column("generator", sa.String(length=120), nullable=False),
        sa.Column("generator_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("input_fact_hash", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("validation_status", content_validation_status, server_default="NOT_VALIDATED", nullable=False),
        sa.Column("validation_errors", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("validation_warnings", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("requires_review", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(length=512), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["facts_id"], ["product_content_facts.id"], name="fk_content_drafts_facts", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], name="fk_content_drafts_variant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_content_drafts")),
        sa.UniqueConstraint("variant_id", "input_fact_hash", "content_hash", name="uq_content_drafts_variant_input_content"),
    )
    for column in ("variant_id", "facts_id", "status", "input_fact_hash", "content_hash", "requires_review", "approved_at"):
        op.create_index(op.f(f"ix_product_content_drafts_{column}"), "product_content_drafts", [column])

    op.create_table(
        "product_image_assets",
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", image_asset_source_type, nullable=False),
        sa.Column("source_reference", sa.String(length=512), nullable=True),
        sa.Column("storage_path", sa.String(length=1024), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", image_asset_status, server_default="READY", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], name="fk_image_assets_variant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_image_assets")),
        sa.UniqueConstraint("variant_id", "sha256", name="uq_image_assets_variant_sha256"),
    )
    for column in ("variant_id", "sha256", "status"):
        op.create_index(op.f(f"ix_product_image_assets_{column}"), "product_image_assets", [column])

    op.create_table(
        "product_image_sets",
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", image_set_status, server_default="DRAFT", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("cover_image_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cover_image_id"], ["product_image_assets.id"], name="fk_image_sets_cover", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], name="fk_image_sets_variant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_image_sets")),
        sa.UniqueConstraint("variant_id", "content_hash", name="uq_image_sets_variant_hash"),
    )
    for column in ("variant_id", "status", "content_hash", "approved_at"):
        op.create_index(op.f(f"ix_product_image_sets_{column}"), "product_image_sets", [column])

    op.create_table(
        "product_image_set_items",
        sa.Column("image_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["image_asset_id"], ["product_image_assets.id"], name="fk_image_set_items_asset", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["image_set_id"], ["product_image_sets.id"], name="fk_image_set_items_set", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("image_set_id", "image_asset_id", name=op.f("pk_product_image_set_items")),
    )

    op.create_table(
        "generic_listing_drafts",
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("image_set_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pricing_state_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", generic_listing_status, nullable=False),
        sa.Column("generic_category", generic_category, server_default="OTHER", nullable=False),
        sa.Column("generic_attributes", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_minor", sa.Integer(), nullable=True),
        sa.Column("stock_decision", sa.String(length=64), nullable=True),
        sa.Column("fulfillment_source", sa.String(length=64), nullable=True),
        sa.Column("generic_readiness", generic_readiness_status, nullable=False),
        sa.Column("avito_readiness", marketplace_readiness_status, server_default="DISABLED_CONTRACT_INCOMPLETE", nullable=False),
        sa.Column("readiness_reasons", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["content_draft_id"], ["product_content_drafts.id"], name="fk_generic_listing_content_draft", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["image_set_id"], ["product_image_sets.id"], name="fk_generic_listing_image_set", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pricing_state_id"], ["variant_pricing_states.product_variant_id"], name="fk_generic_listing_pricing_state", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], name="fk_generic_listing_variant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generic_listing_drafts")),
        sa.UniqueConstraint("variant_id", "content_hash", name="uq_generic_listing_variant_hash"),
    )
    for column in ("variant_id", "content_draft_id", "image_set_id", "status", "generic_category", "generic_readiness", "content_hash", "approved_at"):
        op.create_index(op.f(f"ix_generic_listing_drafts_{column}"), "generic_listing_drafts", [column])


def downgrade() -> None:
    op.drop_table("generic_listing_drafts")
    op.drop_table("product_image_set_items")
    op.drop_table("product_image_sets")
    op.drop_table("product_image_assets")
    op.drop_table("product_content_drafts")
    op.drop_table("product_fact_overrides")
    op.drop_table("product_content_facts")
    bind = op.get_bind()
    for enum_type in (
        marketplace_readiness_status,
        generic_readiness_status,
        generic_listing_status,
        generic_category,
        image_set_status,
        image_asset_status,
        image_asset_source_type,
        content_validation_status,
        content_draft_status,
    ):
        enum_type.drop(bind, checkfirst=True)
