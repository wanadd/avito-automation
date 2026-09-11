import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_source_record import RawSourceRecord
from app.schemas.raw_source_record import RawSourceRecordCreate


def content_hash(raw_text: str, raw_payload: dict | None) -> str:
    payload = json.dumps(raw_payload, sort_keys=True, separators=(",", ":")) if raw_payload is not None else ""
    return hashlib.sha256(f"{raw_text}\n{payload}".encode("utf-8")).hexdigest()


async def create_raw_record(session: AsyncSession, payload: RawSourceRecordCreate) -> RawSourceRecord:
    if payload.external_record_id is not None:
        existing = await session.scalar(
            select(RawSourceRecord).where(
                RawSourceRecord.source_id == payload.source_id,
                RawSourceRecord.external_record_id == payload.external_record_id,
            )
        )
        if existing is not None:
            return existing

    record = RawSourceRecord(
        **payload.model_dump(),
        content_hash=content_hash(payload.raw_text, payload.raw_payload),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record

