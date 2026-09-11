import argparse
import asyncio
import json
import uuid

from app.db.session import AsyncSessionLocal
from app.integrations.telegram.client import build_telegram_adapter
from app.integrations.telegram.collector import collect_source
from app.models.enums import TelegramCollectionMode


async def collect(args) -> None:
    async with AsyncSessionLocal() as session:
        result = await collect_source(
            session,
            uuid.UUID(args.source_id),
            mode=TelegramCollectionMode(args.mode),
            limit=args.limit,
            adapter=build_telegram_adapter(),
        )
    print(json.dumps(result, default=str, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.integrations.telegram.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--source-id", required=True)
    collect_parser.add_argument("--mode", choices=[mode.value for mode in TelegramCollectionMode], default="INCREMENTAL")
    collect_parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "collect":
        asyncio.run(collect(args))


if __name__ == "__main__":
    main()
