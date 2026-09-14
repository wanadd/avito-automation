import uuid
from datetime import datetime

from pydantic import BaseModel

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
from app.schemas.common import ORMModel


class PublicationIntentCreate(BaseModel):
    marketplace: Marketplace = Marketplace.AVITO
    intent_type: PublicationIntentType = PublicationIntentType.CREATE
    requested_by: str = "operator"
    reason: str | None = None
    dry_run: bool = True


class PublicationIntentRead(ORMModel):
    id: uuid.UUID
    listing_id: uuid.UUID
    binding_id: uuid.UUID | None
    marketplace: Marketplace
    intent_type: PublicationIntentType
    status: PublicationIntentStatus
    requested_by: str
    requested_at: datetime
    approved_snapshot_hash: str
    listing_hash: str
    pricing_hash: str | None
    content_hash: str | None
    image_set_hash: str | None
    reason: str | None
    metadata_json: dict
    idempotency_key: str
    created_at: datetime
    updated_at: datetime


class PublicationJobRead(ORMModel):
    id: uuid.UUID
    intent_id: uuid.UUID
    marketplace: Marketplace
    job_type: PublicationIntentType
    status: PublicationJobStatus
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    idempotency_key: str
    payload_hash: str | None
    prepared_payload: dict | None
    dry_run: bool
    created_at: datetime
    updated_at: datetime


class MarketplaceListingBindingRead(ORMModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    generic_listing_id: uuid.UUID
    marketplace: Marketplace
    external_listing_id: str | None
    status: MarketplaceBindingStatus
    sync_state: ListingSyncState
    adapter_version: str
    contract_version: str | None
    last_known_price_minor: int | None
    last_known_stock_state: str | None
    last_content_hash: str | None
    last_image_set_hash: str | None
    last_payload_hash: str | None
    last_sync_at: datetime | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime


class OperationalAlertRead(ORMModel):
    id: uuid.UUID
    type: str
    severity: OperationalAlertSeverity
    entity_type: str
    entity_id: uuid.UUID
    status: OperationalAlertStatus
    dedupe_key: str
    message: str
    metadata_json: dict
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ControlOverviewRead(BaseModel):
    generic_ready: int
    review_required: int
    not_ready: int
    approved: int
    publication_intent_pending: int
    jobs_queued: int
    jobs_retrying: int
    jobs_blocked: int
    jobs_failed: int
    dry_run_success: int
    stale_bindings: int
    open_alerts: int


class RetryCancelRequest(BaseModel):
    requested_by: str = "operator"


class ReconcileRequest(BaseModel):
    listing_id: uuid.UUID
    marketplace: Marketplace = Marketplace.AVITO
