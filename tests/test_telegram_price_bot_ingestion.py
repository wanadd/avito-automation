import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.integrations.telegram.bot_api import TelegramBotApiClient, redact_telegram_token
from app.integrations.telegram.types import TelegramNetworkError
from app.models.enums import SourceType, SupplierSnapshotType
from app.models.product import ProductVariant
from app.models.raw_source_record import RawSourceRecord
from app.models.source import Source
from app.models.supplier import Supplier
from app.models.supplier_offer import SupplierOffer
from app.models.telegram_price import TelegramPriceBatch, TelegramPriceBotState, TelegramPriceMessage, TelegramPriceSource
from app.services.telegram_prices import (
    BATCH_STATUS_PENDING_MAPPING,
    MESSAGE_STATUS_UNAUTHORIZED,
    MESSAGE_STATUS_UNSUPPORTED,
    map_telegram_price_source,
    poll_telegram_prices_bot,
    reprocess_telegram_price_batch,
    sanitize_telegram_error,
)

pytestmark = pytest.mark.usefixtures("clean_database")

BASE_TIME = datetime(2026, 9, 15, 10, tzinfo=UTC)


class FakeBotClient:
    token = "TEST_TOKEN"

    def __init__(self, updates=None, exc=None, send_exc=None):
        self.updates = updates or []
        self.exc = exc
        self.send_exc = send_exc
        self.sent_messages = []
        self.offsets = []

    async def get_updates(self, *, offset, timeout, limit):
        self.offsets.append(offset)
        if self.exc:
            raise self.exc
        return self.updates[:limit]

    async def send_message(self, *, chat_id, text):
        if self.send_exc:
            raise self.send_exc
        self.sent_messages.append({"chat_id": chat_id, "text": text})


@pytest.fixture(autouse=True)
def telegram_price_settings(monkeypatch):
    monkeypatch.setenv("TELEGRAM_PRICES_BOT_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_PRICES_BOT_TOKEN", "TEST_TOKEN")
    monkeypatch.setenv("TELEGRAM_API_BASE_URL", "https://tg-relay.planam.ru")
    monkeypatch.setenv("TELEGRAM_PRICES_ALLOWED_USER_IDS", "42")
    monkeypatch.setenv("TELEGRAM_PRICE_BATCH_WINDOW_SECONDS", "30")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def telegram_update(
    update_id,
    *,
    message_id=None,
    user_id=42,
    channel_id=-100777,
    title="Hello Mobile A41-A42",
    text="Samsung\n🇰🇼S25 ultra S938B 12/256 silverblue - 65300",
    seconds=0,
):
    timestamp = int((BASE_TIME + timedelta(seconds=seconds)).timestamp())
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id or update_id,
            "date": timestamp,
            "from": {"id": user_id, "is_bot": False, "first_name": "Operator"},
            "chat": {"id": 4200, "type": "private"},
            "forward_origin": {
                "type": "channel",
                "date": timestamp,
                "chat": {"id": channel_id, "type": "channel", "title": title, "username": "hello_mobile"},
                "message_id": message_id or update_id,
            },
            "text": text,
        },
    }


async def seed_supplier_source(channel_id=-100777):
    async with AsyncSessionLocal() as session:
        supplier = Supplier(code=f"supplier-{uuid.uuid4().hex[:8]}", name="Hello Supplier")
        session.add(supplier)
        await session.flush()
        source = Source(
            supplier_id=supplier.id,
            source_type=SourceType.TELEGRAM,
            external_key=f"telegram-channel:{channel_id}",
            name="Hello Mobile",
            external_chat_id=channel_id,
            title="Hello Mobile A41-A42",
            telegram_enabled=True,
            snapshot_type=SupplierSnapshotType.FULL,
            collection_enabled=False,
        )
        session.add(source)
        await session.commit()
        return supplier.id, source.id


async def count(model):
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


def test_bot_api_uses_configurable_relay_and_redacts_token():
    client = TelegramBotApiClient(token="TEST_TOKEN", base_url="https://tg-relay.planam.ru")
    assert client.method_url("getUpdates") == "https://tg-relay.planam.ru/botTEST_TOKEN/getUpdates"
    assert client.sanitized_method_url("getUpdates") == "https://tg-relay.planam.ru/bot[redacted]/getUpdates"
    assert "TEST_TOKEN" not in redact_telegram_token(client.method_url("sendMessage"), client.token)


def test_no_production_bot_api_fallback_to_localhost():
    settings = get_settings()
    assert settings.telegram_api_base_url == "https://tg-relay.planam.ru"
    assert "localhost" not in settings.telegram_api_base_url


def test_token_redaction_from_errors():
    error = sanitize_telegram_error(TelegramNetworkError("https://tg-relay.planam.ru/botTEST_TOKEN/getUpdates failed"), "TEST_TOKEN")
    assert "TEST_TOKEN" not in error
    assert "bot[redacted]" in error


async def test_unauthorized_user_rejected_without_import():
    async with AsyncSessionLocal() as session:
        result = await poll_telegram_prices_bot(session, FakeBotClient([telegram_update(1, user_id=99)]))
    assert result["updates"] == 1
    async with AsyncSessionLocal() as session:
        message = await session.scalar(select(TelegramPriceMessage))
    assert message.status == MESSAGE_STATUS_UNAUTHORIZED
    assert await count(TelegramPriceBatch) == 0
    assert await count(SupplierOffer) == 0


async def test_forwarded_channel_creates_stable_unknown_source_and_preserves_raw_message():
    async with AsyncSessionLocal() as session:
        await poll_telegram_prices_bot(session, FakeBotClient([telegram_update(10)]))
    async with AsyncSessionLocal() as session:
        source = await session.scalar(select(TelegramPriceSource))
        batch = await session.scalar(select(TelegramPriceBatch))
        message = await session.scalar(select(TelegramPriceMessage))
    assert source.telegram_channel_id == -100777
    assert source.title == "Hello Mobile A41-A42"
    assert source.source_id is None
    assert batch.status == BATCH_STATUS_PENDING_MAPPING
    assert message.raw_text.startswith("Samsung")
    assert message.raw_payload["message"]["from"] == {"id": 42, "is_bot": False}
    assert await count(SupplierOffer) == 0


async def test_title_change_does_not_create_duplicate_source():
    async with AsyncSessionLocal() as session:
        await poll_telegram_prices_bot(session, FakeBotClient([telegram_update(11, title="Hello Mobile")]))
        await poll_telegram_prices_bot(session, FakeBotClient([telegram_update(12, title="Hello Mobile New", seconds=60)]))
    assert await count(TelegramPriceSource) == 1
    async with AsyncSessionLocal() as session:
        source = await session.scalar(select(TelegramPriceSource))
    assert source.title == "Hello Mobile New"


async def test_mapping_and_reprocess_creates_supplier_offer_through_existing_pipeline():
    supplier_id, _ = await seed_supplier_source()
    async with AsyncSessionLocal() as session:
        await poll_telegram_prices_bot(session, FakeBotClient([telegram_update(20, channel_id=-100999)]))
        price_source = await session.scalar(select(TelegramPriceSource).where(TelegramPriceSource.telegram_channel_id == -100999))
        batch = await session.scalar(select(TelegramPriceBatch))
        await map_telegram_price_source(session, price_source.id, supplier_id)
        processed = await reprocess_telegram_price_batch(session, batch.id)
    assert processed.status == "COMPLETED"
    assert processed.accepted_rows == 1
    assert await count(RawSourceRecord) == 1
    assert await count(SupplierOffer) == 1


async def test_known_source_auto_processes_and_bot_reply_failure_does_not_rollback():
    await seed_supplier_source(channel_id=-100777)
    client = FakeBotClient([telegram_update(30)], send_exc=TelegramNetworkError("reply failed"))
    async with AsyncSessionLocal() as session:
        result = await poll_telegram_prices_bot(session, client)
    assert result["processed_batches"] == 1
    assert await count(SupplierOffer) == 1


async def test_duplicate_update_is_idempotent_and_advances_cursor():
    await seed_supplier_source(channel_id=-100777)
    update = telegram_update(40)
    async with AsyncSessionLocal() as session:
        await poll_telegram_prices_bot(session, FakeBotClient([update]))
        await poll_telegram_prices_bot(session, FakeBotClient([update]))
        state = await session.scalar(select(TelegramPriceBotState))
    assert state.last_update_id == 40
    assert await count(TelegramPriceMessage) == 1
    assert await count(SupplierOffer) == 1


async def test_two_consecutive_messages_batch_together_in_order():
    await seed_supplier_source(channel_id=-100777)
    updates = [
        telegram_update(50, message_id=500, text="Samsung\n🇰🇼S25 ultra S938B 12/256 silverblue - 65300", seconds=0),
        telegram_update(51, message_id=501, text="Samsung\n🇰🇼S25 ultra S939B 12/512 silverblue - 65000", seconds=10),
    ]
    async with AsyncSessionLocal() as session:
        await poll_telegram_prices_bot(session, FakeBotClient(updates))
        batch = await session.scalar(select(TelegramPriceBatch))
        raw = await session.get(RawSourceRecord, batch.raw_source_record_id)
    assert batch.message_count == 2
    assert "S938B" in raw.raw_text
    assert raw.raw_text.index("S938B") < raw.raw_text.index("S939B")
    assert await count(SupplierOffer) == 2


async def test_different_sender_source_or_window_gets_different_batches():
    async with AsyncSessionLocal() as session:
        await poll_telegram_prices_bot(
            session,
            FakeBotClient(
                [
                    telegram_update(60, channel_id=-1001, seconds=0),
                    telegram_update(61, channel_id=-1002, seconds=10),
                    telegram_update(62, channel_id=-1001, user_id=42, seconds=60),
                ]
            ),
        )
    assert await count(TelegramPriceBatch) == 3


async def test_unsupported_document_metadata_preserved_without_offer():
    update = telegram_update(70, text=None)
    update["message"]["document"] = {"file_id": "file-1", "file_name": "price.pdf", "mime_type": "application/pdf"}
    async with AsyncSessionLocal() as session:
        await poll_telegram_prices_bot(session, FakeBotClient([update]))
        saved = await session.scalar(select(TelegramPriceMessage))
    assert saved.status == MESSAGE_STATUS_UNSUPPORTED
    assert saved.raw_payload["message"]["document"]["file_name"] == "price.pdf"
    assert await count(SupplierOffer) == 0


async def test_api_auth_rbac_mapping_and_reprocess(client, unauthenticated_client):
    supplier_id, _ = await seed_supplier_source(channel_id=-100555)
    async with AsyncSessionLocal() as session:
        await poll_telegram_prices_bot(session, FakeBotClient([telegram_update(80, channel_id=-100556)]))
        price_source = await session.scalar(select(TelegramPriceSource).where(TelegramPriceSource.telegram_channel_id == -100556))
        batch = await session.scalar(select(TelegramPriceBatch))

    unauth = await unauthenticated_client.get("/api/v1/telegram-prices/sources")
    assert unauth.status_code == 401
    mapped = await client.post(f"/api/v1/telegram-prices/sources/{price_source.id}/map", json={"supplier_id": str(supplier_id)})
    assert mapped.status_code == 200, mapped.text
    processed = await client.post(f"/api/v1/telegram-prices/ingestions/{batch.id}/reprocess", json={})
    assert processed.status_code == 200, processed.text
    listing = await client.get("/api/v1/telegram-prices/ingestions")
    assert listing.status_code == 200
    assert listing.json()[0]["accepted_rows"] == 1
