from __future__ import annotations

from pathlib import Path

from app.integrations.avito_contract.exporter import write_normalized, write_reports
from app.integrations.avito_contract.fetcher import harvest_public_sources, harvest_recovery_sources
from app.integrations.avito_contract.normalizer import normalize_contract
from app.integrations.avito_contract.provenance import load_manifest, save_manifest
from app.integrations.avito_contract.types import AvitoContractSnapshot, RuntimeAccess

DEFAULT_ROOT = Path("data/avito_contract")


def ensure_layout(root: Path = DEFAULT_ROOT) -> None:
    for path in (
        root / "raw" / "autoload_docs",
        root / "raw" / "templates",
        root / "raw" / "references",
        root / "normalized",
        root / "reports",
    ):
        path.mkdir(parents=True, exist_ok=True)


def harvest(root: Path = DEFAULT_ROOT, refresh: bool = False, offline: bool = False) -> AvitoContractSnapshot:
    ensure_layout(root)
    manifest_path = root / "manifest.json"
    if offline:
        sources = load_manifest(manifest_path)
    else:
        sources = harvest_public_sources(root, refresh=refresh)
        sources = [*sources, *harvest_recovery_sources(root, sources, refresh=refresh)]
    save_manifest(manifest_path, sources)
    snapshot = normalize_contract(root, sources)
    write_normalized(root, snapshot)
    write_reports(root, snapshot)
    return snapshot


def normalize(root: Path = DEFAULT_ROOT) -> AvitoContractSnapshot:
    ensure_layout(root)
    sources = load_manifest(root / "manifest.json")
    snapshot = normalize_contract(root, sources)
    write_normalized(root, snapshot)
    return snapshot


def report(root: Path = DEFAULT_ROOT) -> AvitoContractSnapshot:
    snapshot = normalize(root)
    write_reports(root, snapshot)
    return snapshot


def validate(root: Path = DEFAULT_ROOT) -> dict[str, str]:
    snapshot = normalize(root)
    result = dict(snapshot.markers)
    live_tree = next((item for item in snapshot.auth_matrix if "user-docs/tree" in item["operation"]), None)
    if live_tree and live_tree["runtime_auth_required"]:
        result["CATEGORY TREE LIVE"] = RuntimeAccess.AUTH_REQUIRED.value
    return result
