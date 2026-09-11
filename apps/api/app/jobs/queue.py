from typing import Protocol

from redis import Redis
from rq import Queue

from app.core.config import get_settings

QUEUE_NAME = "source-collection"


class QueueAdapter(Protocol):
    def enqueue_job(self, job_id: str) -> None: ...


class RQQueueAdapter:
    def __init__(self, queue_name: str = QUEUE_NAME):
        settings = get_settings()
        self.redis = Redis.from_url(settings.redis_url)
        self.queue = Queue(queue_name, connection=self.redis)

    def enqueue_job(self, job_id: str) -> None:
        self.queue.enqueue("app.jobs.tasks.execute_source_collection_job", job_id, job_id=f"avito:jobs:{job_id}")


class InMemoryQueueAdapter:
    def __init__(self):
        self.job_ids: list[str] = []

    def enqueue_job(self, job_id: str) -> None:
        self.job_ids.append(job_id)
