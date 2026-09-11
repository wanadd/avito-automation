import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CHAR, DateTime, Enum, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Availability


class SupplierOffer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supplier_offers"
    __table_args__ = (
        Index(
            "uq_supplier_offers_supplier_sku",
            "supplier_id",
            "supplier_sku",
            unique=True,
            postgresql_where=text("supplier_sku IS NOT NULL"),
        ),
        Index("ix_supplier_offers_variant_supplier", "product_variant_id", "supplier_id"),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"))
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True)
    supplier_sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    supplier_title: Mapped[str] = mapped_column(String(512))
    price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(CHAR(3), default="RUB", server_default="RUB")
    availability: Mapped[Availability] = mapped_column(Enum(Availability, name="availability"))
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_source_records.id"), nullable=True
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    consecutive_missing_count: Mapped[int] = mapped_column(default=0, server_default="0")
    last_seen_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_snapshots.id"), nullable=True
    )
    last_missing_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_snapshots.id"), nullable=True
    )
    last_availability_change_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supplier = relationship("Supplier", back_populates="offers")
    product_variant = relationship("ProductVariant", back_populates="offers")
    snapshots = relationship("SupplierOfferSnapshot", back_populates="supplier_offer")


class SupplierOfferSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "supplier_offer_snapshots"
    __table_args__ = (Index("ix_supplier_offer_snapshots_offer_captured", "supplier_offer_id", "captured_at"),)

    supplier_offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_offers.id", ondelete="RESTRICT")
    )
    price_minor: Mapped[int] = mapped_column(BigInteger)
    availability: Mapped[Availability] = mapped_column(Enum(Availability, name="availability"))
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_source_records.id"), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    supplier_offer = relationship("SupplierOffer", back_populates="snapshots")
