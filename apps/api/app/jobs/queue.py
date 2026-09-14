from typing import Protocol

from redis import Redis
from rq import Queue

from app.core.config import get_settings

QUEUE_NAME = "source-collection"
PUBLICATION_QUEUE_NAME = "publication"


class QueueAdapter(Protocol):
    def enqueue_job(self, job_id: str) -> None: ...


class RQQueueAdapter:
    def __init__(self, queue_name: str = QUEUE_NAME, target: str = "app.jobs.tasks.execute_source_collection_job"):
        settings = get_settings()
        self.redis = Redis.from_url(settings.redis_url)
        self.queue = Queue(queue_name, connection=self.redis)
        self.target = target

    def enqueue_job(self, job_id: str) -> None:
        self.queue.enqueue(self.target, job_id, job_id=f"avito-jobs-{job_id}")


class RQPublicationQueueAdapter(RQQueueAdapter):
    def __init__(self):
        super().__init__(PUBLICATION_QUEUE_NAME, "app.jobs.tasks.execute_publication_job")


class InMemoryQueueAdapter:
    def __init__(self):
        self.job_ids: list[str] = []

    def enqueue_job(self, job_id: str) -> None:
        self.job_ids.append(job_id)
