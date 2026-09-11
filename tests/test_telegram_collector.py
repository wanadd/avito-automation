import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.api.v1.routes import get_telegram_adapter
from app.db.session import AsyncSessionLocal
from app.integrations.telegram.collector import check_telegram_source, collect_source, telegram_content_hash
from app.integrations.telegram.types import (
    TelegramAccessError,
    TelegramAuthError,
    TelegramChatInfo,
    TelegramMessage,
    TelegramNetworkError,
    TelegramRateLimitError,
)
from app.main import app
from app.models.audit_log import AuditLog
from app.models.enums import Availability, SourceType, SupplierSnapshotType, TelegramCollectionMode, TelegramCollectionRunStatus
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.product import ProductVariant
from app.models.raw_source_record import RawSourceRecord, RawSourceRecordRevision
from app.models.source import Source
from app.models.supplier_offer import SupplierOffer, SupplierOfferSnapshot
from app.models.supplier_snapshot import SupplierSnapshot, SupplierSnapshotItem
from app.models.telegram_collection import TelegramCollectionRun

pytestmark = pytest.mark.usefixtures("clean_database")


BASE_TIME = datetime(2026, 9, 11, 10, tzinfo=UTC)
LINES = {
    "A": "🇰🇼S25 ultra S938B 12/256 silverblue - 65300",
    "B": "🇰🇼S25 ultra S939B 12/512 silverblue - 65000",
    "B_NEW_PRICE": "🇰🇼S25 ultra S939B 12/512 silverblue - 63000",
    "C": "🇰🇼S25 ultra S940B 16/512 black - 85300",
}


class FakeTelegramAdapter:
    def __init__(self, messages=None, chat=None, exc=None):
        self.messages = messages or []
        self.chat = chat or TelegramChatInfo(external_chat_id=-1001234567890, title="Supplier Channel", username="supplier")
        self.exc = exc
        self.connected = False

    async def connect(self):
        if self.exc:
            raise self.exc
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def get_chat(self, *, external_chat_id=None, username=None):
        if self.exc:
            raise self.exc
        return replace(self.chat, latest_message_id=max([m.message_id for m in self.messages], default=None))

    async def fetch_messages(self, chat_id, *, limit):
        return list(self.messages)[:limit]

    async def fetch_messages_after(self, chat_id, *, after_message_id, limit):
        return [message for message in self.messages if after_message_id is None or message.message_id > after_message_id][:limit]

    async def get_message(self, chat_id, message_id):
        return next((message for message in self.messages if message.message_id == message_id), None)


def message(message_id, text, *, minutes=0, edit=False, media=False, caption=None, service=False):
    date = BASE_TIME + timedelta(minutes=minutes)
    return TelegramMessage(
        message_id=message_id,
        date=date,
        text=text,
        edit_date=date + timedelta(minutes=1) if edit else None,
        sender_id=42,
        reply_to_message_id=7,
        forward={"from": "origin"},
        has_media=media,
        media_type="photo" if media else None,
        caption=caption,
        service=service,
    )


def price_text(keys):
    return "Samsung 🇰🇷\n" + "\n".join(LINES[key] for key in keys)


async def seed_source(snapshot_type=SupplierSnapshotType.FULL, *, external_chat_id=-1001234567890, username=None):
    async with AsyncSessionLocal() as session:
        supplier = __import__("app.models.supplier", fromlist=["Supplier"]).Supplier(
            code=f"tg-{uuid.uuid4().hex[:8]}", name="Telegram Supplier"
        )
        session.add(supplier)
        await session.flush()
        source = Source(
            supplier_id=supplier.id,
            source_type=SourceType.TELEGRAM,
            external_key=f"tg-{uuid.uuid4().hex[:8]}",
            name="Telegram source",
            external_chat_id=external_chat_id,
            username=username,
            telegram_enabled=True,
            snapshot_type=snapshot_type,
        )
        session.add(source)
        await session.commit()
        return supplier.id, source.id


async def get_offer(source_id, code):
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
        variant = await session.scalar(select(ProductVariant).where(ProductVariant.manufacturer_model_code == code))
        offer = await session.scalar(
            select(SupplierOffer).where(
                SupplierOffer.supplier_id == source.supplier_id,
                SupplierOffer.product_variant_id == variant.id,
            )
        )
        return offer


async def count(model):
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def run_collect(source_id, adapter, mode=TelegramCollectionMode.BACKFILL, limit=None):
    async with AsyncSessionLocal() as session:
        return await collect_source(session, source_id, mode=mode, limit=limit, adapter=adapter)


async def test_fake_adapter_connects():
    adapter = FakeTelegramAdapter()
    await adapter.connect()
    assert adapter.connected is True
    await adapter.disconnect()
    assert adapter.connected is False


async def test_source_resolves_by_external_chat_id():
    _, source_id = await seed_source()
    result = await run_collect(source_id, FakeTelegramAdapter(messages=[]))
    assert result["status"] == "COMPLETED"


async def test_username_resolution_stores_chat_id():
    _, source_id = await seed_source(external_chat_id=None, username="supplier")
    async with AsyncSessionLocal() as session:
        result = await check_telegram_source(session, source_id, FakeTelegramAdapter())
        source = await session.get(Source, source_id)
    assert result["reachable"] is True
    assert source.external_chat_id == -1001234567890


async def test_incremental_collects_new_message():
    _, source_id = await seed_source()
    adapter = FakeTelegramAdapter(messages=[message(100, price_text(["A"])), message(101, price_text(["A", "B"]))])
    await run_collect(source_id, adapter, mode=TelegramCollectionMode.INCREMENTAL, limit=1)
    result = await run_collect(source_id, adapter, mode=TelegramCollectionMode.INCREMENTAL)
    assert result["new_records"] == 1
    assert result["last_message_id"] == 101


async def test_backfill_respects_limit():
    _, source_id = await seed_source()
    adapter = FakeTelegramAdapter(messages=[message(i, price_text(["A"]), minutes=i) for i in range(100, 105)])
    result = await run_collect(source_id, adapter, limit=2)
    assert result["fetched"] == 2
    assert await count(RawSourceRecord) == 2


async def test_duplicate_unchanged_message_idempotent():
    _, source_id = await seed_source()
    adapter = FakeTelegramAdapter(messages=[message(100, price_text(["A"]))])
    first = await run_collect(source_id, adapter)
    before = {RawSourceRecord: await count(RawSourceRecord), SupplierSnapshot: await count(SupplierSnapshot), SupplierOfferSnapshot: await count(SupplierOfferSnapshot)}
    second = await run_collect(source_id, adapter)
    after = {RawSourceRecord: await count(RawSourceRecord), SupplierSnapshot: await count(SupplierSnapshot), SupplierOfferSnapshot: await count(SupplierOfferSnapshot)}
    assert first["new_records"] == 1
    assert second["duplicate_records"] == 1
    assert before == after


async def test_same_message_id_across_two_sources_independent():
    _, first_source = await seed_source()
    _, second_source = await seed_source(external_chat_id=-100222)
    await run_collect(first_source, FakeTelegramAdapter(messages=[message(100, price_text(["A"]))]))
    await run_collect(second_source, FakeTelegramAdapter(messages=[message(100, price_text(["A"]))], chat=TelegramChatInfo(-100222)))
    assert await count(RawSourceRecord) == 2


@pytest.mark.parametrize("telegram_message", [message(100, ""), message(100, None), message(100, None, service=True)])
async def test_empty_or_service_message_ignored(telegram_message):
    _, source_id = await seed_source()
    result = await run_collect(source_id, FakeTelegramAdapter(messages=[telegram_message]))
    assert result["ignored_records"] == 1
    assert await count(SupplierSnapshot) == 0


async def test_media_only_ignored_safely():
    _, source_id = await seed_source()
    result = await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, None, media=True)]))
    assert result["ignored_records"] == 1
    assert await count(SupplierSnapshot) == 0


async def test_caption_processed():
    _, source_id = await seed_source()
    result = await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, None, media=True, caption=price_text(["A"]))]))
    assert result["new_records"] == 1
    assert await count(SupplierOffer) == 1


async def test_raw_text_preserved_exactly():
    _, source_id = await seed_source()
    text = price_text(["A"])
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, text)]))
    async with AsyncSessionLocal() as session:
        raw = await session.scalar(select(RawSourceRecord))
    assert raw.raw_text == text


async def test_metadata_preserved():
    _, source_id = await seed_source()
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A"]), edit=True)]))
    async with AsyncSessionLocal() as session:
        revision = await session.scalar(select(RawSourceRecordRevision))
    assert revision.raw_payload["telegram_message_id"] == 100
    assert revision.raw_payload["sender_id"] == 42
    assert revision.raw_payload["reply_to"] == 7
    assert revision.raw_payload["forward"] == {"from": "origin"}


def test_content_hash_deterministic():
    assert telegram_content_hash("same") == telegram_content_hash("same")
    assert telegram_content_hash("same") != telegram_content_hash("different")


async def test_edited_message_detected_and_old_evidence_preserved():
    _, source_id = await seed_source()
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(200, price_text(["B"]))]))
    result = await run_collect(source_id, FakeTelegramAdapter(messages=[message(200, price_text(["B_NEW_PRICE"]), edit=True)]))
    async with AsyncSessionLocal() as session:
        raw = await session.scalar(select(RawSourceRecord))
        revisions = list(await session.scalars(select(RawSourceRecordRevision).order_by(RawSourceRecordRevision.revision_no)))
    assert result["edited_records"] == 1
    assert raw.raw_text == price_text(["B"])
    assert [revision.raw_content for revision in revisions] == [price_text(["B"]), price_text(["B_NEW_PRICE"])]


async def test_edited_message_triggers_downstream_once():
    _, source_id = await seed_source()
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(200, price_text(["B"]))]))
    offer = await get_offer(source_id, "S939B")
    before = await count(SupplierOfferSnapshot)
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(200, price_text(["B_NEW_PRICE"]), edit=True)]))
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(200, price_text(["B_NEW_PRICE"]), edit=True)]))
    after_offer = await get_offer(source_id, "S939B")
    assert offer.price_minor == 6500000
    assert after_offer.price_minor == 6300000
    assert await count(SupplierOfferSnapshot) == before + 1


async def test_cursor_advances_after_raw_persist():
    _, source_id = await seed_source()
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A"]))]))
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
    assert source.last_collected_message_id == 100


async def test_cursor_does_not_advance_on_raw_persist_failure(monkeypatch):
    _, source_id = await seed_source()

    async def fail_persist(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.integrations.telegram.collector.persist_message_revision", fail_persist)
    result = await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A"]))]))
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
    assert result["failed_records"] == 1
    assert source.last_collected_message_id is None


async def test_downstream_failure_does_not_duplicate_raw_evidence(monkeypatch):
    _, source_id = await seed_source()

    async def fail_process(*args, **kwargs):
        raise RuntimeError("processor down")

    monkeypatch.setattr("app.integrations.telegram.collector.process_snapshot", fail_process)
    first = await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A"]))]))
    second = await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A"]))]))
    assert first["failed_records"] == 1
    assert second["duplicate_records"] == 1
    assert await count(RawSourceRecord) == 1


async def test_retry_existing_snapshot_safe():
    _, source_id = await seed_source()
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A"]))]))
    async with AsyncSessionLocal() as session:
        snapshot = await session.scalar(select(SupplierSnapshot))
        from app.services.supplier_snapshots import process_snapshot

        await process_snapshot(session, snapshot.id)
    assert await count(SupplierSnapshotItem) == 1


@pytest.mark.parametrize("snapshot_type", [SupplierSnapshotType.FULL, SupplierSnapshotType.PARTIAL])
async def test_source_snapshot_type_creates_matching_snapshot(snapshot_type):
    _, source_id = await seed_source(snapshot_type=snapshot_type)
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A"]))]))
    async with AsyncSessionLocal() as session:
        snapshot = await session.scalar(select(SupplierSnapshot))
    assert snapshot.snapshot_type == snapshot_type


async def test_full_collector_feeds_availability_pipeline():
    _, source_id = await seed_source()
    adapter = FakeTelegramAdapter(
        messages=[
            message(100, price_text(["A", "B", "C"]), minutes=0),
            message(101, price_text(["A", "C"]), minutes=1),
            message(102, price_text(["A", "C"]), minutes=2),
            message(103, price_text(["A", "B", "C"]), minutes=3),
        ]
    )
    await run_collect(source_id, adapter)
    offer = await get_offer(source_id, "S939B")
    assert offer.availability == Availability.IN_STOCK
    assert offer.consecutive_missing_count == 0


async def test_partial_collector_cannot_missing_detect():
    _, source_id = await seed_source(snapshot_type=SupplierSnapshotType.PARTIAL)
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A", "B"]))]))
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(101, price_text(["A"]))]), mode=TelegramCollectionMode.INCREMENTAL)
    offer = await get_offer(source_id, "S939B")
    assert offer.availability == Availability.IN_STOCK
    assert offer.consecutive_missing_count == 0


async def test_duplicate_collection_does_not_double_missing_count():
    _, source_id = await seed_source()
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A", "B"]))]))
    adapter = FakeTelegramAdapter(messages=[message(101, price_text(["A"]))])
    await run_collect(source_id, adapter, mode=TelegramCollectionMode.INCREMENTAL)
    await run_collect(source_id, adapter)
    offer = await get_offer(source_id, "S939B")
    assert offer.consecutive_missing_count == 1


async def test_messages_processed_oldest_to_newest():
    _, source_id = await seed_source()
    adapter = FakeTelegramAdapter(
        messages=[
            message(103, price_text(["A", "B", "C"]), minutes=3),
            message(102, price_text(["A", "C"]), minutes=2),
            message(101, price_text(["A", "C"]), minutes=1),
            message(100, price_text(["A", "B", "C"]), minutes=0),
        ]
    )
    await run_collect(source_id, adapter)
    offer = await get_offer(source_id, "S939B")
    assert offer.availability == Availability.IN_STOCK
    assert offer.consecutive_missing_count == 0


@pytest.mark.parametrize("exc", [TelegramAuthError("unauthorized"), TelegramAccessError("private"), TelegramNetworkError("timeout")])
async def test_collection_error_does_not_affect_inventory(exc):
    _, source_id = await seed_source()
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A", "B"]))]))
    before = await get_offer(source_id, "S939B")
    result = await run_collect(source_id, FakeTelegramAdapter(exc=exc))
    after = await get_offer(source_id, "S939B")
    assert result["status"] == "FAILED"
    assert before.availability == after.availability
    assert before.consecutive_missing_count == after.consecutive_missing_count


async def test_flood_wait_handled_safely():
    _, source_id = await seed_source()
    result = await run_collect(source_id, FakeTelegramAdapter(exc=TelegramRateLimitError(3600)))
    assert result["status"] == "FAILED"
    assert "3600" in result["error"]


async def test_collection_run_created_and_counts_correct():
    _, source_id = await seed_source()
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A"])), message(101, "")]))
    async with AsyncSessionLocal() as session:
        run = await session.scalar(select(TelegramCollectionRun))
    assert run.status == TelegramCollectionRunStatus.COMPLETED
    assert run.fetched_count == 2
    assert run.new_count == 1
    assert run.ignored_count == 1


async def test_source_last_collection_fields_correct():
    _, source_id = await seed_source()
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A"]))]))
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
    assert source.last_collection_status == TelegramCollectionRunStatus.COMPLETED
    assert source.last_collection_at is not None
    assert source.last_collection_error is None


async def test_api_collect_endpoint(client):
    _, source_id = await seed_source()
    fake = FakeTelegramAdapter(messages=[message(100, price_text(["A"]))])
    app.dependency_overrides[get_telegram_adapter] = lambda: fake
    try:
        response = await client.post(f"/api/v1/sources/{source_id}/collect", json={"mode": "BACKFILL", "limit": 10})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["new_records"] == 1


async def test_api_list_and_get_collection_runs(client):
    _, source_id = await seed_source()
    await run_collect(source_id, FakeTelegramAdapter(messages=[message(100, price_text(["A"]))]))
    listing = await client.get("/api/v1/telegram-collection-runs")
    assert listing.status_code == 200
    run_id = listing.json()[0]["id"]
    single = await client.get(f"/api/v1/telegram-collection-runs/{run_id}")
    assert single.status_code == 200
    assert single.json()["source_id"] == str(source_id)


async def test_telegram_test_endpoint_sanitized(client):
    _, source_id = await seed_source()
    app.dependency_overrides[get_telegram_adapter] = lambda: FakeTelegramAdapter()
    try:
        response = await client.post(f"/api/v1/sources/{source_id}/telegram-test")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["reachable"] is True
    assert "session" not in str(payload).lower()
    assert "api_hash" not in str(payload).lower()


async def test_no_credentials_exposed_in_failed_api_response(client):
    _, source_id = await seed_source()
    app.dependency_overrides[get_telegram_adapter] = lambda: FakeTelegramAdapter(
        exc=TelegramAuthError("bad api_hash session phone password")
    )
    try:
        response = await client.post(f"/api/v1/sources/{source_id}/collect", json={"mode": "BACKFILL", "limit": 1})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "api_hash" not in response.text
    assert "session" not in response.text
    assert "phone" not in response.text
    assert "password" not in response.text


async def test_no_session_artifacts_are_tracked_by_git():
    import subprocess

    result = subprocess.run(["git", "ls-files"], cwd="C:\\Projects\\avito-automation", capture_output=True, text=True, check=True)
    tracked = result.stdout.lower().splitlines()
    assert not any(path.endswith(".session") or path.endswith(".session-journal") for path in tracked)
    assert ".env" not in tracked
