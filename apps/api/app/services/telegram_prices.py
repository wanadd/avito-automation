import hashlib
import logging
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.telegram.bot_api import TelegramBotApiClient, redact_telegram_token
from app.integrations.telegram.collector import sanitize_error
from app.integrations.telegram.types import TelegramCollectorError, TelegramNetworkError, TelegramRateLimitError
from app.models.enums import ProcessingStatus, SourceType, SupplierSnapshotType
from app.models.raw_source_record import RawSourceRecord, RawSourceRecordRevision
from app.models.source import Source
from app.models.supplier import Supplier
from app.models.supplier_snapshot import SupplierSnapshot
from app.models.telegram_price import TelegramPriceBatch, TelegramPriceBotState, TelegramPriceMessage, TelegramPriceSource
from app.schemas.raw_source_record import RawSourceRecordCreate
from app.schemas.supplier_snapshot import SupplierSnapshotCreate
from app.services.raw_records import create_raw_record
from app.services.supplier_snapshots import create_snapshot, process_snapshot

logger = logging.getLogger("app.telegram_prices")

BATCH_STATUS_RECEIVED = "RECEIVED"
BATCH_STATUS_COMPLETED = "COMPLETED"
BATCH_STATUS_FAILED = "FAILED"
BATCH_STATUS_PENDING_MAPPING = "PENDING_MAPPING"
BATCH_STATUS_REPROCESSING = "REPROCESSING"
BATCH_STATUS_UNSUPPORTED = "UNSUPPORTED_FORMAT"
BATCH_RECEIVING_STATUSES = {BATCH_STATUS_RECEIVED, BATCH_STATUS_PENDING_MAPPING}
MESSAGE_STATUS_DUPLICATE = "DUPLICATE"
MESSAGE_STATUS_INGESTED = "INGESTED"
MESSAGE_STATUS_UNAUTHORIZED = "UNAUTHORIZED"
MESSAGE_STATUS_UNSUPPORTED = "UNSUPPORTED_FORMAT"


def utc_now() -> datetime:
    return datetime.now(UTC)


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def message_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message") or update.get("edited_message") or update.get("channel_post")
    return message if isinstance(message, dict) else None


def sender_user_id(message: dict[str, Any]) -> int | None:
    sender = message.get("from")
    return int(sender["id"]) if isinstance(sender, dict) and sender.get("id") is not None else None


def destination_chat_id(message: dict[str, Any]) -> int | None:
    chat = message.get("chat")
    return int(chat["id"]) if isinstance(chat, dict) and chat.get("id") is not None else None


def unix_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


def forwarded_channel(message: dict[str, Any]) -> dict[str, Any] | None:
    origin = message.get("forward_origin")
    if isinstance(origin, dict) and origin.get("type") == "channel":
        chat = origin.get("chat")
        if isinstance(chat, dict) and chat.get("id") is not None:
            return {
                "id": int(chat["id"]),
                "type": chat.get("type"),
                "title": chat.get("title") or origin.get("chat_title"),
                "username": chat.get("username"),
            }
    forward_from_chat = message.get("forward_from_chat")
    if isinstance(forward_from_chat, dict) and forward_from_chat.get("id") is not None:
        return {
            "id": int(forward_from_chat["id"]),
            "type": forward_from_chat.get("type"),
            "title": forward_from_chat.get("title"),
            "username": forward_from_chat.get("username"),
        }
    return None


def telegram_message_text(message: dict[str, Any]) -> str | None:
    text = message.get("text") if isinstance(message.get("text"), str) else message.get("caption")
    return text if isinstance(text, str) and text.strip() else None


def bot_reply_for_batch(batch: TelegramPriceBatch, source: TelegramPriceSource | None) -> str:
    title = source.title if source and source.title else "Telegram source"
    if batch.status == BATCH_STATUS_PENDING_MAPPING:
        return f"Прайс сохранён.\nИсточник пока не привязан к поставщику:\n{title}\nПривяжите источник в панели управления."
    if batch.status == BATCH_STATUS_UNSUPPORTED:
        return "Файл получен и сохранён, но этот формат пока требует ручной обработки."
    if batch.duplicate:
        return "Этот прайс уже получен ранее."
    return (
        f"Прайс получен.\nПоставщик: {title}\nСообщений: {batch.message_count}\n"
        f"Строк найдено: {batch.parsed_rows}\nРаспознано: {batch.accepted_rows}\nТребуют проверки: {batch.review_rows}"
    )


def bot_reply_for_rejection(status: str) -> str:
    if status == MESSAGE_STATUS_UNAUTHORIZED:
        return "Доступ к загрузке прайсов не разрешён."
    return "Сообщение сохранено, но этот формат пока требует ручной обработки."


async def poll_telegram_prices_bot(session: AsyncSession, client: TelegramBotApiClient) -> dict[str, Any]:
    settings = get_settings()
    if not settings.telegram_prices_bot_enabled:
        return {"enabled": False, "updates": 0, "processed_batches": 0}

    state = await get_bot_state(session)
    state.last_poll_at = utc_now()
    await session.commit()
    offset = state.last_update_id + 1 if state.last_update_id is not None else None

    try:
        updates = await client.get_updates(
            offset=offset,
            timeout=settings.telegram_prices_poll_timeout_seconds,
            limit=settings.telegram_price_poll_limit,
        )
    except (TelegramNetworkError, TelegramRateLimitError) as exc:
        state.last_api_error = sanitize_telegram_error(exc, client.token)
        await session.commit()
        raise

    touched_batch_ids: set[uuid.UUID] = set()
    replies: list[str] = []
    max_update_id = state.last_update_id
    for update in updates:
        max_update_id = max(max_update_id or int(update["update_id"]), int(update["update_id"]))
        result = await persist_update(session, update)
        if result.get("batch_id") and result.get("should_process"):
            touched_batch_ids.add(result["batch_id"])
        if result.get("reply"):
            replies.append(result["reply"])

    processed_batches = 0
    for batch_id in sorted(touched_batch_ids, key=str):
        batch = await session.get(TelegramPriceBatch, batch_id)
        if batch is None:
            continue
        if batch.status != BATCH_STATUS_PENDING_MAPPING:
            await reprocess_telegram_price_batch(session, batch.id)
            processed_batches += 1
        await session.refresh(batch)
        source = await session.get(TelegramPriceSource, batch.telegram_price_source_id) if batch.telegram_price_source_id else None
        reply = bot_reply_for_batch(batch, source)
        batch.response_text = reply
        await session.commit()
        if batch.destination_chat_id is not None:
            await safe_send_message(client, chat_id=batch.destination_chat_id, text=reply)

    state.last_update_id = max_update_id
    state.last_success_poll_at = utc_now()
    state.last_api_error = None
    if processed_batches:
        state.last_successful_price_ingestion_at = state.last_success_poll_at
    await session.commit()
    return {"enabled": True, "updates": len(updates), "processed_batches": processed_batches, "replies": replies}


async def safe_send_message(client: TelegramBotApiClient, *, chat_id: int, text: str) -> None:
    try:
        await client.send_message(chat_id=chat_id, text=text)
    except TelegramCollectorError as exc:
        logger.warning("telegram_price_reply_failed", extra={"error": sanitize_telegram_error(exc, client.token)})


async def persist_update(session: AsyncSession, update: dict[str, Any]) -> dict[str, Any]:
    update_id = int(update["update_id"])
    existing = await session.scalar(select(TelegramPriceMessage).where(TelegramPriceMessage.update_id == update_id))
    if existing is not None:
        return {
            "status": MESSAGE_STATUS_DUPLICATE,
            "batch_id": existing.batch_id,
            "should_process": False,
            "reply": "Этот прайс уже получен ранее.",
        }

    message = message_from_update(update)
    if message is None:
        saved = TelegramPriceMessage(update_id=update_id, status=MESSAGE_STATUS_UNSUPPORTED, raw_payload=update, error="NO_MESSAGE")
        session.add(saved)
        await session.commit()
        return {"status": saved.status, "reply": bot_reply_for_rejection(saved.status)}

    user_id = sender_user_id(message)
    chat_id = destination_chat_id(message)
    allowed = get_settings().telegram_prices_allowed_user_id_set
    if user_id is None or user_id not in allowed:
        saved = TelegramPriceMessage(
            update_id=update_id,
            message_id=message.get("message_id"),
            sender_user_id=user_id,
            destination_chat_id=chat_id,
            message_date=unix_datetime(message.get("date")),
            status=MESSAGE_STATUS_UNAUTHORIZED,
            raw_payload=sanitized_update_payload(update),
            error="UNAUTHORIZED_SENDER",
        )
        session.add(saved)
        await session.commit()
        return {"status": saved.status, "reply": bot_reply_for_rejection(saved.status)}

    channel = forwarded_channel(message)
    text = telegram_message_text(message)
    if channel is None or text is None:
        saved = TelegramPriceMessage(
            update_id=update_id,
            message_id=message.get("message_id"),
            sender_user_id=user_id,
            destination_chat_id=chat_id,
            message_date=unix_datetime(message.get("date")),
            status=MESSAGE_STATUS_UNSUPPORTED,
            raw_text=text,
            caption=message.get("caption") if isinstance(message.get("caption"), str) else None,
            forward_origin=message.get("forward_origin"),
            raw_payload=sanitized_update_payload(update),
            error="UNSUPPORTED_OR_NOT_FORWARDED_CHANNEL_TEXT",
        )
        session.add(saved)
        await session.commit()
        return {"status": saved.status, "reply": bot_reply_for_rejection(saved.status)}

    price_source = await upsert_telegram_price_source(session, channel, unix_datetime(message.get("date")) or utc_now())
    batch = await find_or_create_batch(session, price_source, user_id=user_id, destination_chat_id=chat_id, message_at=unix_datetime(message.get("date")) or utc_now())
    saved = TelegramPriceMessage(
        batch_id=batch.id,
        telegram_price_source_id=price_source.id,
        update_id=update_id,
        message_id=message.get("message_id"),
        sender_user_id=user_id,
        destination_chat_id=chat_id,
        message_date=unix_datetime(message.get("date")),
        status=MESSAGE_STATUS_INGESTED,
        content_hash=content_hash(text),
        raw_text=text,
        caption=message.get("caption") if isinstance(message.get("caption"), str) else None,
        forward_origin=message.get("forward_origin"),
        raw_payload=sanitized_update_payload(update),
    )
    session.add(saved)
    batch.message_count += 1
    batch.first_message_at = min(filter(None, [batch.first_message_at, saved.message_date]), default=saved.message_date)
    batch.last_message_at = max(filter(None, [batch.last_message_at, saved.message_date]), default=saved.message_date)
    batch.source_id = price_source.source_id
    batch.status = BATCH_STATUS_RECEIVED if price_source.source_id else BATCH_STATUS_PENDING_MAPPING
    price_source.last_received_at = utc_now()
    await session.commit()
    return {"status": saved.status, "batch_id": batch.id, "should_process": price_source.source_id is not None}


async def upsert_telegram_price_source(session: AsyncSession, channel: dict[str, Any], received_at: datetime) -> TelegramPriceSource:
    source = await session.scalar(
        select(TelegramPriceSource).where(TelegramPriceSource.telegram_channel_id == int(channel["id"]))
    )
    if source is None:
        mapped_source = await session.scalar(select(Source).where(Source.external_chat_id == int(channel["id"])))
        source = TelegramPriceSource(
            telegram_channel_id=int(channel["id"]),
            chat_type=channel.get("type"),
            title=channel.get("title"),
            username=channel.get("username"),
            source_id=mapped_source.id if mapped_source is not None else None,
            last_seen_at=received_at,
        )
        session.add(source)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            source = await session.scalar(
                select(TelegramPriceSource).where(TelegramPriceSource.telegram_channel_id == int(channel["id"]))
            )
            if source is None:
                raise
    source.chat_type = channel.get("type")
    source.title = channel.get("title")
    source.username = channel.get("username")
    if source.source_id is None:
        mapped_source = await session.scalar(select(Source).where(Source.external_chat_id == int(channel["id"])))
        if mapped_source is not None:
            source.source_id = mapped_source.id
    source.last_seen_at = received_at
    await session.commit()
    await session.refresh(source)
    return source


async def find_or_create_batch(
    session: AsyncSession,
    price_source: TelegramPriceSource,
    *,
    user_id: int,
    destination_chat_id: int | None,
    message_at: datetime,
) -> TelegramPriceBatch:
    cutoff = message_at - timedelta(seconds=get_settings().telegram_price_batch_window_seconds)
    batch = await session.scalar(
        select(TelegramPriceBatch)
        .where(
            TelegramPriceBatch.telegram_price_source_id == price_source.id,
            TelegramPriceBatch.submitted_by_user_id == user_id,
            TelegramPriceBatch.last_message_at >= cutoff,
            TelegramPriceBatch.status.in_(BATCH_RECEIVING_STATUSES),
        )
        .order_by(TelegramPriceBatch.last_message_at.desc())
        .limit(1)
    )
    if batch is not None:
        return batch
    batch = TelegramPriceBatch(
        telegram_price_source_id=price_source.id,
        source_id=price_source.source_id,
        submitted_by_user_id=user_id,
        destination_chat_id=destination_chat_id,
        status=BATCH_STATUS_RECEIVED if price_source.source_id else BATCH_STATUS_PENDING_MAPPING,
        first_message_at=message_at,
        last_message_at=message_at,
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    return batch


async def reprocess_telegram_price_batch(session: AsyncSession, batch_id: uuid.UUID) -> TelegramPriceBatch:
    batch = await session.scalar(select(TelegramPriceBatch).where(TelegramPriceBatch.id == batch_id).with_for_update())
    if batch is None:
        raise ValueError("TelegramPriceBatch not found")
    price_source = await session.get(TelegramPriceSource, batch.telegram_price_source_id) if batch.telegram_price_source_id else None
    if price_source is None or price_source.source_id is None:
        batch.status = BATCH_STATUS_PENDING_MAPPING
        await session.commit()
        return batch
    source = await session.get(Source, price_source.source_id)
    if source is None:
        batch.status = BATCH_STATUS_PENDING_MAPPING
        batch.error = "MAPPED_SOURCE_NOT_FOUND"
        await session.commit()
        return batch

    messages = list(
        await session.scalars(
            select(TelegramPriceMessage)
            .where(TelegramPriceMessage.batch_id == batch.id, TelegramPriceMessage.status == MESSAGE_STATUS_INGESTED)
            .order_by(TelegramPriceMessage.message_date, TelegramPriceMessage.message_id)
        )
    )
    combined_text = "\n".join(message.raw_text or message.caption or "" for message in messages if message.raw_text or message.caption)
    batch.status = BATCH_STATUS_REPROCESSING
    batch.source_id = source.id
    await session.commit()

    raw_record, revision, revision_kind = await persist_batch_raw_revision(session, source, batch, messages, combined_text)
    snapshot = await create_snapshot(
        session,
        SupplierSnapshotCreate(
            supplier_id=source.supplier_id,
            source_id=source.id,
            raw_source_record_id=raw_record.id,
            raw_source_record_revision_id=revision.id,
            external_snapshot_id=f"telegram-bot-batch:{batch.id}:r{revision.revision_no}",
            snapshot_type=source.snapshot_type,
            captured_at=batch.last_message_at,
        ),
    )
    summary = await process_snapshot(session, snapshot.id)
    batch.raw_source_record_id = raw_record.id
    batch.raw_source_record_revision_id = revision.id
    batch.supplier_snapshot_id = snapshot.id
    batch.parsed_rows = int(summary.get("parsed_items") or 0)
    batch.accepted_rows = int(summary.get("offers_seen") or 0)
    batch.review_rows = int(summary.get("review_count") or 0) + int(summary.get("conflicts_count") or 0)
    batch.failed_rows = int(summary.get("parser_error_count") or 0)
    batch.duplicate = revision_kind == "duplicate"
    batch.status = BATCH_STATUS_COMPLETED if snapshot.status.value == "COMPLETED" else snapshot.status.value
    batch.error = snapshot.quality_gate_reason
    batch.processed_at = utc_now()
    await session.commit()
    await session.refresh(batch)
    return batch


async def persist_batch_raw_revision(
    session: AsyncSession,
    source: Source,
    batch: TelegramPriceBatch,
    messages: list[TelegramPriceMessage],
    combined_text: str,
) -> tuple[RawSourceRecord, RawSourceRecordRevision, str]:
    payload = {
        "provider": "telegram_bot_api",
        "telegram_price_batch_id": str(batch.id),
        "message_count": len(messages),
        "messages": [
            {
                "update_id": message.update_id,
                "message_id": message.message_id,
                "sender_user_id": message.sender_user_id,
                "destination_chat_id": message.destination_chat_id,
                "message_date": message.message_date.isoformat() if message.message_date else None,
                "forward_origin": message.forward_origin,
            }
            for message in messages
        ],
    }
    raw_record = await create_raw_record(
        session,
        RawSourceRecordCreate(
            source_id=source.id,
            external_record_id=f"telegram-bot-batch:{batch.id}",
            raw_text=combined_text,
            raw_payload=payload,
            source_published_at=batch.last_message_at,
            processing_status=ProcessingStatus.NEW,
        ),
    )
    message_hash = content_hash(combined_text)
    revision = await session.scalar(
        select(RawSourceRecordRevision)
        .where(RawSourceRecordRevision.raw_source_record_id == raw_record.id)
        .order_by(RawSourceRecordRevision.revision_no.desc())
        .limit(1)
    )
    if revision and revision.content_hash == message_hash:
        return raw_record, revision, "duplicate"
    next_revision = (await session.scalar(select(func.max(RawSourceRecordRevision.revision_no)).where(RawSourceRecordRevision.raw_source_record_id == raw_record.id)) or 0) + 1
    revision = RawSourceRecordRevision(
        raw_source_record_id=raw_record.id,
        revision_no=next_revision,
        content_hash=message_hash,
        raw_content=combined_text,
        raw_payload=payload,
        external_updated_at=batch.last_message_at,
    )
    session.add(revision)
    await session.commit()
    await session.refresh(revision)
    return raw_record, revision, "new"


async def map_telegram_price_source(session: AsyncSession, price_source_id: uuid.UUID, supplier_id: uuid.UUID) -> TelegramPriceSource:
    price_source = await session.get(TelegramPriceSource, price_source_id)
    supplier = await session.get(Supplier, supplier_id)
    if price_source is None:
        raise ValueError("TelegramPriceSource not found")
    if supplier is None:
        raise ValueError("Supplier not found")
    source = None
    if price_source.source_id is not None:
        source = await session.get(Source, price_source.source_id)
    if source is None:
        source = await session.scalar(select(Source).where(Source.external_chat_id == price_source.telegram_channel_id))
    if source is None:
        source = Source(
            supplier_id=supplier.id,
            source_type=SourceType.TELEGRAM,
            external_key=f"telegram-channel:{price_source.telegram_channel_id}",
            name=price_source.title or f"Telegram channel {price_source.telegram_channel_id}",
            external_chat_id=price_source.telegram_channel_id,
            username=price_source.username,
            title=price_source.title,
            telegram_enabled=True,
            snapshot_type=SupplierSnapshotType.FULL,
            collection_enabled=False,
        )
        session.add(source)
        await session.flush()
    else:
        source.supplier_id = supplier.id
        source.username = price_source.username
        source.title = price_source.title
        source.name = source.name or price_source.title or f"Telegram channel {price_source.telegram_channel_id}"
    price_source.source_id = source.id
    await session.commit()
    await session.refresh(price_source)
    return price_source


async def telegram_prices_status(session: AsyncSession) -> dict[str, Any]:
    state = await get_bot_state(session)
    return {
        "enabled": get_settings().telegram_prices_bot_enabled,
        "last_update_id": state.last_update_id,
        "last_success_poll_at": state.last_success_poll_at,
        "last_api_error": state.last_api_error,
        "last_successful_price_ingestion_at": state.last_successful_price_ingestion_at,
        "pending_ingestion_count": await session.scalar(select(func.count()).select_from(TelegramPriceBatch).where(TelegramPriceBatch.status == BATCH_STATUS_PENDING_MAPPING)),
        "failed_ingestion_count": await session.scalar(select(func.count()).select_from(TelegramPriceBatch).where(TelegramPriceBatch.status == BATCH_STATUS_FAILED)),
        "unknown_source_count": await session.scalar(select(func.count()).select_from(TelegramPriceSource).where(TelegramPriceSource.source_id.is_(None))),
    }


async def get_bot_state(session: AsyncSession) -> TelegramPriceBotState:
    state = await session.scalar(select(TelegramPriceBotState).where(TelegramPriceBotState.bot_key == "prices"))
    if state is None:
        state = TelegramPriceBotState(bot_key="prices")
        session.add(state)
        await session.commit()
        await session.refresh(state)
    return state


def sanitized_update_payload(update: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(update)
    message = message_from_update(sanitized)
    if message is None:
        return sanitized
    sender = message.get("from")
    if isinstance(sender, dict):
        message["from"] = {"id": sender.get("id"), "is_bot": sender.get("is_bot")}
    chat = message.get("chat")
    if isinstance(chat, dict):
        message["chat"] = {"id": chat.get("id"), "type": chat.get("type")}
    return sanitized


def sanitize_telegram_error(exc: BaseException, token: str | None = None) -> str:
    return redact_telegram_token(sanitize_error(exc), token)
