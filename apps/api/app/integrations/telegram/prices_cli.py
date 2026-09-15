import argparse
import asyncio
import logging

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.integrations.telegram.bot_api import build_telegram_prices_bot_client
from app.integrations.telegram.types import TelegramCollectorError, TelegramRateLimitError
from app.services.telegram_prices import poll_telegram_prices_bot, sanitize_telegram_error

logger = logging.getLogger("app.telegram_prices_cli")


async def run_once() -> dict:
    async with AsyncSessionLocal() as session:
        return await poll_telegram_prices_bot(session, build_telegram_prices_bot_client())


async def run_loop() -> None:
    settings = get_settings()
    backoff = settings.telegram_prices_retry_base_seconds
    client = build_telegram_prices_bot_client()
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await poll_telegram_prices_bot(session, client)
            backoff = settings.telegram_prices_retry_base_seconds
        except TelegramRateLimitError as exc:
            logger.warning("telegram_prices_rate_limited", extra={"retry_after": exc.wait_seconds})
            await asyncio.sleep(max(exc.wait_seconds, backoff))
        except TelegramCollectorError as exc:
            logger.warning("telegram_prices_poll_failed", extra={"error": sanitize_telegram_error(exc, client.token)})
            await asyncio.sleep(backoff)


def main() -> None:
    logging.basicConfig(level=get_settings().log_level)
    parser = argparse.ArgumentParser(prog="python -m app.integrations.telegram.prices_cli")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        print(asyncio.run(run_once()))
    else:
        asyncio.run(run_loop())


if __name__ == "__main__":
    main()
