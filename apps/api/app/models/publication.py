import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ListingSyncState,
    Marketplace,
    MarketplaceBindingStatus,
    OperationalAlertSeverity,
    OperationalAlertStatus,
    PublicationIntentStatus,
    PublicationIntentType,
    PublicationJobStatus,
)


class MarketplaceListingBinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "marketplace_listing_bindings"
    __table_args__ = (UniqueConstraint("marketplace", "generic_listing_id", name="uq_marketplace_binding_listing"),)

    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True)
    generic_listing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("generic_listing_drafts.id", ondelete="RESTRICT"), index=True)
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace, name="marketplace"), index=True)
    external_listing_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[MarketplaceBindingStatus] = mapped_column(Enum(MarketplaceBindingStatus, name="marketplace_binding_status"), index=True)
    sync_state: Mapped[ListingSyncState] = mapped_column(Enum(ListingSyncState, name="listing_sync_state"), index=True)
    adapter_version: Mapped[str] = mapped_column(String(64))
    contract_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_known_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_known_stock_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_image_set_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    listing = relationship("GenericListingDraft")


class PublicationIntent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "publication_intents"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_publication_intents_idempotency_key"),)

    listing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("generic_listing_drafts.id", ondelete="RESTRICT"), index=True)
    binding_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("marketplace_listing_bindings.id", ondelete="RESTRICT"), nullable=True, index=True)
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace, name="marketplace"), index=True)
    intent_type: Mapped[PublicationIntentType] = mapped_column(Enum(PublicationIntentType, name="publication_intent_type"), index=True)
    status: Mapped[PublicationIntentStatus] = mapped_column(Enum(PublicationIntentStatus, name="publication_intent_status"), index=True)
    requested_by: Mapped[str] = mapped_column(String(120))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_snapshot_hash: Mapped[str] = mapped_column(String(64))
    listing_hash: Mapped[str] = mapped_column(String(64))
    pricing_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_set_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)

    listing = relationship("GenericListingDraft")
    binding = relationship("MarketplaceListingBinding")


class PublicationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "publication_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_publication_jobs_idempotency_key"),)

    intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("publication_intents.id", ondelete="RESTRICT"), index=True)
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace, name="marketplace"), index=True)
    job_type: Mapped[PublicationIntentType] = mapped_column(Enum(PublicationIntentType, name="publication_intent_type"), index=True)
    status: Mapped[PublicationJobStatus] = mapped_column(Enum(PublicationJobStatus, name="publication_job_status"), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prepared_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    intent = relationship("PublicationIntent")


class PublicationAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "publication_attempts"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("publication_jobs.id", ondelete="RESTRICT"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[PublicationJobStatus] = mapped_column(Enum(PublicationJobStatus, name="publication_job_status"), index=True)
    adapter: Mapped[str] = mapped_column(String(120))
    adapter_version: Mapped[str] = mapped_column(String(64))
    request_summary: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    response_summary: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class PublicationStateHistory(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "publication_state_history"

    entity_type: Mapped[str] = mapped_column(String(120), index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    old_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class OperationalAlert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operational_alerts"
    __table_args__ = (UniqueConstraint("dedupe_key", "status", name="uq_operational_alert_dedupe_status"),)

    type: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[OperationalAlertSeverity] = mapped_column(Enum(OperationalAlertSeverity, name="operational_alert_severity"), index=True)
    entity_type: Mapped[str] = mapped_column(String(120), index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[OperationalAlertStatus] = mapped_column(Enum(OperationalAlertStatus, name="operational_alert_status"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), index=True)
    message: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
