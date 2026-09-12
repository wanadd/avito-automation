import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import OneCImportMode, OneCImportRunStatus, OneCItemMatchStatus, OneCItemMatchStrategy


class OneCItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "one_c_items"
    __table_args__ = (UniqueConstraint("internal_code", name="uq_one_c_items_internal_code"),)

    internal_code: Mapped[str] = mapped_column(String(120), index=True)
    sku: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    barcode: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    raw_name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    matched_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True
    )
    match_status: Mapped[OneCItemMatchStatus] = mapped_column(
        Enum(OneCItemMatchStatus, name="one_c_item_match_status"),
        default=OneCItemMatchStatus.UNMATCHED,
        server_default=OneCItemMatchStatus.UNMATCHED,
    )
    match_strategy: Mapped[OneCItemMatchStrategy | None] = mapped_column(
        Enum(OneCItemMatchStrategy, name="one_c_item_match_strategy"), nullable=True
    )
    match_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    explicit_mapping: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    matched_variant = relationship("ProductVariant")


class OneCImportRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "one_c_import_runs"

    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    exported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[OneCImportRunStatus] = mapped_column(
        Enum(OneCImportRunStatus, name="one_c_import_run_status"),
        default=OneCImportRunStatus.PENDING,
        server_default=OneCImportRunStatus.PENDING,
    )
    mode: Mapped[OneCImportMode] = mapped_column(Enum(OneCImportMode, name="one_c_import_mode"))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    total_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    valid_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    matched_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unmatched_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ambiguous_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    would_update_stock: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    would_update_cost: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    would_zero_missing: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    warnings: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VariantInventoryState(Base):
    __tablename__ = "variant_inventory_states"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), primary_key=True
    )
    own_stock_total: Mapped[int] = mapped_column(Integer)
    own_cost_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("one_c_items.id"))
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_import_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("one_c_import_runs.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    variant = relationship("ProductVariant")
    source_item = relationship("OneCItem")


class VariantStockSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "variant_stock_snapshots"

    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id"))
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("one_c_items.id"))
    import_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("one_c_import_runs.id"))
    stock_total: Mapped[int] = mapped_column(Integer)
    stock_by_store: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VariantCostSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "variant_cost_snapshots"

    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id"))
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("one_c_items.id"))
    import_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("one_c_import_runs.id"))
    cost_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
