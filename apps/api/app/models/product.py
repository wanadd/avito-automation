import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ProductCondition


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"

    brand: Mapped[str] = mapped_column(String(120), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    model_family: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    variants = relationship("ProductVariant", back_populates="product")
    aliases = relationship("ProductAlias", back_populates="product")


class ProductVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_variants"

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"))
    manufacturer_model_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ram_gb: Mapped[int | None] = mapped_column(nullable=True)
    storage_gb: Mapped[int | None] = mapped_column(nullable=True)
    color_raw: Mapped[str | None] = mapped_column(String(120), nullable=True)
    color_normalized: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    condition: Mapped[ProductCondition] = mapped_column(Enum(ProductCondition, name="product_condition"))
    canonical_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    product = relationship("Product", back_populates="variants")
    aliases = relationship("ProductAlias", back_populates="product_variant")
    offers = relationship("SupplierOffer", back_populates="product_variant")


class ProductAlias(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_aliases"
    __table_args__ = (
        CheckConstraint(
            "(product_id IS NOT NULL AND product_variant_id IS NULL) OR "
            "(product_id IS NULL AND product_variant_id IS NOT NULL)",
            name="exactly_one_product_target",
        ),
        UniqueConstraint("normalized_alias", "source_id", name="uq_product_aliases_normalized_source"),
    )

    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=True
    )
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=True
    )
    alias: Mapped[str] = mapped_column(String(255))
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="aliases")
    product_variant = relationship("ProductVariant", back_populates="aliases")
