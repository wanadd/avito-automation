from __future__ import annotations

import argparse
from pathlib import Path

from app.integrations.avito_contract.registry import DEFAULT_ROOT, harvest, normalize, report, validate


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.integrations.avito_contract.cli")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    harvest_parser = sub.add_parser("harvest")
    harvest_parser.add_argument("--refresh", action="store_true")
    harvest_parser.add_argument("--offline", action="store_true")
    sub.add_parser("normalize")
    sub.add_parser("report")
    sub.add_parser("validate")
    args = parser.parse_args()
    root = Path(args.root)
    if args.command == "harvest":
        snapshot = harvest(root=root, refresh=args.refresh, offline=args.offline)
        print(f"OPENAPI SOURCE: {snapshot.markers['AVITO OPENAPI DISCOVERY']}")
        print(f"AUTOLOAD OPERATIONS: {len(snapshot.api_surface)}")
        print(f"TEMPLATE SOURCE: {snapshot.markers['AUTOLOAD PAYLOAD CONTRACT']}")
        print(f"AVITO LISTING CONTRACT GATE: {snapshot.markers['AVITO LISTING CONTRACT GATE']}")
    elif args.command == "normalize":
        snapshot = normalize(root=root)
        print(f"NORMALIZED: {len(snapshot.field_definitions)} fields")
    elif args.command == "report":
        snapshot = report(root=root)
        print(f"REPORT: {root / 'reports' / 'avito_listing_contract_v1.md'}")
        print(f"AVITO LISTING CONTRACT GATE: {snapshot.markers['AVITO LISTING CONTRACT GATE']}")
    elif args.command == "validate":
        markers = validate(root=root)
        for name, status in markers.items():
            print(f"{name}: {status}")


if __name__ == "__main__":
    main()
