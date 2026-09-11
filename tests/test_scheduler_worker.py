import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.api.v1.routes import get_queue_adapter
from app.db.session import AsyncSessionLocal
from app.integrations.telegram.types import TelegramAccessError, TelegramAuthError, TelegramNetworkError, TelegramRateLimitError
from app.integrations.telegram.types import TelegramChatInfo, TelegramMessage
from app.jobs.queue import InMemoryQueueAdapter
from app.jobs.service import (
    create_collection_job,
    create_manual_job,
    enqueue_due_retries,
    execute_job,
    recover_stale_running_jobs,
    retry_failed_job,
    scheduler_tick,
    source_status,
)
from app.main import app
from app.models.audit_log import AuditLog
from app.models.enums import (
    SourceCollectionJobStatus,
    SourceCollectionJobType,
    SourceType,
    TelegramCollectionMode,
    TelegramCollectionRunStatus,
    Availability,
)
from app.models.product import ProductVariant
from app.models.raw_source_record import RawSourceRecord
from app.models.source import Source
from app.models.source_collection_job import SourceCollectionJob
from app.models.supplier_offer import SupplierOffer, SupplierOfferSnapshot
from app.models.supplier import Supplier
from app.models.supplier_snapshot import SupplierSnapshot
from app.models.telegram_collection import TelegramCollectionRun

pytestmark = pytest.mark.usefixtures("clean_database")

NOW = datetime(2026, 9, 11, 10, tzinfo=UTC)
LINES = {
    "A": "S25 ultra S938B 12/256 silverblue - 65300",
    "B": "S25 ultra S939B 12/512 silverblue - 65000",
    "C": "S25 ultra S940B 16/512 black - 85300",
}


class FakeTelegramAdapter:
    def __init__(self, messages):
        self.messages = messages

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def get_chat(self, *, external_chat_id=None, username=None):
        return TelegramChatInfo(external_chat_id=external_chat_id or -100123, title="Supplier Channel")

    async def fetch_messages(self, chat_id, *, limit):
        return list(self.messages)[:limit]

    async def fetch_messages_after(self, chat_id, *, after_message_id, limit):
        return [message for message in self.messages if after_message_id is None or message.message_id > after_message_id][:limit]

    async def get_message(self, chat_id, message_id):
        return next((message for message in self.messages if message.message_id == message_id), None)


class AllowLock:
    def __init__(self):
        self.released = False

    def acquire(self):
        return True

    def release(self):
        self.released = True


class DenyLock:
    def acquire(self):
        return False

    def release(self):
        pass


class FailingQueue:
    def enqueue_job(self, job_id: str) -> None:
        raise RuntimeError("redis unavailable")


async def seed_source(*, enabled=True, telegram_enabled=True, next_at=NOW, interval=60):
    async with AsyncSessionLocal() as session:
        supplier = Supplier(code=f"s-{uuid.uuid4().hex[:8]}", name="Scheduled Supplier")
        session.add(supplier)
        await session.flush()
        source = Source(
            supplier_id=supplier.id,
            source_type=SourceType.TELEGRAM,
            external_key=f"tg-{uuid.uuid4().hex[:8]}",
            name="Telegram source",
            external_chat_id=-100123,
            telegram_enabled=telegram_enabled,
            collection_enabled=enabled,
            collection_interval_seconds=interval,
            next_collection_at=next_at,
        )
        session.add(source)
        await session.commit()
        return source.id


def price_text(keys):
    return "Samsung\n" + "\n".join(LINES[key] for key in keys)


def message(message_id, keys, *, minutes=0):
    return TelegramMessage(
        message_id=message_id,
        date=NOW + timedelta(minutes=minutes),
        text=price_text(keys),
        sender_id=42,
    )


async def count(model):
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def offer_state(source_id, model_code):
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
        variant = await session.scalar(select(ProductVariant).where(ProductVariant.manufacturer_model_code == model_code))
        offer = await session.scalar(
            select(SupplierOffer).where(
                SupplierOffer.supplier_id == source.supplier_id,
                SupplierOffer.product_variant_id == variant.id,
            )
        )
        return offer.availability, offer.consecutive_missing_count


async def successful_collector(session, source, job):
    run = TelegramCollectionRun(
        source_id=source.id,
        mode=TelegramCollectionMode(job.parameters["mode"]),
        status=TelegramCollectionRunStatus.COMPLETED,
        fetched_count=1,
    )
    session.add(run)
    await session.flush()
    return {"run_id": run.id, "status": TelegramCollectionRunStatus.COMPLETED}


async def failed_result_collector(session, source, job):
    return {"status": TelegramCollectionRunStatus.FAILED, "error": "auth denied"}


async def network_collector(session, source, job):
    raise TelegramNetworkError("timeout")


async def auth_collector(session, source, job):
    raise TelegramAuthError("bad api_hash session phone password")


async def access_collector(session, source, job):
    raise TelegramAccessError("private channel")


async def rate_limit_collector(session, source, job):
    raise TelegramRateLimitError(42)


async def make_job(source_id, *, status=SourceCollectionJobStatus.QUEUED, job_type=SourceCollectionJobType.MANUAL_INCREMENTAL, attempt=1, max_attempts=3, scheduled_for=NOW):
    async with AsyncSessionLocal() as session:
        job = SourceCollectionJob(
            source_id=source_id,
            job_type=job_type,
            status=status,
            scheduled_for=scheduled_for,
            attempt=attempt,
            max_attempts=max_attempts,
            parameters={"mode": TelegramCollectionMode.INCREMENTAL.value},
            idempotency_key=f"{source_id}:{scheduled_for.isoformat()}:{job_type.value}:{uuid.uuid4()}",
        )
        session.add(job)
        await session.commit()
        return job.id


async def load_job(job_id):
    async with AsyncSessionLocal() as session:
        return await session.get(SourceCollectionJob, job_id)


async def test_scheduler_creates_and_enqueues_due_source():
    source_id = await seed_source(next_at=NOW)
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        jobs = await scheduler_tick(session, queue, now=NOW)
        source = await session.get(Source, source_id)
    assert len(jobs) == 1
    assert jobs[0].status == SourceCollectionJobStatus.QUEUED
    assert queue.job_ids == [str(jobs[0].id)]
    assert source.next_collection_at > NOW


async def test_scheduler_skips_disabled_source():
    await seed_source(enabled=False, next_at=NOW)
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        jobs = await scheduler_tick(session, queue, now=NOW)
    assert jobs == []
    assert queue.job_ids == []


async def test_scheduler_skips_telegram_disabled_source():
    await seed_source(telegram_enabled=False, next_at=NOW)
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        jobs = await scheduler_tick(session, queue, now=NOW)
    assert jobs == []


async def test_scheduler_skips_future_source():
    await seed_source(next_at=NOW + timedelta(minutes=5))
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        jobs = await scheduler_tick(session, queue, now=NOW)
    assert jobs == []


async def test_scheduler_tick_is_idempotent_for_same_due_slot():
    await seed_source(next_at=NOW)
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        await scheduler_tick(session, queue, now=NOW)
        await scheduler_tick(session, queue, now=NOW)
    assert await count(SourceCollectionJob) == 1
    assert len(queue.job_ids) == 1


async def test_missed_schedule_creates_only_one_catchup_job():
    source_id = await seed_source(next_at=NOW - timedelta(hours=5), interval=60)
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        jobs = await scheduler_tick(session, queue, now=NOW)
        source = await session.get(Source, source_id)
    assert len(jobs) == 1
    assert source.next_collection_at > NOW


async def test_multiple_sources_create_independent_jobs():
    await seed_source(next_at=NOW)
    await seed_source(next_at=NOW)
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        jobs = await scheduler_tick(session, queue, now=NOW)
    assert len(jobs) == 2
    assert len(queue.job_ids) == 2


async def test_jitter_does_not_duplicate_schedule_slot():
    await seed_source(next_at=NOW)
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        await scheduler_tick(session, queue, now=NOW)
        await scheduler_tick(session, queue, now=NOW + timedelta(seconds=1))
    assert await count(SourceCollectionJob) == 1


async def test_scheduler_redis_failure_is_visible_and_inventory_safe():
    await seed_source(next_at=NOW)
    async with AsyncSessionLocal() as session:
        with pytest.raises(RuntimeError, match="redis unavailable"):
            await scheduler_tick(session, FailingQueue(), now=NOW)
    assert await count(SourceCollectionJob) == 1
    assert await count(SupplierOffer) == 0


async def test_manual_collect_queues_job_when_enabled():
    source_id = await seed_source(enabled=True)
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        job = await create_manual_job(session, queue, source_id=source_id, mode=TelegramCollectionMode.BACKFILL, limit=5)
    assert job.status == SourceCollectionJobStatus.QUEUED
    assert job.job_type == SourceCollectionJobType.MANUAL_BACKFILL
    assert job.parameters == {"mode": "BACKFILL", "limit": 5}
    assert queue.job_ids == [str(job.id)]


async def test_manual_collect_rejects_disabled_source():
    source_id = await seed_source(enabled=False)
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError, match="disabled"):
            await create_manual_job(session, queue, source_id=source_id, mode=TelegramCollectionMode.INCREMENTAL)


async def test_create_collection_job_deduplicates_idempotency_key():
    source_id = await seed_source()
    async with AsyncSessionLocal() as session:
        first, first_created = await create_collection_job(
            session, source_id=source_id, job_type=SourceCollectionJobType.SCHEDULED_INCREMENTAL, scheduled_for=NOW
        )
        second, second_created = await create_collection_job(
            session, source_id=source_id, job_type=SourceCollectionJobType.SCHEDULED_INCREMENTAL, scheduled_for=NOW
        )
    assert first.id == second.id
    assert first_created is True
    assert second_created is False


async def test_worker_success_marks_job_succeeded():
    source_id = await seed_source()
    job_id = await make_job(source_id)
    async with AsyncSessionLocal() as session:
        job = await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=successful_collector)
    assert job.status == SourceCollectionJobStatus.SUCCEEDED
    assert job.collection_run_id is not None


async def test_worker_success_resets_failure_counter():
    source_id = await seed_source()
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
        source.consecutive_failures = 2
        await session.commit()
    job_id = await make_job(source_id)
    async with AsyncSessionLocal() as session:
        await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=successful_collector)
        source = await session.get(Source, source_id)
    assert source.consecutive_failures == 0
    assert source.last_success_at is not None


async def test_worker_success_after_failure_writes_recovery_audit():
    source_id = await seed_source()
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
        source.consecutive_failures = 1
        await session.commit()
    job_id = await make_job(source_id)
    async with AsyncSessionLocal() as session:
        await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=successful_collector)
    assert await count(AuditLog) == 1


@pytest.mark.parametrize("collector", [network_collector, rate_limit_collector])
async def test_worker_transient_failure_enters_retry_wait(collector):
    source_id = await seed_source()
    job_id = await make_job(source_id)
    async with AsyncSessionLocal() as session:
        job = await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=collector)
    assert job.status == SourceCollectionJobStatus.RETRY_WAIT
    assert job.attempt == 1
    assert job.scheduled_for > NOW


@pytest.mark.parametrize("collector", [auth_collector, access_collector, failed_result_collector])
async def test_worker_permanent_failure_marks_failed(collector):
    source_id = await seed_source()
    job_id = await make_job(source_id)
    async with AsyncSessionLocal() as session:
        job = await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=collector)
    assert job.status == SourceCollectionJobStatus.FAILED


async def test_worker_sanitizes_secret_words_in_failure():
    source_id = await seed_source()
    job_id = await make_job(source_id)
    async with AsyncSessionLocal() as session:
        job = await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=auth_collector)
    assert "api_hash" not in job.error_message
    assert "session" not in job.error_message
    assert "phone" not in job.error_message


async def test_worker_final_transient_attempt_fails():
    source_id = await seed_source()
    job_id = await make_job(source_id, attempt=3, max_attempts=3)
    async with AsyncSessionLocal() as session:
        job = await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=network_collector)
    assert job.status == SourceCollectionJobStatus.FAILED


async def test_worker_skips_when_source_disabled():
    source_id = await seed_source(enabled=False)
    job_id = await make_job(source_id)
    async with AsyncSessionLocal() as session:
        job = await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=successful_collector)
    assert job.status == SourceCollectionJobStatus.SKIPPED


async def test_worker_skips_when_source_lock_held():
    source_id = await seed_source()
    job_id = await make_job(source_id)
    async with AsyncSessionLocal() as session:
        job = await execute_job(session, job_id, lock_factory=lambda _: DenyLock(), collector=successful_collector)
    assert job.status == SourceCollectionJobStatus.SKIPPED
    assert job.error_code == "SOURCE_LOCKED"


async def test_duplicate_queue_delivery_is_terminal_idempotent(monkeypatch):
    source_id = await seed_source(next_at=NOW)
    queue = InMemoryQueueAdapter()
    monkeypatch.setattr("app.jobs.service.build_telegram_adapter", lambda: FakeTelegramAdapter([message(100, ["A", "B"])]))
    async with AsyncSessionLocal() as session:
        jobs = await scheduler_tick(session, queue, now=NOW)
        await execute_job(session, jobs[0].id, lock_factory=lambda _: AllowLock())
    before = {
        RawSourceRecord: await count(RawSourceRecord),
        SupplierSnapshot: await count(SupplierSnapshot),
        SupplierOfferSnapshot: await count(SupplierOfferSnapshot),
    }
    async with AsyncSessionLocal() as session:
        await execute_job(session, jobs[0].id, lock_factory=lambda _: AllowLock())
    after = {
        RawSourceRecord: await count(RawSourceRecord),
        SupplierSnapshot: await count(SupplierSnapshot),
        SupplierOfferSnapshot: await count(SupplierOfferSnapshot),
    }
    assert before == after


async def test_worker_skips_when_another_running_job_exists():
    source_id = await seed_source()
    await make_job(source_id, status=SourceCollectionJobStatus.RUNNING)
    job_id = await make_job(source_id)
    async with AsyncSessionLocal() as session:
        job = await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=successful_collector)
    assert job.status == SourceCollectionJobStatus.SKIPPED
    assert job.error_code == "SOURCE_ALREADY_RUNNING"


@pytest.mark.parametrize("terminal", [SourceCollectionJobStatus.SUCCEEDED, SourceCollectionJobStatus.FAILED, SourceCollectionJobStatus.CANCELLED, SourceCollectionJobStatus.SKIPPED])
async def test_worker_does_not_rerun_terminal_jobs(terminal):
    source_id = await seed_source()
    job_id = await make_job(source_id, status=terminal)
    async with AsyncSessionLocal() as session:
        job = await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=successful_collector)
    assert job.status == terminal
    assert await count(TelegramCollectionRun) == 0


async def test_due_retry_requeues_and_increments_attempt():
    source_id = await seed_source()
    job_id = await make_job(source_id, status=SourceCollectionJobStatus.RETRY_WAIT, scheduled_for=NOW - timedelta(seconds=1))
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        jobs = await enqueue_due_retries(session, queue, now=NOW)
    job = await load_job(job_id)
    assert jobs[0].id == job_id
    assert job.attempt == 2
    assert job.status == SourceCollectionJobStatus.QUEUED
    assert queue.job_ids == [str(job_id)]


async def test_future_retry_is_not_requeued():
    source_id = await seed_source()
    await make_job(source_id, status=SourceCollectionJobStatus.RETRY_WAIT, scheduled_for=NOW + timedelta(minutes=1))
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        jobs = await enqueue_due_retries(session, queue, now=NOW)
    assert jobs == []
    assert queue.job_ids == []


async def test_stale_running_recovers_to_retry_wait():
    source_id = await seed_source()
    job_id = await make_job(source_id, status=SourceCollectionJobStatus.RUNNING, scheduled_for=NOW)
    async with AsyncSessionLocal() as session:
        job = await session.get(SourceCollectionJob, job_id)
        job.started_at = NOW - timedelta(hours=1)
        await session.commit()
        jobs = await recover_stale_running_jobs(session, InMemoryQueueAdapter(), now=NOW)
    assert jobs[0].id == job_id
    assert (await load_job(job_id)).status == SourceCollectionJobStatus.RETRY_WAIT


async def test_stale_running_at_max_attempts_fails():
    source_id = await seed_source()
    job_id = await make_job(source_id, status=SourceCollectionJobStatus.RUNNING, attempt=3, max_attempts=3, scheduled_for=NOW)
    async with AsyncSessionLocal() as session:
        job = await session.get(SourceCollectionJob, job_id)
        job.started_at = NOW - timedelta(hours=1)
        await session.commit()
        await recover_stale_running_jobs(session, InMemoryQueueAdapter(), now=NOW)
    assert (await load_job(job_id)).status == SourceCollectionJobStatus.FAILED


async def test_non_stale_running_job_is_not_recovered():
    source_id = await seed_source()
    job_id = await make_job(source_id, status=SourceCollectionJobStatus.RUNNING, scheduled_for=NOW)
    async with AsyncSessionLocal() as session:
        job = await session.get(SourceCollectionJob, job_id)
        job.started_at = NOW - timedelta(seconds=10)
        await session.commit()
        jobs = await recover_stale_running_jobs(session, InMemoryQueueAdapter(), now=NOW)
    assert jobs == []
    assert (await load_job(job_id)).status == SourceCollectionJobStatus.RUNNING


async def test_completed_job_is_not_recovered():
    source_id = await seed_source()
    job_id = await make_job(source_id, status=SourceCollectionJobStatus.SUCCEEDED, scheduled_for=NOW)
    async with AsyncSessionLocal() as session:
        jobs = await recover_stale_running_jobs(session, InMemoryQueueAdapter(), now=NOW)
    assert jobs == []
    assert (await load_job(job_id)).status == SourceCollectionJobStatus.SUCCEEDED


async def test_source_status_reports_disabled():
    source_id = await seed_source(enabled=False)
    async with AsyncSessionLocal() as session:
        payload = await source_status(session, source_id, now=NOW)
    assert payload["operational_status"] == "DISABLED"


async def test_source_status_reports_never_run():
    source_id = await seed_source()
    async with AsyncSessionLocal() as session:
        payload = await source_status(session, source_id, now=NOW)
    assert payload["operational_status"] == "NEVER_RUN"


async def test_source_status_reports_degraded_and_error():
    source_id = await seed_source()
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
        source.last_collection_at = NOW
        source.last_success_at = NOW
        source.consecutive_failures = 1
        await session.commit()
        degraded = await source_status(session, source_id, now=NOW)
        source.consecutive_failures = 3
        await session.commit()
        error = await source_status(session, source_id, now=NOW)
    assert degraded["operational_status"] == "DEGRADED"
    assert error["operational_status"] == "ERROR"


async def test_source_status_reports_stale():
    source_id = await seed_source(interval=60)
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
        source.last_collection_at = NOW - timedelta(minutes=10)
        source.last_success_at = NOW - timedelta(minutes=10)
        await session.commit()
        payload = await source_status(session, source_id, now=NOW)
    assert payload["stale"] is True


async def test_stale_source_detection_does_not_touch_inventory():
    source_id = await seed_source(interval=60)
    before = await count(SupplierOffer)
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
        source.last_collection_at = NOW - timedelta(minutes=10)
        source.last_success_at = NOW - timedelta(minutes=10)
        await session.commit()
        payload = await source_status(session, source_id, now=NOW)
    assert payload["stale"] is True
    assert await count(SupplierOffer) == before


async def test_retry_failed_job_creates_retry_job():
    source_id = await seed_source()
    failed_id = await make_job(source_id, status=SourceCollectionJobStatus.FAILED)
    queue = InMemoryQueueAdapter()
    async with AsyncSessionLocal() as session:
        job = await retry_failed_job(session, queue, failed_id)
    assert job.job_type == SourceCollectionJobType.RETRY
    assert job.status == SourceCollectionJobStatus.QUEUED
    assert queue.job_ids == [str(job.id)]


async def test_retry_non_failed_job_rejected():
    source_id = await seed_source()
    job_id = await make_job(source_id, status=SourceCollectionJobStatus.SUCCEEDED)
    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError, match="FAILED"):
            await retry_failed_job(session, InMemoryQueueAdapter(), job_id)


async def test_api_manual_collect_returns_queued_job(client):
    source_id = await seed_source(enabled=True)
    queue = InMemoryQueueAdapter()
    app.dependency_overrides[get_queue_adapter] = lambda: queue
    try:
        response = await client.post(f"/api/v1/sources/{source_id}/collect", json={"mode": "INCREMENTAL"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "QUEUED"
    assert queue.job_ids == [response.json()["id"]]


async def test_api_lists_and_gets_jobs(client):
    source_id = await seed_source()
    job_id = await make_job(source_id)
    listing = await client.get("/api/v1/source-collection-jobs")
    single = await client.get(f"/api/v1/source-collection-jobs/{job_id}")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == str(job_id)
    assert single.status_code == 200
    assert single.json()["source_id"] == str(source_id)


async def test_api_filters_jobs_by_status(client):
    source_id = await seed_source()
    await make_job(source_id, status=SourceCollectionJobStatus.FAILED)
    await make_job(source_id, status=SourceCollectionJobStatus.SUCCEEDED)
    response = await client.get("/api/v1/source-collection-jobs?status_filter=FAILED")
    assert response.status_code == 200
    assert [job["status"] for job in response.json()] == ["FAILED"]


async def test_api_retries_failed_job(client):
    source_id = await seed_source()
    failed_id = await make_job(source_id, status=SourceCollectionJobStatus.FAILED)
    queue = InMemoryQueueAdapter()
    app.dependency_overrides[get_queue_adapter] = lambda: queue
    try:
        response = await client.post(f"/api/v1/source-collection-jobs/{failed_id}/retry")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["job_type"] == "RETRY"
    assert queue.job_ids == [response.json()["id"]]


async def test_api_source_status(client):
    source_id = await seed_source(enabled=True)
    response = await client.get(f"/api/v1/sources/{source_id}/status")
    assert response.status_code == 200
    assert response.json()["source_id"] == str(source_id)


async def test_api_operations_status(client):
    await seed_source(enabled=True)
    response = await client.get("/api/v1/operations/status")
    assert response.status_code == 200
    assert response.json()["enabled_sources"] == 1


async def test_no_supplier_inventory_is_created_by_empty_worker_job():
    source_id = await seed_source()
    job_id = await make_job(source_id)
    async with AsyncSessionLocal() as session:
        await execute_job(session, job_id, lock_factory=lambda _: AllowLock(), collector=successful_collector)
    assert await count(TelegramCollectionRun) == 1


async def test_two_sources_can_have_independent_jobs():
    first = await seed_source()
    second = await seed_source()
    first_job = await make_job(first)
    second_job = await make_job(second)
    async with AsyncSessionLocal() as session:
        await execute_job(session, first_job, lock_factory=lambda _: AllowLock(), collector=successful_collector)
        await execute_job(session, second_job, lock_factory=lambda _: AllowLock(), collector=successful_collector)
    assert await count(TelegramCollectionRun) == 2


async def test_full_e2e_scheduler_worker_telegram_snapshot_availability(monkeypatch):
    source_id = await seed_source(next_at=NOW)
    snapshots = [
        (100, ["A", "B", "C"], Availability.IN_STOCK, 0),
        (101, ["A", "C"], Availability.SUSPECT_MISSING, 1),
        (102, ["A", "C"], Availability.OUT_OF_STOCK, 2),
        (103, ["A", "B", "C"], Availability.IN_STOCK, 0),
    ]
    observed = []
    for offset, (message_id, keys, expected_status, expected_missing) in enumerate(snapshots):
        tick_at = NOW + timedelta(minutes=offset)
        async with AsyncSessionLocal() as session:
            source = await session.get(Source, source_id)
            source.next_collection_at = tick_at
            await session.commit()
            queue = InMemoryQueueAdapter()
            jobs = await scheduler_tick(session, queue, now=tick_at)
        monkeypatch.setattr("app.jobs.service.build_telegram_adapter", lambda keys=keys, message_id=message_id, offset=offset: FakeTelegramAdapter([message(message_id, keys, minutes=offset)]))
        async with AsyncSessionLocal() as session:
            await execute_job(session, jobs[0].id, lock_factory=lambda _: AllowLock())
        observed.append(await offer_state(source_id, "S939B"))
        assert observed[-1] == (expected_status, expected_missing)

    assert observed == [
        (Availability.IN_STOCK, 0),
        (Availability.SUSPECT_MISSING, 1),
        (Availability.OUT_OF_STOCK, 2),
        (Availability.IN_STOCK, 0),
    ]


async def test_missing_job_raises_value_error():
    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError, match="not found"):
            await execute_job(session, uuid.uuid4(), lock_factory=lambda _: AllowLock(), collector=successful_collector)
