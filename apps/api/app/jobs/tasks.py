import asyncio
import uuid

from redis import Redis

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.jobs.locks import SourceLock
from app.jobs.service import execute_job


async def _execute_source_collection_job(job_id: str) -> None:
    redis = Redis.from_url(get_settings().redis_url)
    async with AsyncSessionLocal() as session:
        await execute_job(session, uuid.UUID(job_id), lock_factory=lambda source_id: SourceLock(redis, source_id))


def execute_source_collection_job(job_id: str) -> None:
    asyncio.run(_execute_source_collection_job(job_id))
