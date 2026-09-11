from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.jobs.queue import QUEUE_NAME


def main() -> None:
    redis = Redis.from_url(get_settings().redis_url)
    queue = Queue(QUEUE_NAME, connection=redis)
    Worker([queue], connection=redis).work()


if __name__ == "__main__":
    main()
