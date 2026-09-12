from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.integrations.avito_contract.assets import INTERESTING_URL_RE
from app.integrations.avito_contract.provenance import sha256_bytes, utc_now_iso
from app.integrations.avito_contract.types import ContractSourceType, RuntimeAccess

SENSITIVE_HEADER_RE = re.compile(r"(cookie|authorization|csrf|token|secret|session)", re.I)


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if not SENSITIVE_HEADER_RE.search(key)}


def discover_frontend_endpoints(raw_paths: list[Path], discovered_from: str) -> list[dict[str, Any]]:
    endpoints: dict[str, dict[str, Any]] = {}
    for path in raw_paths:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8", errors="ignore")
        for match in INTERESTING_URL_RE.finditer(raw):
            url = match.group("url")
            if not url.startswith(("http://", "https://", "/")):
                continue
            endpoints[url] = {
                "method": "GET",
                "url": url,
                "status": None,
                "content_type": None,
                "response_sha256": None,
                "discovered_from": discovered_from,
                "auth_required": None,
                "source_type": ContractSourceType.PUBLIC_FRONTEND_CONTRACT.value,
                "downloaded_at": None,
                "headers": {},
            }
    return [endpoints[key] for key in sorted(endpoints)[:500]]


def response_manifest(
    *,
    method: str,
    url: str,
    status: int,
    content_type: str | None,
    content: bytes,
    discovered_from: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    return {
        "method": method,
        "url": url,
        "status": status,
        "content_type": content_type,
        "response_sha256": sha256_bytes(content),
        "discovered_from": discovered_from,
        "auth_required": status in {401, 403},
        "source_type": ContractSourceType.PUBLIC_FRONTEND_CONTRACT.value,
        "downloaded_at": utc_now_iso(),
        "headers": sanitize_headers(headers),
    }
