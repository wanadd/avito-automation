import argparse
import asyncio

from app.db.session import AsyncSessionLocal
from app.integrations.one_c.importer import import_one_c_path
from app.models.enums import OneCImportMode


async def run_import(args) -> None:
    async with AsyncSessionLocal() as session:
        run = await import_one_c_path(session, args.path, mode=OneCImportMode(args.mode), dry_run=args.dry_run)
        print(f"{run.status} {run.id} total={run.total_rows} valid={run.valid_rows}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.integrations.one_c.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    import_parser = sub.add_parser("import-file")
    import_parser.add_argument("path")
    import_parser.add_argument("--mode", choices=[mode.value for mode in OneCImportMode], default=OneCImportMode.PARTIAL.value)
    import_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "import-file":
        asyncio.run(run_import(args))


if __name__ == "__main__":
    main()
