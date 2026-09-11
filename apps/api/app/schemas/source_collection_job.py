import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import SourceCollectionJobStatus, SourceCollectionJobType, TelegramCollectionRunStatus
from app.schemas.common import Timestamped


class SourceCollectionJobRead(Timestamped):
    id: uuid.UUID
    source_id: uuid.UUID
    collection_run_id: uuid.UUID | None
    job_type: SourceCollectionJobType
    status: SourceCollectionJobStatus
    scheduled_for: datetime
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    attempt: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    parameters: dict


class SourceStatusRead(BaseModel):
    source_id: uuid.UUID
    collection_enabled: bool
    operational_status: str
    stale: bool
    last_success_at: datetime | None
    last_collection_at: datetime | None
    last_collection_status: TelegramCollectionRunStatus | None
    consecutive_failures: int
    next_collection_at: datetime | None
    latest_job_id: uuid.UUID | None
    latest_job_status: SourceCollectionJobStatus | None


class OperationsStatusRead(BaseModel):
    enabled_sources: int
    healthy_sources: int
    degraded_sources: int
    error_sources: int
    stale_sources: int
    queued_jobs: int
    running_jobs: int
    retry_wait_jobs: int
    failed_jobs_last_24h: int
