import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import ConflictStatus


class DataConflict(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "data_conflicts"

    conflict_type: Mapped[str] = mapped_column(String(120), index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True)
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id"), nullable=True
    )
    raw_source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_source_records.id"), nullable=True
    )
    details: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[ConflictStatus] = mapped_column(
        Enum(ConflictStatus, name="conflict_status"), default=ConflictStatus.OPEN, server_default=ConflictStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
