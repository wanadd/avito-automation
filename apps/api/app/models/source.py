import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SourceType, SupplierSnapshotType, TelegramCollectionRunStatus


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"))
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type"))
    external_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    external_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    snapshot_type: Mapped[SupplierSnapshotType] = mapped_column(
        Enum(SupplierSnapshotType, name="supplier_snapshot_type"),
        default=SupplierSnapshotType.FULL,
        server_default=SupplierSnapshotType.FULL,
    )
    last_collected_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_collection_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_collection_status: Mapped[TelegramCollectionRunStatus | None] = mapped_column(
        Enum(TelegramCollectionRunStatus, name="telegram_collection_run_status"), nullable=True
    )
    last_collection_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    collection_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    collection_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_collection_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(default=0, server_default="0")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supplier = relationship("Supplier", back_populates="sources")
    raw_records = relationship("RawSourceRecord", back_populates="source")
