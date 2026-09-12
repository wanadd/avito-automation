import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ContentDraftStatus,
    ContentValidationStatus,
    GenericCategory,
    GenericListingStatus,
    GenericReadinessStatus,
    ImageAssetSourceType,
    ImageAssetStatus,
    ImageSetStatus,
    MarketplaceReadinessStatus,
    ProductCondition,
)


class ProductContentFacts(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_content_facts"
    __table_args__ = (UniqueConstraint("variant_id", "fact_hash", name="uq_content_facts_variant_hash"),)

    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ram: Mapped[str | None] = mapped_column(String(32), nullable=True)
    storage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    color: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)
    condition: Mapped[ProductCondition | None] = mapped_column(Enum(ProductCondition, name="product_condition"), nullable=True)
    canonical_product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_variant_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    known_attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    warranty_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", server_default="UNKNOWN")
    warranty_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_contents_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", server_default="UNKNOWN")
    package_contents: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    additional_facts: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    fact_sources: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    fact_hash: Mapped[str] = mapped_column(String(64), index=True)
    completeness_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    has_conflicts: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)

    variant = relationship("ProductVariant")


class ProductContentDraft(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_content_drafts"
    __table_args__ = (UniqueConstraint("variant_id", "input_fact_hash", "content_hash", name="uq_content_drafts_variant_input_content"),)

    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True)
    facts_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_content_facts.id", ondelete="RESTRICT"), index=True)
    status: Mapped[ContentDraftStatus] = mapped_column(Enum(ContentDraftStatus, name="content_draft_status"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    title_generation_mode: Mapped[str] = mapped_column(String(64))
    description_generation_mode: Mapped[str] = mapped_column(String(64))
    generator: Mapped[str] = mapped_column(String(120))
    generator_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    input_fact_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    validation_status: Mapped[ContentValidationStatus] = mapped_column(Enum(ContentValidationStatus, name="content_validation_status"), default=ContentValidationStatus.NOT_VALIDATED)
    validation_errors: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    validation_warnings: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    facts = relationship("ProductContentFacts")


class ProductFactOverride(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_fact_overrides"
    __table_args__ = (UniqueConstraint("variant_id", "field", name="uq_fact_overrides_variant_field"),)

    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True)
    field: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[str] = mapped_column(String(512))
    operator: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProductImageAsset(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_image_assets"
    __table_args__ = (UniqueConstraint("variant_id", "sha256", name="uq_image_assets_variant_sha256"),)

    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True)
    source_type: Mapped[ImageAssetSourceType] = mapped_column(Enum(ImageAssetSourceType, name="image_asset_source_type"))
    source_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(120))
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[ImageAssetStatus] = mapped_column(Enum(ImageAssetStatus, name="image_asset_status"), default=ImageAssetStatus.READY, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductImageSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_image_sets"
    __table_args__ = (UniqueConstraint("variant_id", "content_hash", name="uq_image_sets_variant_hash"),)

    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True)
    status: Mapped[ImageSetStatus] = mapped_column(Enum(ImageSetStatus, name="image_set_status"), default=ImageSetStatus.DRAFT, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    cover_image_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_image_assets.id", ondelete="RESTRICT"), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    items = relationship("ProductImageSetItem", back_populates="image_set", cascade="all, delete-orphan")


class ProductImageSetItem(Base):
    __tablename__ = "product_image_set_items"

    image_set_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_image_sets.id", ondelete="CASCADE"), primary_key=True)
    image_asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_image_assets.id", ondelete="RESTRICT"), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer)

    image_set = relationship("ProductImageSet", back_populates="items")
    image_asset = relationship("ProductImageAsset")


class GenericListingDraft(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "generic_listing_drafts"
    __table_args__ = (UniqueConstraint("variant_id", "content_hash", name="uq_generic_listing_variant_hash"),)

    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True)
    content_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_content_drafts.id", ondelete="RESTRICT"), nullable=True, index=True)
    image_set_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_image_sets.id", ondelete="RESTRICT"), nullable=True, index=True)
    pricing_state_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("variant_pricing_states.product_variant_id", ondelete="RESTRICT"), nullable=True)
    status: Mapped[GenericListingStatus] = mapped_column(Enum(GenericListingStatus, name="generic_listing_status"), index=True)
    generic_category: Mapped[GenericCategory] = mapped_column(Enum(GenericCategory, name="generic_category"), default=GenericCategory.OTHER, index=True)
    generic_attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fulfillment_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generic_readiness: Mapped[GenericReadinessStatus] = mapped_column(Enum(GenericReadinessStatus, name="generic_readiness_status"), index=True)
    avito_readiness: Mapped[MarketplaceReadinessStatus] = mapped_column(Enum(MarketplaceReadinessStatus, name="marketplace_readiness_status"))
    readiness_reasons: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    content_draft = relationship("ProductContentDraft")
    image_set = relationship("ProductImageSet")
