import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ManualImportBatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "manual_import_batches"
    __table_args__ = (
        UniqueConstraint("import_type", "scope_key", "content_hash", "mode", name="uq_manual_import_batch_identity"),
        Index("ix_manual_import_batches_status", "status"),
        Index("ix_manual_import_batches_created_at", "created_at"),
    )

    import_type: Mapped[str] = mapped_column(String(32))
    scope_key: Mapped[str] = mapped_column(String(255))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="PREVIEWED", server_default="PREVIEWED")
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_content: Mapped[str] = mapped_column(Text)
    preview: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    raw_source_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("raw_source_records.id"), nullable=True)
    supplier_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("supplier_snapshots.id"), nullable=True)
    one_c_import_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("one_c_import_runs.id"), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
