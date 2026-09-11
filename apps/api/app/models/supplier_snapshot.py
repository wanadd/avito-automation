import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import MatchStatus, SupplierSnapshotItemStatus, SupplierSnapshotStatus, SupplierSnapshotType


class SupplierSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "supplier_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "supplier_id",
            "source_id",
            "raw_source_record_id",
            "raw_source_record_revision_id",
            name="uq_supplier_snapshots_raw_revision_identity",
        ),
        Index("ix_supplier_snapshots_supplier_id", "supplier_id"),
        Index("ix_supplier_snapshots_source_id", "source_id"),
        Index("ix_supplier_snapshots_captured_at", "captured_at"),
        Index("ix_supplier_snapshots_status", "status"),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"))
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"))
    raw_source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_source_records.id", ondelete="RESTRICT")
    )
    raw_source_record_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_source_record_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    external_snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_type: Mapped[SupplierSnapshotType] = mapped_column(Enum(SupplierSnapshotType, name="supplier_snapshot_type"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[SupplierSnapshotStatus] = mapped_column(
        Enum(SupplierSnapshotStatus, name="supplier_snapshot_status"),
        default=SupplierSnapshotStatus.PENDING,
        server_default=SupplierSnapshotStatus.PENDING,
    )
    total_lines: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    parsed_items: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    matched_items: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    offers_seen: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    conflicts_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    review_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    parser_error_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    quality_gate_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplierSnapshotItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "supplier_snapshot_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "parsed_supplier_item_id", name="uq_supplier_snapshot_items_snapshot_parsed"),
        Index("ix_supplier_snapshot_items_snapshot_id", "snapshot_id"),
        Index("ix_supplier_snapshot_items_offer_id", "supplier_offer_id"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("supplier_snapshots.id", ondelete="CASCADE"))
    parsed_supplier_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parsed_supplier_items.id", ondelete="CASCADE")
    )
    supplier_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_offers.id"), nullable=True
    )
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id"), nullable=True
    )
    match_status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus, name="match_status"))
    item_status: Mapped[SupplierSnapshotItemStatus] = mapped_column(
        Enum(SupplierSnapshotItemStatus, name="supplier_snapshot_item_status")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
