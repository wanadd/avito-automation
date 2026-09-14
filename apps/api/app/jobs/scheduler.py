import asyncio
import signal

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.jobs.queue import RQQueueAdapter
from app.jobs.service import enqueue_due_retries, recover_stale_running_jobs, scheduler_tick
from app.services.publication import auto_prepare_ready_listings


async def run_forever() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        loop.add_signal_handler(getattr(signal, signame), stop.set)

    queue = RQQueueAdapter()
    while not stop.is_set():
        async with AsyncSessionLocal() as session:
            await recover_stale_running_jobs(session, queue)
            await enqueue_due_retries(session, queue)
            await scheduler_tick(session, queue)
            await auto_prepare_ready_listings(session)
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.scheduler_tick_seconds)
        except TimeoutError:
            pass


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
