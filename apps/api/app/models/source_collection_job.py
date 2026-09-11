import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SourceCollectionJobStatus, SourceCollectionJobType


class SourceCollectionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_collection_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_source_collection_jobs_idempotency_key"),
        Index("ix_source_collection_jobs_source_id", "source_id"),
        Index("ix_source_collection_jobs_status", "status"),
        Index("ix_source_collection_jobs_scheduled_for", "scheduled_for"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"))
    collection_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_collection_runs.id"), nullable=True
    )
    job_type: Mapped[SourceCollectionJobType] = mapped_column(
        Enum(SourceCollectionJobType, name="source_collection_job_type")
    )
    status: Mapped[SourceCollectionJobStatus] = mapped_column(
        Enum(SourceCollectionJobStatus, name="source_collection_job_status"),
        default=SourceCollectionJobStatus.PENDING,
        server_default=SourceCollectionJobStatus.PENDING,
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
