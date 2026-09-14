from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.jobs.queue import PUBLICATION_QUEUE_NAME, QUEUE_NAME


def main() -> None:
    redis = Redis.from_url(get_settings().redis_url)
    source_queue = Queue(QUEUE_NAME, connection=redis)
    publication_queue = Queue(PUBLICATION_QUEUE_NAME, connection=redis)
    Worker([source_queue, publication_queue], connection=redis).work()


if __name__ == "__main__":
    main()
