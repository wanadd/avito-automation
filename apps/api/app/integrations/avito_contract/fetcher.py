from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

from app.integrations.avito_contract.assets import asset_raw_path, discover_public_links
from app.integrations.avito_contract.provenance import sha256_bytes, utc_now_iso
from app.integrations.avito_contract.types import (
    ContractSourceType,
    RuntimeAccess,
    SourceCandidate,
    SourceManifestEntry,
)

USER_AGENT = "avito-automation-contract-harvester/0.1 (+public-docs-only)"
TIMEOUT_SECONDS = 15


DEFAULT_SOURCES: tuple[SourceCandidate, ...] = (
    SourceCandidate(
        url="https://developers.avito.ru/api-catalog",
        raw_path="raw/official/api_catalog.html",
        source_type=ContractSourceType.OFFICIAL_DOCS,
        expected_kind="html",
    ),
    SourceCandidate(
        url="https://www.avito.ru/autoload/documentation",
        raw_path="raw/autoload_docs/documentation.html",
        source_type=ContractSourceType.OFFICIAL_DOCS,
        expected_kind="html",
    ),
    SourceCandidate(
        url="https://www.avito.ru/autoload/documentation/templates",
        raw_path="raw/templates/templates.html",
        source_type=ContractSourceType.OFFICIAL_TEMPLATE,
        expected_kind="html",
    ),
    SourceCandidate(
        url="https://apis.io/",
        raw_path="raw/references/apis_io.html",
        source_type=ContractSourceType.PUBLIC_API_MIRROR,
        expected_kind="html",
    ),
    SourceCandidate(
        url="https://raw.githubusercontent.com/covox/avito_api/master/docs/Api/AutoloadApi.md",
        raw_path="raw/references/covox_autoload_api.md",
        source_type=ContractSourceType.PUBLIC_API_MIRROR,
        expected_kind="markdown",
    ),
)

OPENAPI_CANDIDATES: tuple[SourceCandidate, ...] = (
    SourceCandidate(
        url="https://developers.avito.ru/openapi.json",
        raw_path="raw/openapi.json",
        source_type=ContractSourceType.OFFICIAL_OPENAPI,
        expected_kind="openapi",
    ),
    SourceCandidate(
        url="https://developers.avito.ru/api/openapi.json",
        raw_path="raw/openapi.json",
        source_type=ContractSourceType.OFFICIAL_OPENAPI,
        expected_kind="openapi",
    ),
    SourceCandidate(
        url="https://api.avito.ru/openapi.json",
        raw_path="raw/openapi.json",
        source_type=ContractSourceType.OFFICIAL_OPENAPI,
        expected_kind="openapi",
    ),
    SourceCandidate(
        url="https://api.avito.ru/swagger.json",
        raw_path="raw/openapi.json",
        source_type=ContractSourceType.OFFICIAL_OPENAPI,
        expected_kind="openapi",
    ),
)


def fetch_url(candidate: SourceCandidate, root: Path) -> SourceManifestEntry:
    request = urllib.request.Request(candidate.url, headers={"User-Agent": USER_AGENT})
    destination = root / candidate.raw_path
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            content = response.read()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            return SourceManifestEntry(
                url=candidate.url,
                path=candidate.raw_path,
                downloaded_at=utc_now_iso(),
                sha256=sha256_bytes(content),
                content_type=response.headers.get("Content-Type"),
                source_type=candidate.source_type,
                status=response.status,
                runtime_access=RuntimeAccess.PUBLIC,
            )
    except urllib.error.HTTPError as exc:
        if destination.exists():
            content = destination.read_bytes()
            return SourceManifestEntry(
                url=candidate.url,
                path=candidate.raw_path,
                downloaded_at=None,
                sha256=sha256_bytes(content),
                content_type=exc.headers.get("Content-Type") if exc.headers else None,
                source_type=candidate.source_type,
                status=200,
                runtime_access=RuntimeAccess.PUBLIC,
                error=f"refresh_failed_using_cache: {exc}",
            )
        access = RuntimeAccess.AUTH_REQUIRED if exc.code in {401, 403} else RuntimeAccess.UNKNOWN
        return SourceManifestEntry(
            url=candidate.url,
            path=candidate.raw_path,
            downloaded_at=utc_now_iso(),
            sha256=None,
            content_type=exc.headers.get("Content-Type") if exc.headers else None,
            source_type=candidate.source_type,
            status=exc.code,
            runtime_access=access,
            error=str(exc),
        )
    except (OSError, urllib.error.URLError) as exc:
        if destination.exists():
            content = destination.read_bytes()
            return SourceManifestEntry(
                url=candidate.url,
                path=candidate.raw_path,
                downloaded_at=None,
                sha256=sha256_bytes(content),
                content_type=None,
                source_type=candidate.source_type,
                status=200,
                runtime_access=RuntimeAccess.PUBLIC,
                error=f"refresh_failed_using_cache: {exc}",
            )
        return SourceManifestEntry(
            url=candidate.url,
            path=candidate.raw_path,
            downloaded_at=utc_now_iso(),
            sha256=None,
            content_type=None,
            source_type=candidate.source_type,
            status=None,
            runtime_access=RuntimeAccess.UNKNOWN,
            error=str(exc),
        )


def harvest_public_sources(root: Path, refresh: bool = False) -> list[SourceManifestEntry]:
    sources: list[SourceManifestEntry] = []
    seen_openapi = False
    for candidate in (*OPENAPI_CANDIDATES, *DEFAULT_SOURCES):
        destination = root / candidate.raw_path
        if destination.exists() and not refresh:
            content = destination.read_bytes()
            sources.append(
                SourceManifestEntry(
                    url=candidate.url,
                    path=candidate.raw_path,
                    downloaded_at=None,
                    sha256=sha256_bytes(content),
                    content_type=None,
                    source_type=candidate.source_type,
                    status=200,
                    runtime_access=RuntimeAccess.PUBLIC,
                )
            )
            if candidate.expected_kind == "openapi":
                seen_openapi = True
            continue

        entry = fetch_url(candidate, root)
        sources.append(entry)
        if candidate.expected_kind == "openapi" and entry.status == 200:
            seen_openapi = True
        if seen_openapi and candidate.expected_kind == "openapi":
            continue
    return sources


def harvest_recovery_sources(
    root: Path, existing_sources: list[SourceManifestEntry], refresh: bool = False, limit: int = 30
) -> list[SourceManifestEntry]:
    raw_paths = [
        root / entry.path
        for entry in existing_sources
        if entry.status == 200
        and entry.source_type in {ContractSourceType.OFFICIAL_DOCS, ContractSourceType.OFFICIAL_TEMPLATE, ContractSourceType.PUBLIC_FRONTEND_CONTRACT}
    ]
    links = discover_public_links(raw_paths, "https://www.avito.ru/")
    known_urls = {entry.url for entry in existing_sources}
    recovered: list[SourceManifestEntry] = []
    for index, url in enumerate(url for url in links if url not in known_urls):
        if index >= limit:
            break
        source_type = ContractSourceType.OFFICIAL_TEMPLATE if "/autoload/documentation/templates/" in url else ContractSourceType.PUBLIC_FRONTEND_CONTRACT
        candidate = SourceCandidate(
            url=url,
            raw_path=asset_raw_path(url, index),
            source_type=source_type,
            expected_kind="recovery",
        )
        destination = root / candidate.raw_path
        if destination.exists() and not refresh:
            content = destination.read_bytes()
            recovered.append(
                SourceManifestEntry(
                    url=url,
                    path=candidate.raw_path,
                    downloaded_at=None,
                    sha256=sha256_bytes(content),
                    content_type=None,
                    source_type=source_type,
                    status=200,
                    runtime_access=RuntimeAccess.PUBLIC,
                )
            )
            continue
        recovered.append(fetch_url(candidate, root))
    return recovered
