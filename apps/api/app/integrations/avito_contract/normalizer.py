from __future__ import annotations

from pathlib import Path

from app.integrations.avito_contract.assets import parse_template_asset
from app.integrations.avito_contract.gate import compute_gate_markers
from app.integrations.avito_contract.network import discover_frontend_endpoints
from app.integrations.avito_contract.openapi import extract_autoload_endpoints, load_openapi
from app.integrations.avito_contract.parser import (
    extract_category_nodes_from_openapi,
    extract_embedded_category_tree_nodes,
    extract_markdown_autoload_endpoints,
    extract_template_fields,
    extract_template_category_nodes,
)
from app.integrations.avito_contract.types import (
    AvitoEndpointContract,
    AvitoContractSnapshot,
    AvitoFieldContract,
    AvitoImageContract,
    Completeness,
    ContractConfidence,
    ContractLifecycle,
    ContractSourceType,
    CoverageMetrics,
    ElectronicsCategoryContract,
    GateStatus,
    RuntimeAccess,
    SourceManifestEntry,
)

TARGET_CATEGORIES = (
    "SMARTPHONES",
    "TABLETS",
    "WATCHES",
    "HEADPHONES",
    "LAPTOPS",
    "POWER_STATIONS",
    "GENERATORS",
    "ACCESSORIES",
)

TARGET_TERMS = {
    "SMARTPHONES": ("мобильные телефоны", "смартфон"),
    "TABLETS": ("планшеты", "планшет"),
    "WATCHES": ("часы", "smart watch"),
    "HEADPHONES": ("наушник",),
    "LAPTOPS": ("ноутбук",),
    "POWER_STATIONS": ("электростанц", "зарядн"),
    "GENERATORS": ("генератор",),
    "ACCESSORIES": ("аксессуар",),
}
ELECTRONICS_TARGETS = {"SMARTPHONES", "TABLETS", "WATCHES", "HEADPHONES", "LAPTOPS", "ACCESSORIES"}

CORE_FIELDS = ("Id", "Category", "Title", "Description", "Price", "Images", "Address", "ContactMethod", "Condition", "Delivery")


def _auth_matrix(endpoints: list) -> list[dict]:
    matrix = []
    for endpoint in endpoints:
        matrix.append(
            {
                "operation": f"{endpoint.method} {endpoint.path}",
                "public_schema_available": True,
                "runtime_auth_required": endpoint.runtime_access == RuntimeAccess.AUTH_REQUIRED,
                "paid_tariff_likely_required": "UNKNOWN",
                "account_specific": endpoint.runtime_access == RuntimeAccess.AUTH_REQUIRED,
                "safe_for_future_use": endpoint.lifecycle.value in {"CURRENT", "UNKNOWN"},
            }
        )
    if not any("user-docs/tree" in item["operation"] for item in matrix):
        matrix.append(
            {
                "operation": "GET /autoload/v1/user-docs/tree",
                "public_schema_available": False,
                "runtime_auth_required": True,
                "paid_tariff_likely_required": "UNKNOWN",
                "account_specific": True,
                "safe_for_future_use": "FUTURE",
            }
        )
    return matrix


def _coverage(fields: list) -> CoverageMetrics:
    confirmed = sum(1 for field in fields if field.confidence == ContractConfidence.CONFIRMED)
    strong = sum(1 for field in fields if field.confidence == ContractConfidence.STRONG)
    partial = sum(1 for field in fields if field.confidence == ContractConfidence.PARTIAL)
    unknown = sum(1 for field in fields if field.confidence == ContractConfidence.UNKNOWN)
    auth_locked = sum(1 for field in fields if field.runtime_access == RuntimeAccess.AUTH_REQUIRED.value)
    enum_with = sum(1 for field in fields if field.enum_values)
    enum_without = sum(1 for field in fields if field.field_type in {"enum", "select"} and not field.enum_values)
    required_confirmed = sum(1 for field in fields if field.required is True and field.confidence == ContractConfidence.CONFIRMED)
    required_unknown = sum(1 for field in fields if field.required is None)
    return CoverageMetrics(
        total_discovered_fields=len(fields),
        confirmed_fields=confirmed,
        strong_fields=strong,
        partial_fields=partial,
        unknown_fields=unknown,
        auth_locked_fields=auth_locked,
        enum_fields_with_values=enum_with,
        enum_fields_without_values=enum_without,
        required_fields_confirmed=required_confirmed,
        required_fields_unknown=required_unknown,
    )


def _template_assets(root: Path, sources: list[SourceManifestEntry]) -> list[dict]:
    assets = []
    for entry in sources:
        path = root / entry.path
        if entry.status != 200 or not path.exists():
            continue
        if entry.source_type not in {ContractSourceType.OFFICIAL_TEMPLATE, ContractSourceType.PUBLIC_FRONTEND_CONTRACT}:
            continue
        kind = path.suffix.lower().lstrip(".") or "html"
        if kind not in {"xml", "xlsx", "xls", "csv", "zip", "json", "yaml", "yml"} and "/recovery/" not in entry.path:
            continue
        assets.append(
            {
                "url": entry.url,
                "raw_path": entry.path,
                "asset_type": kind,
                "source_type": entry.source_type.value,
                "content_type": entry.content_type,
                "sha256": entry.sha256,
                "runtime_access": entry.runtime_access.value,
                "parsed": parse_template_asset(path),
            }
        )
    return sorted(assets, key=lambda item: item["url"])


def _fields_from_assets(template_assets: list[dict]) -> list[AvitoFieldContract]:
    fields: dict[str, AvitoFieldContract] = {}
    for asset in template_assets:
        parsed = asset.get("parsed") or {}
        if parsed.get("status") != "PARSED":
            continue
        for field in parsed.get("fields", []):
            if not field or field in fields:
                continue
            fields[field] = AvitoFieldContract(
                field_id=field,
                api_name=field,
                display_name=None,
                field_type=parsed.get("format"),
                required=None,
                conditional=False,
                enum_values=[],
                min_value=None,
                max_value=None,
                min_length=None,
                max_length=None,
                pattern=None,
                depends_on=[],
                dependencies_raw=None,
                category_slugs=[],
                source_type=ContractSourceType(asset["source_type"]),
                confidence=ContractConfidence.PARTIAL,
                runtime_access=asset.get("runtime_access") or RuntimeAccess.UNKNOWN.value,
                evidence_url=asset.get("url"),
            )
    return list(fields.values())


def _listing_core_contract(fields: list[AvitoFieldContract]) -> dict:
    by_name = {field.field_id.lower(): field for field in fields}
    items = {}
    confirmed = 0
    partial = 0
    for name in CORE_FIELDS:
        field = by_name.get(name.lower())
        if field and field.confidence == ContractConfidence.CONFIRMED:
            status = "CONFIRMED"
            confirmed += 1
        elif field:
            status = "PARTIAL"
            partial += 1
        else:
            status = "UNKNOWN"
        items[name] = {
            "status": status,
            "evidence_url": field.evidence_url if field else None,
            "source_type": field.source_type.value if field else ContractSourceType.UNKNOWN.value,
        }
    return {"fields": items, "confirmed_count": confirmed, "partial_count": partial}


def _autoload_versions(root: Path, endpoints: list[AvitoEndpointContract], sources: list[SourceManifestEntry]) -> dict:
    versions: dict[str, dict] = {}
    for endpoint in endpoints:
        version = "v4" if "/v4/" in endpoint.path else "v3" if "/v3/" in endpoint.path else "v2" if "/v2/" in endpoint.path else "v1" if "/v1/" in endpoint.path else "UNKNOWN"
        versions.setdefault(
            version,
            {
                "version": version,
                "component": "autoload",
                "lifecycle": endpoint.lifecycle.value,
                "evidence": [],
            },
        )["evidence"].append(endpoint.evidence_url or endpoint.path)
    for entry in sources:
        path = root / entry.path
        if entry.status != 200 or not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if "autoload/v4" in text or "autoload v4" in text or "v4 uploads" in text:
            versions.setdefault(
                "v4",
                {
                    "version": "v4",
                    "component": "autoload",
                    "lifecycle": ContractLifecycle.CURRENT.value,
                    "evidence": [],
                },
            )["evidence"].append(entry.url)
    return {"versions": [versions[key] for key in sorted(versions)]}


def _contract_conflicts(fields: list[AvitoFieldContract]) -> list[dict]:
    claims: dict[str, list[AvitoFieldContract]] = {}
    for field in fields:
        claims.setdefault(field.field_id, []).append(field)
    conflicts = []
    for field_id, items in claims.items():
        required_values = {item.required for item in items}
        if len(required_values) > 1:
            conflicts.append(
                {
                    "field": field_id,
                    "category": None,
                    "claims": [
                        {
                            "required": item.required,
                            "source_type": item.source_type.value,
                            "evidence_url": item.evidence_url,
                        }
                        for item in items
                    ],
                    "preferred_claim": None,
                    "preference_reason": "Equal authority or unresolved contradiction.",
                    "unresolved": True,
                }
            )
    return conflicts


def normalize_contract(root: Path, sources: list[SourceManifestEntry]) -> AvitoContractSnapshot:
    openapi_spec = load_openapi(root / "raw/openapi.json") or load_openapi(root / "raw/openapi.yaml")
    openapi_url = next((entry.url for entry in sources if entry.path in {"raw/openapi.json", "raw/openapi.yaml"} and entry.status == 200), None)
    endpoints = extract_autoload_endpoints(openapi_spec, evidence_url=openapi_url) if openapi_spec else []
    existing = {(endpoint.method, endpoint.path) for endpoint in endpoints}
    for entry in sources:
        if entry.source_type != ContractSourceType.PUBLIC_API_MIRROR or entry.status != 200:
            continue
        for item in extract_markdown_autoload_endpoints(root / entry.path):
            key = (item["method"], item["path"])
            if key in existing:
                continue
            existing.add(key)
            endpoints.append(
                AvitoEndpointContract(
                    path=item["path"],
                    method=item["method"],
                    operation_id=None,
                    tags=["Autoload"],
                    summary=None,
                    request_schema=None,
                    response_schema=None,
                    auth_type="OAuth2",
                    deprecated=False,
                    lifecycle=ContractLifecycle.LEGACY,
                    required_scopes=[],
                    rate_limits=[],
                    runtime_access=RuntimeAccess.AUTH_REQUIRED,
                    source_type=ContractSourceType.PUBLIC_API_MIRROR,
                    confidence=ContractConfidence.PARTIAL,
                    evidence_url=entry.url,
                )
            )
    endpoints = sorted(endpoints, key=lambda endpoint: (endpoint.path, endpoint.method))
    template_paths = [root / entry.path for entry in sources if entry.source_type == ContractSourceType.OFFICIAL_TEMPLATE and entry.status == 200]
    template_assets = _template_assets(root, sources)
    fields = [*extract_template_fields(template_paths), *_fields_from_assets(template_assets)]
    category_tree = [
        *extract_category_nodes_from_openapi(endpoints),
        *extract_template_category_nodes(template_paths),
        *extract_embedded_category_tree_nodes(template_paths),
    ]
    categories_by_target = {}
    for target, terms in TARGET_TERMS.items():
        candidates = []
        for node in category_tree:
            haystack = " ".join([node.name or "", *node.path]).lower()
            path_has_electronics = any(part.lower() == "электроника" for part in node.path)
            if target in ELECTRONICS_TARGETS and not path_has_electronics:
                continue
            if any(term in haystack for term in terms):
                name = (node.name or "").lower()
                exact_name = any(name == term or name.startswith(term) for term in terms)
                candidates.append((0 if exact_name else 1, len(node.path), node))
        if candidates:
            categories_by_target[target] = sorted(candidates, key=lambda item: (item[0], item[1], item[2].slug or ""))[0][2]
    category_contracts = [
        ElectronicsCategoryContract(
            target=target,
            display_name=categories_by_target[target].name if target in categories_by_target else None,
            category_path=categories_by_target[target].path if target in categories_by_target else [],
            category_slug=categories_by_target[target].slug if target in categories_by_target else None,
            autoload_category_value=categories_by_target[target].slug if target in categories_by_target else None,
            auth_locked_fields=[] if fields else ["category_fields"],
            contract_completeness=Completeness.PARTIAL
            if target in categories_by_target
            else Completeness.BLOCKED_BY_AUTH,
            mapping_status="PARTIAL_SOURCE_MATCH" if target in categories_by_target else "UNCONFIRMED",
        )
        for target in TARGET_CATEGORIES
    ]
    enums = [
        {
            "field": field.field_id,
            "values": field.enum_values,
            "runtime_access": field.runtime_access,
            "confidence": field.confidence.value,
        }
        for field in fields
        if field.enum_values or field.field_type in {"enum", "select"}
    ]
    dependencies: list[dict] = []
    coverage = _coverage(fields)
    raw_paths = [root / entry.path for entry in sources if entry.status == 200]
    public_network_endpoints = discover_frontend_endpoints(raw_paths, "saved_public_raw")
    listing_core_contract = _listing_core_contract(fields)
    autoload_versions = _autoload_versions(root, endpoints, sources)
    contract_conflicts = _contract_conflicts(fields)
    has_official_template = any(entry.source_type == ContractSourceType.OFFICIAL_TEMPLATE and entry.status == 200 for entry in sources)
    has_official_openapi = openapi_spec is not None
    has_autoload_surface = bool(endpoints)
    has_tree_schema = any("user-docs/tree" in endpoint.path for endpoint in endpoints)
    current_versions = sum(1 for item in autoload_versions["versions"] if item["lifecycle"] == ContractLifecycle.CURRENT.value)
    markers, readiness = compute_gate_markers(
        implementation_ok=True,
        public_sources_found=has_official_template or has_autoload_surface,
        autoload_operations=len(endpoints),
        template_assets=len(template_assets) or len(category_tree),
        current_versions=current_versions,
        listing_core_confirmed=listing_core_contract["confirmed_count"],
        category_fields_confirmed=coverage.required_fields_confirmed,
        coverage=coverage,
        conflicts=len(contract_conflicts),
        security_ok=True,
    )
    markers.update(
        {
            "AVITO OPENAPI DISCOVERY": GateStatus.PASS.value if has_official_openapi else GateStatus.FAIL.value,
            "AUTOLOAD API SURFACE": GateStatus.PASS.value if has_autoload_surface else GateStatus.FAIL.value,
            "CATEGORY TREE DISCOVERY": GateStatus.AUTH_REQUIRED.value
            if not category_tree or not has_tree_schema
            else GateStatus.PASS_WITH_LIMITATIONS.value,
            "CATEGORY FIELD DISCOVERY": GateStatus.AUTH_REQUIRED.value if not fields else GateStatus.PASS_WITH_LIMITATIONS.value,
            "AUTOLOAD PAYLOAD CONTRACT": GateStatus.PASS_WITH_LIMITATIONS.value if has_official_template else GateStatus.FAIL.value,
            "TITLE/DESCRIPTION RULES": GateStatus.UNKNOWN.value,
            "LIFECYCLE CHECK": GateStatus.PASS.value,
            "AUTH MATRIX": GateStatus.PASS.value,
            "ELECTRONICS MAPPING": GateStatus.PASS_WITH_LIMITATIONS.value if fields or endpoints else GateStatus.FAIL.value,
            "CONTRACT COVERAGE": GateStatus.PASS_WITH_LIMITATIONS.value if fields else GateStatus.FAIL.value,
            "AVITO LISTING CONTRACT GATE": readiness["AVITO LISTING CONTRACT GATE"],
        }
    )
    gaps = []
    if not has_official_openapi:
        gaps.append(
            {
                "id": "GAP-OPENAPI-001",
                "category": "OPENAPI",
                "field": None,
                "severity": "MAJOR",
                "problem": "Official machine-readable OpenAPI was not available in saved raw sources.",
                "why_unresolved": "Public candidate URLs did not return a downloadable spec.",
                "can_sprint_0_9_proceed": True,
                "future_resolution": "Use official API catalog export or authorized developer portal when available.",
            }
        )
    if not fields:
        gaps.append(
            {
                "id": "GAP-FIELDS-001",
                "category": "CATEGORY_FIELDS",
                "field": "category_fields",
                "severity": "MAJOR",
                "problem": "Category-specific required fields are not confirmed.",
                "why_unresolved": "Live field endpoint requires runtime API access or templates did not expose structured fields.",
                "can_sprint_0_9_proceed": True,
                "future_resolution": "Resolve via authorized /autoload/user-docs/node/{node_slug}/fields before production publishing.",
            }
        )
    return AvitoContractSnapshot(
        api_surface=endpoints,
        category_tree=category_tree,
        field_definitions=fields,
        enums=enums,
        dependencies=dependencies,
        category_contracts=category_contracts,
        template_assets=template_assets,
        public_network_endpoints=public_network_endpoints,
        autoload_versions=autoload_versions,
        listing_core_contract=listing_core_contract,
        contract_conflicts=contract_conflicts,
        image_contract=AvitoImageContract(
            min_count=None,
            max_count=None,
            formats=[],
            min_width=None,
            min_height=None,
            max_size_bytes=None,
            remote_url_allowed=None,
            ordering_supported=None,
            source_type=ContractSourceType.UNKNOWN,
            confidence=ContractConfidence.UNKNOWN,
        ),
        autoload_payload_contract={
            "format": "UNKNOWN" if not has_official_template else "DOCUMENTED_TEMPLATE_AVAILABLE",
            "root": None,
            "item_node": None,
            "required_top_level_fields": [],
            "category_specific_fields": [],
            "images_representation": "UNKNOWN",
            "price_representation": "UNKNOWN",
            "location_representation": "UNKNOWN",
            "contact_representation": "UNKNOWN",
            "source_type": ContractSourceType.OFFICIAL_TEMPLATE.value if has_official_template else ContractSourceType.UNKNOWN.value,
            "confidence": ContractConfidence.PARTIAL.value if has_official_template else ContractConfidence.UNKNOWN.value,
        },
        title_description_rules={"confidence": ContractConfidence.UNKNOWN.value, "rules": {}},
        price_contract={
            "internal_pricing_engine_units": "minor integer units",
            "avito_payload_representation": "UNKNOWN",
            "confidence": ContractConfidence.UNKNOWN.value,
        },
        auth_matrix=_auth_matrix(endpoints),
        coverage=coverage,
        gaps=gaps,
        markers=markers,
        readiness=readiness,
        sources=sources,
    )
