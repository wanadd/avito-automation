import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class TelegramPriceBotState(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "telegram_price_bot_states"
    __table_args__ = (UniqueConstraint("bot_key", name="uq_telegram_price_bot_states_bot_key"),)

    bot_key: Mapped[str] = mapped_column(String(64), nullable=False)
    last_update_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_api_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_successful_price_ingestion_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramPriceSource(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "telegram_price_sources"
    __table_args__ = (
        UniqueConstraint("telegram_channel_id", name="uq_telegram_price_sources_channel_id"),
        Index("ix_telegram_price_sources_source_id", "source_id"),
    )

    telegram_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source = relationship("Source")


class TelegramPriceBatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "telegram_price_batches"
    __table_args__ = (
        Index("ix_telegram_price_batches_status", "status"),
        Index("ix_telegram_price_batches_source", "telegram_price_source_id"),
    )

    telegram_price_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_price_sources.id", ondelete="SET NULL"), nullable=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True)
    raw_source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_source_records.id", ondelete="SET NULL"), nullable=True
    )
    raw_source_record_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_source_record_revisions.id", ondelete="SET NULL"), nullable=True
    )
    supplier_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    submitted_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    destination_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="RECEIVED", server_default="RECEIVED")
    duplicate: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    parsed_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    accepted_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    review_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    first_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    telegram_price_source = relationship("TelegramPriceSource")
    messages = relationship("TelegramPriceMessage", back_populates="batch")


class TelegramPriceMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "telegram_price_messages"
    __table_args__ = (
        UniqueConstraint("update_id", name="uq_telegram_price_messages_update_id"),
        Index("ix_telegram_price_messages_batch", "batch_id"),
    )

    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_price_batches.id", ondelete="SET NULL"), nullable=True
    )
    telegram_price_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_price_sources.id", ondelete="SET NULL"), nullable=True
    )
    update_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sender_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    destination_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    forward_origin: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    batch = relationship("TelegramPriceBatch", back_populates="messages")
    telegram_price_source = relationship("TelegramPriceSource")
