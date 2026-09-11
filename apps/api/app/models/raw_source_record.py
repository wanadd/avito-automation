import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import ProcessingStatus


class RawSourceRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_source_records"
    __table_args__ = (
        Index(
            "uq_raw_source_records_source_external_record",
            "source_id",
            "external_record_id",
            unique=True,
            postgresql_where=text("external_record_id IS NOT NULL"),
        ),
        Index("ix_raw_source_records_content_hash", "content_hash"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"))
    external_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="processing_status"), default=ProcessingStatus.NEW, server_default=ProcessingStatus.NEW
    )

    source = relationship("Source", back_populates="raw_records")


class RawSourceRecordRevision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_source_record_revisions"
    __table_args__ = (
        Index("uq_raw_source_record_revisions_record_revision", "raw_source_record_id", "revision_no", unique=True),
        Index("uq_raw_source_record_revisions_record_hash", "raw_source_record_id", "content_hash", unique=True),
    )

    raw_source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_source_records.id", ondelete="CASCADE")
    )
    revision_no: Mapped[int] = mapped_column()
    content_hash: Mapped[str] = mapped_column(String(128))
    raw_content: Mapped[str] = mapped_column(Text)
    external_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
