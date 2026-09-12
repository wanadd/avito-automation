from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.integrations.avito_contract.types import SourceManifestEntry, to_jsonable


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest(path: Path) -> list[SourceManifestEntry]:
    if not path.exists():
        return []
    entries = read_json(path)
    return [SourceManifestEntry(**entry) for entry in entries]


def save_manifest(path: Path, entries: list[SourceManifestEntry]) -> None:
    write_json(path, entries)
