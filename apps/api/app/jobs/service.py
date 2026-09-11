import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import base as _model_registry  # noqa: F401
from app.integrations.telegram.client import build_telegram_adapter
from app.integrations.telegram.collector import collect_source, sanitize_error
from app.integrations.telegram.types import (
    TelegramAccessError,
    TelegramAuthError,
    TelegramNetworkError,
    TelegramRateLimitError,
)
from app.jobs.locks import SourceLock
from app.jobs.queue import QueueAdapter
from app.models.audit_log import AuditLog
from app.models.enums import (
    SourceCollectionJobStatus,
    SourceCollectionJobType,
    SourceType,
    TelegramCollectionMode,
    TelegramCollectionRunStatus,
)
from app.models.source import Source
from app.models.source_collection_job import SourceCollectionJob

CollectorCallable = Callable[[AsyncSession, Source, SourceCollectionJob], Awaitable[dict]]


def utc_now() -> datetime:
    return datetime.now(UTC)


def interval_for(source: Source) -> int:
    return source.collection_interval_seconds or get_settings().telegram_default_collection_interval_seconds


def jitter_for(source_id: uuid.UUID) -> int:
    max_jitter = get_settings().collection_scheduler_jitter_seconds
    if max_jitter <= 0:
        return 0
    digest = hashlib.sha256(str(source_id).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % (max_jitter + 1)


def next_future_slot(scheduled_for: datetime, interval_seconds: int, now: datetime) -> datetime:
    next_at = scheduled_for + timedelta(seconds=interval_seconds)
    while next_at <= now:
        next_at += timedelta(seconds=interval_seconds)
    return next_at


def idempotency_key(source_id: uuid.UUID, scheduled_for: datetime, job_type: SourceCollectionJobType) -> str:
    return f"{source_id}:{scheduled_for.isoformat()}:{job_type.value}"


def job_mode(job: SourceCollectionJob) -> TelegramCollectionMode:
    value = job.parameters.get("mode")
    if value:
        return TelegramCollectionMode(value)
    if job.job_type == SourceCollectionJobType.MANUAL_BACKFILL:
        return TelegramCollectionMode.BACKFILL
    return TelegramCollectionMode.INCREMENTAL


def job_limit(job: SourceCollectionJob) -> int | None:
    value = job.parameters.get("limit")
    return int(value) if value is not None else None


async def create_collection_job(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    job_type: SourceCollectionJobType,
    scheduled_for: datetime,
    parameters: dict | None = None,
    max_attempts: int | None = None,
) -> tuple[SourceCollectionJob, bool]:
    key = idempotency_key(source_id, scheduled_for, job_type)
    existing = await session.scalar(select(SourceCollectionJob).where(SourceCollectionJob.idempotency_key == key))
    if existing:
        return existing, False
    job = SourceCollectionJob(
        source_id=source_id,
        job_type=job_type,
        scheduled_for=scheduled_for,
        max_attempts=max_attempts or get_settings().collection_job_max_attempts,
        parameters=parameters or {"mode": TelegramCollectionMode.INCREMENTAL.value},
        idempotency_key=key,
    )
    session.add(job)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(select(SourceCollectionJob).where(SourceCollectionJob.idempotency_key == key))
        if existing is None:
            raise
        return existing, False
    await session.refresh(job)
    return job, True


async def enqueue_job(session: AsyncSession, job: SourceCollectionJob, queue: QueueAdapter) -> SourceCollectionJob:
    queue.enqueue_job(str(job.id))
    job.status = SourceCollectionJobStatus.QUEUED
    job.queued_at = utc_now()
    await session.commit()
    await session.refresh(job)
    return job


async def create_manual_job(
    session: AsyncSession,
    queue: QueueAdapter,
    *,
    source_id: uuid.UUID,
    mode: TelegramCollectionMode,
    limit: int | None = None,
    force: bool = False,
) -> SourceCollectionJob:
    source = await session.get(Source, source_id)
    if source is None:
        raise ValueError("Source not found")
    if not force and not source.collection_enabled:
        raise ValueError("Source collection is disabled")
    job_type = SourceCollectionJobType.MANUAL_BACKFILL if mode == TelegramCollectionMode.BACKFILL else SourceCollectionJobType.MANUAL_INCREMENTAL
    job, _ = await create_collection_job(
        session,
        source_id=source_id,
        job_type=job_type,
        scheduled_for=utc_now(),
        parameters={"mode": mode.value, "limit": limit},
    )
    return await enqueue_job(session, job, queue)


async def scheduler_tick(session: AsyncSession, queue: QueueAdapter, *, now: datetime | None = None) -> list[SourceCollectionJob]:
    now = now or utc_now()
    statement = select(Source).where(
        Source.source_type == SourceType.TELEGRAM,
        Source.telegram_enabled.is_(True),
        Source.collection_enabled.is_(True),
        or_(Source.next_collection_at.is_(None), Source.next_collection_at <= now),
    )
    sources = list(await session.scalars(statement))
    jobs: list[SourceCollectionJob] = []
    for source in sources:
        interval_seconds = interval_for(source)
        scheduled_for = source.next_collection_at or now
        if scheduled_for < now - timedelta(seconds=interval_seconds):
            scheduled_for = now
        scheduled_for = scheduled_for + timedelta(seconds=jitter_for(source.id))
        job, created = await create_collection_job(
            session,
            source_id=source.id,
            job_type=SourceCollectionJobType.SCHEDULED_INCREMENTAL,
            scheduled_for=scheduled_for,
            parameters={"mode": TelegramCollectionMode.INCREMENTAL.value},
        )
        if created:
            await enqueue_job(session, job, queue)
        source.last_scheduled_at = now
        source.next_collection_at = next_future_slot(source.next_collection_at or now, interval_seconds, now)
        await session.commit()
        jobs.append(job)
    return jobs


async def execute_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    lock_factory,
    collector: CollectorCallable | None = None,
) -> SourceCollectionJob:
    job = await session.scalar(select(SourceCollectionJob).where(SourceCollectionJob.id == job_id).with_for_update())
    if job is None:
        raise ValueError("SourceCollectionJob not found")
    if job.status in {
        SourceCollectionJobStatus.SUCCEEDED,
        SourceCollectionJobStatus.FAILED,
        SourceCollectionJobStatus.CANCELLED,
        SourceCollectionJobStatus.SKIPPED,
    }:
        return job
    source = await session.get(Source, job.source_id)
    if source is None:
        return await fail_job(session, job, "SOURCE_NOT_FOUND", "Source not found", permanent=True)
    if not source.collection_enabled:
        job.status = SourceCollectionJobStatus.SKIPPED
        job.finished_at = utc_now()
        await session.commit()
        return job

    running = await session.scalar(
        select(SourceCollectionJob).where(
            SourceCollectionJob.source_id == source.id,
            SourceCollectionJob.status == SourceCollectionJobStatus.RUNNING,
            SourceCollectionJob.id != job.id,
        )
    )
    if running is not None:
        job.status = SourceCollectionJobStatus.SKIPPED
        job.error_code = "SOURCE_ALREADY_RUNNING"
        job.error_message = "Another source collection job is running"
        job.finished_at = utc_now()
        await session.commit()
        return job

    lock = lock_factory(source.id)
    if not lock.acquire():
        job.status = SourceCollectionJobStatus.SKIPPED
        job.error_code = "SOURCE_LOCKED"
        job.error_message = "Source collection lock is held"
        job.finished_at = utc_now()
        await session.commit()
        return job

    try:
        job.status = SourceCollectionJobStatus.RUNNING
        job.started_at = utc_now()
        await session.commit()
        if collector is None:
            collector = run_telegram_collector
        result = await collector(session, source, job)
        run_id = result.get("run_id")
        if run_id:
            job.collection_run_id = run_id
        if result.get("status") == TelegramCollectionRunStatus.COMPLETED:
            await succeed_job(session, job, source)
        else:
            error = result.get("error") or "Collection failed"
            await classify_failure(session, job, source, error, transient=is_transient_collection_error(error))
    except (TelegramNetworkError, TelegramRateLimitError) as exc:
        await classify_failure(session, job, source, sanitize_error(exc), transient=True)
    except (TelegramAuthError, TelegramAccessError, ValueError) as exc:
        await fail_job(session, job, exc.__class__.__name__, sanitize_error(exc), permanent=True)
    except Exception as exc:
        await classify_failure(session, job, source, sanitize_error(exc), transient=True)
    finally:
        lock.release()
    await session.refresh(job)
    return job


async def run_telegram_collector(session: AsyncSession, source: Source, job: SourceCollectionJob) -> dict:
    return await collect_source(
        session,
        source.id,
        mode=job_mode(job),
        limit=job_limit(job),
        adapter=build_telegram_adapter(),
    )


async def succeed_job(session: AsyncSession, job: SourceCollectionJob, source: Source) -> None:
    recovered = source.consecutive_failures > 0
    job.status = SourceCollectionJobStatus.SUCCEEDED
    job.finished_at = utc_now()
    job.error_code = None
    job.error_message = None
    source.consecutive_failures = 0
    source.last_success_at = job.finished_at
    if recovered:
        session.add(
            AuditLog(
                entity_type="Source",
                entity_id=source.id,
                action="SOURCE_RECOVERED",
                old_value=None,
                new_value={"job_id": str(job.id)},
                actor_type="SYSTEM",
            )
        )
    await session.commit()


async def classify_failure(
    session: AsyncSession,
    job: SourceCollectionJob,
    source: Source,
    message: str,
    *,
    transient: bool = False,
) -> None:
    if transient and job.attempt < job.max_attempts:
        job.status = SourceCollectionJobStatus.RETRY_WAIT
        job.error_code = "TRANSIENT_FAILURE"
        job.error_message = message
        job.scheduled_for = utc_now() + retry_backoff(job.attempt)
    else:
        await fail_job(session, job, "COLLECTION_FAILED", message, permanent=not transient)
        return
    source.consecutive_failures += 1
    await session.commit()


async def fail_job(
    session: AsyncSession,
    job: SourceCollectionJob,
    code: str,
    message: str,
    *,
    permanent: bool,
) -> SourceCollectionJob:
    source = await session.get(Source, job.source_id)
    job.status = SourceCollectionJobStatus.FAILED
    job.finished_at = utc_now()
    job.error_code = code
    job.error_message = message
    if source is not None:
        source.consecutive_failures += 1
    await session.commit()
    return job


def retry_backoff(attempt: int) -> timedelta:
    seconds = {1: 30, 2: 120}.get(attempt, 300)
    return timedelta(seconds=seconds)


def is_transient_collection_error(message: str) -> bool:
    normalized = message.lower()
    return "rate limit" in normalized or "timeout" in normalized or "network" in normalized


async def enqueue_due_retries(session: AsyncSession, queue: QueueAdapter, *, now: datetime | None = None) -> list[SourceCollectionJob]:
    now = now or utc_now()
    jobs = list(
        await session.scalars(
            select(SourceCollectionJob).where(
                SourceCollectionJob.status == SourceCollectionJobStatus.RETRY_WAIT,
                SourceCollectionJob.scheduled_for <= now,
                SourceCollectionJob.attempt < SourceCollectionJob.max_attempts,
            )
        )
    )
    for job in jobs:
        job.attempt += 1
        await enqueue_job(session, job, queue)
    return jobs


async def recover_stale_running_jobs(session: AsyncSession, queue: QueueAdapter, *, now: datetime | None = None) -> list[SourceCollectionJob]:
    now = now or utc_now()
    cutoff = now - timedelta(seconds=get_settings().job_stale_running_seconds)
    jobs = list(
        await session.scalars(
            select(SourceCollectionJob).where(
                SourceCollectionJob.status == SourceCollectionJobStatus.RUNNING,
                SourceCollectionJob.started_at < cutoff,
            )
        )
    )
    for job in jobs:
        if job.attempt < job.max_attempts:
            job.status = SourceCollectionJobStatus.RETRY_WAIT
            job.scheduled_for = now + retry_backoff(job.attempt)
            job.error_code = "STALE_RUNNING"
            job.error_message = "Stale running job recovered for retry"
        else:
            job.status = SourceCollectionJobStatus.FAILED
            job.finished_at = now
            job.error_code = "STALE_RUNNING"
            job.error_message = "Stale running job exceeded max attempts"
    await session.commit()
    return jobs


def source_operational_status(source: Source, *, now: datetime | None = None) -> str:
    if not source.collection_enabled:
        return "DISABLED"
    if source.last_collection_at is None:
        return "NEVER_RUN"
    if source.consecutive_failures >= get_settings().source_error_failure_threshold:
        return "ERROR"
    if source.consecutive_failures > 0:
        return "DEGRADED"
    return "HEALTHY"


def source_is_stale(source: Source, *, now: datetime | None = None) -> bool:
    now = now or utc_now()
    if source.last_success_at is None:
        return False
    return now - source.last_success_at > timedelta(seconds=interval_for(source) * get_settings().source_stale_multiplier)


async def source_status(session: AsyncSession, source_id: uuid.UUID, *, now: datetime | None = None) -> dict:
    source = await session.get(Source, source_id)
    if source is None:
        raise ValueError("Source not found")
    latest_job = await session.scalar(
        select(SourceCollectionJob).where(SourceCollectionJob.source_id == source.id).order_by(SourceCollectionJob.created_at.desc()).limit(1)
    )
    return {
        "source_id": source.id,
        "collection_enabled": source.collection_enabled,
        "operational_status": source_operational_status(source, now=now),
        "stale": source_is_stale(source, now=now),
        "last_success_at": source.last_success_at,
        "last_collection_at": source.last_collection_at,
        "last_collection_status": source.last_collection_status,
        "consecutive_failures": source.consecutive_failures,
        "next_collection_at": source.next_collection_at,
        "latest_job_id": latest_job.id if latest_job else None,
        "latest_job_status": latest_job.status if latest_job else None,
    }


async def operations_status(session: AsyncSession, *, now: datetime | None = None) -> dict:
    sources = list(await session.scalars(select(Source).where(Source.collection_enabled.is_(True))))
    statuses = [source_operational_status(source, now=now) for source in sources]
    stale_count = sum(source_is_stale(source, now=now) for source in sources)
    last_24h = (now or utc_now()) - timedelta(hours=24)
    return {
        "enabled_sources": len(sources),
        "healthy_sources": statuses.count("HEALTHY"),
        "degraded_sources": statuses.count("DEGRADED"),
        "error_sources": statuses.count("ERROR"),
        "stale_sources": stale_count,
        "queued_jobs": await session.scalar(select(func.count()).select_from(SourceCollectionJob).where(SourceCollectionJob.status == SourceCollectionJobStatus.QUEUED)),
        "running_jobs": await session.scalar(select(func.count()).select_from(SourceCollectionJob).where(SourceCollectionJob.status == SourceCollectionJobStatus.RUNNING)),
        "retry_wait_jobs": await session.scalar(select(func.count()).select_from(SourceCollectionJob).where(SourceCollectionJob.status == SourceCollectionJobStatus.RETRY_WAIT)),
        "failed_jobs_last_24h": await session.scalar(
            select(func.count()).select_from(SourceCollectionJob).where(
                SourceCollectionJob.status == SourceCollectionJobStatus.FAILED,
                SourceCollectionJob.finished_at >= last_24h,
            )
        ),
    }


async def retry_failed_job(session: AsyncSession, queue: QueueAdapter, job_id: uuid.UUID) -> SourceCollectionJob:
    old = await session.get(SourceCollectionJob, job_id)
    if old is None:
        raise ValueError("SourceCollectionJob not found")
    if old.status != SourceCollectionJobStatus.FAILED:
        raise ValueError("Only FAILED jobs can be retried")
    job, _ = await create_collection_job(
        session,
        source_id=old.source_id,
        job_type=SourceCollectionJobType.RETRY,
        scheduled_for=utc_now(),
        parameters=old.parameters,
        max_attempts=old.max_attempts,
    )
    return await enqueue_job(session, job, queue)
