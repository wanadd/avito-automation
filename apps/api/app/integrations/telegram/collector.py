import hashlib
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.telegram.types import (
    TelegramAccessError,
    TelegramAuthError,
    TelegramChatInfo,
    TelegramClientAdapter,
    TelegramCollectorError,
    TelegramMessage,
    TelegramNetworkError,
    TelegramRateLimitError,
)
from app.models.enums import (
    ProcessingStatus,
    SourceType,
    TelegramCollectionMode,
    TelegramCollectionRunStatus,
)
from app.models.raw_source_record import RawSourceRecord, RawSourceRecordRevision
from app.models.source import Source
from app.models.telegram_collection import TelegramCollectionRun
from app.schemas.raw_source_record import RawSourceRecordCreate
from app.schemas.supplier_snapshot import SupplierSnapshotCreate
from app.services.raw_records import create_raw_record
from app.services.supplier_snapshots import create_snapshot, process_snapshot

logger = logging.getLogger("app.telegram_collector")


def telegram_content_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def sanitize_error(exc: BaseException) -> str:
    message = str(exc).replace("\n", " ").strip()
    for key in ("api_hash", "session", "otp", "password", "phone"):
        message = message.replace(key, "[redacted]")
    return message[:512] or exc.__class__.__name__


def message_text(message: TelegramMessage) -> str | None:
    text = message.text if message.text is not None else message.caption
    if text is None:
        return None
    return text if text.strip() else None


def message_metadata(message: TelegramMessage, chat_id: int, collected_at: datetime) -> dict:
    return {
        "provider": "telegram",
        "telegram_message_id": message.message_id,
        "telegram_chat_id": chat_id,
        "message_date": message.date.isoformat(),
        "edit_date": message.edit_date.isoformat() if message.edit_date else None,
        "sender_id": message.sender_id,
        "reply_to": message.reply_to_message_id,
        "forward": message.forward,
        "has_media": message.has_media,
        "media_type": message.media_type,
        "collected_at": collected_at.isoformat(),
    }


async def check_telegram_source(session: AsyncSession, source_id: uuid.UUID, adapter: TelegramClientAdapter) -> dict:
    source = await _get_source(session, source_id)
    try:
        await adapter.connect()
        chat = await adapter.get_chat(external_chat_id=source.external_chat_id, username=source.username)
        source.external_chat_id = chat.external_chat_id
        source.username = chat.username
        source.title = chat.title
        await session.commit()
        return {
            "reachable": True,
            "external_chat_id": chat.external_chat_id,
            "title": chat.title,
            "username": chat.username,
            "latest_message_id": chat.latest_message_id,
        }
    except TelegramCollectorError as exc:
        return {"reachable": False, "error": sanitize_error(exc)}
    finally:
        await adapter.disconnect()


async def collect_source(
    session: AsyncSession,
    source_id: uuid.UUID,
    *,
    mode: TelegramCollectionMode,
    limit: int | None,
    adapter: TelegramClientAdapter,
) -> dict:
    source = await _get_source(session, source_id)
    run = TelegramCollectionRun(source_id=source.id, mode=mode)
    session.add(run)
    await session.commit()
    await session.refresh(run)
    run_id = run.id
    safe_limit = limit or get_settings().telegram_backfill_limit

    last_message_id = source.last_collected_message_id
    try:
        await adapter.connect()
        chat = await adapter.get_chat(external_chat_id=source.external_chat_id, username=source.username)
        _update_source_chat_cache(source, chat)
        messages = (
            await adapter.fetch_messages(chat.external_chat_id, limit=safe_limit)
            if mode == TelegramCollectionMode.BACKFILL
            else await adapter.fetch_messages_after(
                chat.external_chat_id, after_message_id=source.last_collected_message_id, limit=safe_limit
            )
        )
        messages = sorted(messages, key=lambda item: (item.date, item.message_id))
        if messages:
            run.start_message_id = messages[0].message_id
            run.end_message_id = messages[-1].message_id

        for message in messages:
            run.fetched_count += 1
            last_message_id = max(last_message_id or message.message_id, message.message_id)
            content = message_text(message)
            if message.service or content is None:
                run.ignored_count += 1
                source.last_collected_message_id = max(source.last_collected_message_id or message.message_id, message.message_id)
                continue

            collected_at = datetime.now(UTC)
            metadata = message_metadata(message, chat.external_chat_id, collected_at)
            try:
                raw_record, revision, kind = await persist_message_revision(session, source, message, content, metadata)
                if kind == "duplicate":
                    run.duplicate_count += 1
                    source.last_collected_message_id = max(source.last_collected_message_id or message.message_id, message.message_id)
                    continue
                if kind == "edited":
                    run.edited_count += 1
                else:
                    run.new_count += 1
            except Exception as exc:
                await session.rollback()
                run = await session.get(TelegramCollectionRun, run_id)
                source = await session.get(Source, source_id)
                run.failed_count += 1
                run.error = sanitize_error(exc)
                continue

            source.last_collected_message_id = max(source.last_collected_message_id or message.message_id, message.message_id)
            snapshot = await create_snapshot(
                session,
                SupplierSnapshotCreate(
                    supplier_id=source.supplier_id,
                    source_id=source.id,
                    raw_source_record_id=raw_record.id,
                    raw_source_record_revision_id=revision.id,
                    external_snapshot_id=f"telegram:{chat.external_chat_id}:{message.message_id}:r{revision.revision_no}",
                    snapshot_type=source.snapshot_type,
                    captured_at=message.edit_date or message.date,
                ),
            )
            run.snapshots_created += 1
            try:
                await process_snapshot(session, snapshot.id)
                run.snapshots_processed += 1
            except Exception as exc:
                await session.rollback()
                run = await session.get(TelegramCollectionRun, run_id)
                source = await session.get(Source, source_id)
                run.failed_count += 1
                run.error = sanitize_error(exc)

        run.status = TelegramCollectionRunStatus.PARTIAL if run.failed_count else TelegramCollectionRunStatus.COMPLETED
    except TelegramRateLimitError as exc:
        run.status = TelegramCollectionRunStatus.PARTIAL if run.new_count or run.duplicate_count or run.edited_count else TelegramCollectionRunStatus.FAILED
        run.error = sanitize_error(exc)
    except (TelegramAuthError, TelegramAccessError, TelegramNetworkError) as exc:
        run.status = TelegramCollectionRunStatus.FAILED
        run.error = sanitize_error(exc)
    finally:
        await adapter.disconnect()

    run.finished_at = datetime.now(UTC)
    source.last_collection_at = run.finished_at
    source.last_collection_status = run.status
    source.last_collection_error = run.error
    await session.commit()
    return collection_result(run, last_message_id)


async def persist_message_revision(
    session: AsyncSession, source: Source, message: TelegramMessage, content: str, metadata: dict
) -> tuple[RawSourceRecord, RawSourceRecordRevision, str]:
    message_hash = telegram_content_hash(content)
    existing = await session.scalar(
        select(RawSourceRecord).where(
            RawSourceRecord.source_id == source.id,
            RawSourceRecord.external_record_id == str(message.message_id),
        )
    )
    if existing is None:
        raw_record = await create_raw_record(
            session,
            RawSourceRecordCreate(
                source_id=source.id,
                external_record_id=str(message.message_id),
                raw_text=content,
                raw_payload=metadata,
                source_published_at=message.date,
                processing_status=ProcessingStatus.NEW,
            ),
        )
        revision = RawSourceRecordRevision(
            raw_source_record_id=raw_record.id,
            revision_no=1,
            content_hash=message_hash,
            raw_content=content,
            external_updated_at=message.edit_date,
            raw_payload=metadata,
        )
        session.add(revision)
        await session.commit()
        await session.refresh(revision)
        return raw_record, revision, "new"

    revision = await session.scalar(
        select(RawSourceRecordRevision)
        .where(RawSourceRecordRevision.raw_source_record_id == existing.id)
        .order_by(RawSourceRecordRevision.revision_no.desc())
        .limit(1)
    )
    if revision and revision.content_hash == message_hash:
        return existing, revision, "duplicate"

    next_revision = (await session.scalar(
        select(func.max(RawSourceRecordRevision.revision_no)).where(
            RawSourceRecordRevision.raw_source_record_id == existing.id
        )
    ) or 0) + 1
    new_revision = RawSourceRecordRevision(
        raw_source_record_id=existing.id,
        revision_no=next_revision,
        content_hash=message_hash,
        raw_content=content,
        external_updated_at=message.edit_date,
        raw_payload=metadata,
    )
    session.add(new_revision)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        duplicate = await session.scalar(
            select(RawSourceRecordRevision).where(
                RawSourceRecordRevision.raw_source_record_id == existing.id,
                RawSourceRecordRevision.content_hash == message_hash,
            )
        )
        if duplicate is None:
            raise
        return existing, duplicate, "duplicate"
    await session.refresh(new_revision)
    return existing, new_revision, "edited"


async def _get_source(session: AsyncSession, source_id: uuid.UUID) -> Source:
    source = await session.get(Source, source_id)
    if source is None:
        raise ValueError("Source not found")
    if source.source_type != SourceType.TELEGRAM:
        raise ValueError("Source is not Telegram")
    if source.external_chat_id is None and not source.username:
        raise ValueError("Telegram source requires external_chat_id or username")
    return source


def _update_source_chat_cache(source: Source, chat: TelegramChatInfo) -> None:
    source.external_chat_id = chat.external_chat_id
    source.username = chat.username
    source.title = chat.title


def collection_result(run: TelegramCollectionRun, last_message_id: int | None) -> dict:
    return {
        "run_id": run.id,
        "source_id": run.source_id,
        "status": run.status,
        "mode": run.mode,
        "fetched": run.fetched_count,
        "new_records": run.new_count,
        "duplicate_records": run.duplicate_count,
        "edited_records": run.edited_count,
        "ignored_records": run.ignored_count,
        "snapshots_created": run.snapshots_created,
        "snapshots_processed": run.snapshots_processed,
        "failed_records": run.failed_count,
        "last_message_id": last_message_id,
        "error": run.error,
    }
