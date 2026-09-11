import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import TelegramCollectionMode, TelegramCollectionRunStatus


class TelegramCollectionRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "telegram_collection_runs"

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[TelegramCollectionRunStatus] = mapped_column(
        Enum(TelegramCollectionRunStatus, name="telegram_collection_run_status"),
        default=TelegramCollectionRunStatus.RUNNING,
        server_default=TelegramCollectionRunStatus.RUNNING,
    )
    mode: Mapped[TelegramCollectionMode] = mapped_column(Enum(TelegramCollectionMode, name="telegram_collection_mode"))
    fetched_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    new_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    edited_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ignored_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    snapshots_created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    snapshots_processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    start_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    end_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
