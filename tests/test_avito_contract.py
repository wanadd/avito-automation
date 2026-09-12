from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.integrations.avito_contract.assets import (
    discover_public_links,
    parse_csv_fields,
    parse_xml_fields,
    parse_xlsx_fields,
    parse_zip_fields,
)
from app.integrations.avito_contract.fetcher import harvest_public_sources
from app.integrations.avito_contract.gate import compute_gate_markers
from app.integrations.avito_contract.network import discover_frontend_endpoints, response_manifest, sanitize_headers
from app.integrations.avito_contract.openapi import extract_autoload_endpoints, lifecycle_for
from app.integrations.avito_contract.parser import extract_embedded_category_tree_nodes
from app.integrations.avito_contract.provenance import load_manifest, save_manifest
from app.integrations.avito_contract.registry import harvest, normalize, report, validate
from app.integrations.avito_contract.types import (
    AvitoFieldContract,
    ContractConfidence,
    ContractLifecycle,
    ContractSourceType,
    CoverageMetrics,
    RuntimeAccess,
    SourceManifestEntry,
)


def sample_openapi() -> dict:
    return {
        "openapi": "3.0.0",
        "security": [{"ClientCredentials": ["autoload"]}],
        "paths": {
            "/autoload/v1/user-docs/tree": {
                "get": {
                    "operationId": "getUserDocsTree",
                    "tags": ["Autoload"],
                    "summary": "Получение дерева категорий",
                    "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Tree"}}}}},
                }
            },
            "/autoload/v1/user-docs/node/{node_slug}/fields": {
                "get": {
                    "operationId": "getNodeFields",
                    "tags": ["Autoload"],
                    "deprecated": True,
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
            "/autoload/v4/upload": {
                "post": {
                    "operationId": "uploadAutoloadV4",
                    "tags": ["Autoload"],
                    "requestBody": {"content": {"application/xml": {"schema": {"type": "string"}}}},
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
            "/items": {"get": {"operationId": "listItems", "responses": {"200": {"description": "ok"}}}},
        },
    }


def write_sample_raw(root: Path) -> None:
    (root / "raw").mkdir(parents=True)
    (root / "raw" / "openapi.json").write_text(json.dumps(sample_openapi()), encoding="utf-8")
    (root / "raw" / "templates").mkdir(parents=True)
    (root / "raw" / "templates" / "templates.html").write_text(
        "<a href=\"/autoload/documentation/templates/67097\"><span>Ноутбуки</span></a>"
        "<Ads><Ad><Title>Телефон</Title><Price>65000</Price><Images><Image url=\"x\"/></Images></Ad></Ads>",
        encoding="utf-8",
    )
    save_manifest(
        root / "manifest.json",
        [
            SourceManifestEntry(
                url="https://example.test/openapi.json",
                path="raw/openapi.json",
                downloaded_at="2026-09-12T00:00:00Z",
                sha256="abc",
                content_type="application/json",
                source_type=ContractSourceType.OFFICIAL_OPENAPI,
                status=200,
                runtime_access=RuntimeAccess.PUBLIC,
            ),
            SourceManifestEntry(
                url="https://example.test/templates",
                path="raw/templates/templates.html",
                downloaded_at="2026-09-12T00:00:00Z",
                sha256="def",
                content_type="text/html",
                source_type=ContractSourceType.OFFICIAL_TEMPLATE,
                status=200,
                runtime_access=RuntimeAccess.PUBLIC,
            ),
        ],
    )


def test_openapi_parser_extracts_autoload_endpoints() -> None:
    endpoints = extract_autoload_endpoints(sample_openapi(), "https://example.test/openapi.json")
    assert [endpoint.path for endpoint in endpoints] == [
        "/autoload/v1/user-docs/node/{node_slug}/fields",
        "/autoload/v1/user-docs/tree",
        "/autoload/v4/upload",
    ]
    assert all(endpoint.runtime_access == RuntimeAccess.AUTH_REQUIRED for endpoint in endpoints)


def test_schema_extraction_and_auth_matrix_inputs() -> None:
    upload = [endpoint for endpoint in extract_autoload_endpoints(sample_openapi()) if endpoint.operation_id == "uploadAutoloadV4"][0]
    assert upload.request_schema == {"type": "string"}
    assert upload.response_schema == {"type": "object"}
    assert upload.required_scopes == ["autoload"]


def test_lifecycle_current_vs_legacy_precedence() -> None:
    assert lifecycle_for("/autoload/v4/upload", {}) == ContractLifecycle.CURRENT
    assert lifecycle_for("/autoload/v2/report", {}) == ContractLifecycle.LEGACY
    assert lifecycle_for("/autoload/v1/x", {"deprecated": True}) == ContractLifecycle.DEPRECATED


def test_offline_mode_normalizes_deterministically(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    first = harvest(root=tmp_path, offline=True)
    second = harvest(root=tmp_path, offline=True)
    assert first.markers == second.markers
    assert (tmp_path / "normalized" / "api_surface.json").read_text(encoding="utf-8") == (
        tmp_path / "normalized" / "api_surface.json"
    ).read_text(encoding="utf-8")


def test_field_normalization_and_enum_unknown(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    snapshot = normalize(root=tmp_path)
    fields = {field.field_id: field for field in snapshot.field_definitions}
    assert "Title" in fields
    assert fields["Title"].required is None
    assert snapshot.enums == []


def test_category_normalization_from_template_links(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    snapshot = normalize(root=tmp_path)
    assert any(node.name == "Ноутбуки" for node in snapshot.category_tree)
    laptop = [item for item in snapshot.category_contracts if item.target == "LAPTOPS"][0]
    assert laptop.mapping_status == "UNCONFIRMED"


def test_embedded_category_tree_extraction(tmp_path: Path) -> None:
    page = tmp_path / "page.html"
    payload = {"layout": {"header": {"categoryTree": [{"name": "Все категории", "mcId": 1, "subs": [{"name": "Электроника", "mcId": 10, "subs": [{"name": "Ноутбуки", "mcId": 46, "subs": []}]}]}]}}}
    page.write_text(f"window.__preloadedState__ = {json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)};", encoding="utf-8")
    nodes = extract_embedded_category_tree_nodes([page])
    laptop = [node for node in nodes if node.name == "Ноутбуки"][0]
    assert laptop.path == ["Все категории", "Электроника", "Ноутбуки"]
    assert laptop.source_type == ContractSourceType.PUBLIC_FRONTEND_CONTRACT


def test_electronics_mapping_requires_electronics_path(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    payload = {"layout": {"header": {"categoryTree": [{"name": "Все категории", "mcId": 1, "subs": [{"name": "Электроника", "mcId": 7, "subs": [{"name": "Наушники", "mcId": 293, "subs": []}]}]}]}}}
    (tmp_path / "raw" / "templates" / "templates.html").write_text(
        f"window.__preloadedState__ = {json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)};",
        encoding="utf-8",
    )
    snapshot = normalize(root=tmp_path)
    headphones = [item for item in snapshot.category_contracts if item.target == "HEADPHONES"][0]
    assert headphones.display_name == "Наушники"
    assert headphones.mapping_status == "PARTIAL_SOURCE_MATCH"


def test_dependency_extraction_unknown_is_empty_not_inferred(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    snapshot = normalize(root=tmp_path)
    assert snapshot.dependencies == []


def test_auth_matrix_contains_auth_required_live_tree(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    markers = validate(root=tmp_path)
    assert markers["CATEGORY TREE LIVE"] == "AUTH_REQUIRED"


def test_report_generation(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    snapshot = report(root=tmp_path)
    assert snapshot.markers["AVITO LISTING CONTRACT GATE"] == "FAIL"
    assert (tmp_path / "reports" / "avito_listing_contract_v1.md").exists()
    assert (tmp_path / "reports" / "avito_electronics_mapping.md").exists()
    assert (tmp_path / "reports" / "avito_contract_gaps.md").exists()


def test_missing_source_fails_openapi_without_crashing(tmp_path: Path) -> None:
    save_manifest(tmp_path / "manifest.json", [])
    snapshot = normalize(root=tmp_path)
    assert snapshot.markers["AVITO OPENAPI DISCOVERY"] == "FAIL"
    assert snapshot.markers["AVITO LISTING CONTRACT GATE"] == "FAIL"


def test_malformed_openapi_is_handled(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir(parents=True)
    (tmp_path / "raw" / "openapi.json").write_text("{bad", encoding="utf-8")
    save_manifest(tmp_path / "manifest.json", [])
    snapshot = normalize(root=tmp_path)
    assert snapshot.api_surface == []


def test_duplicate_source_is_deduped_by_field_id(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    (tmp_path / "raw" / "templates" / "templates2.html").write_text("<Title>x</Title>", encoding="utf-8")
    manifest = load_manifest(tmp_path / "manifest.json")
    manifest.append(
        SourceManifestEntry(
            url="https://example.test/templates2",
            path="raw/templates/templates2.html",
            downloaded_at="2026-09-12T00:00:00Z",
            sha256="ghi",
            content_type="text/html",
            source_type=ContractSourceType.OFFICIAL_TEMPLATE,
            status=200,
            runtime_access=RuntimeAccess.PUBLIC,
        )
    )
    save_manifest(tmp_path / "manifest.json", manifest)
    snapshot = normalize(root=tmp_path)
    titles = [field for field in snapshot.field_definitions if field.field_id == "Title"]
    assert len(titles) == 1


def test_completeness_metrics(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    snapshot = normalize(root=tmp_path)
    assert snapshot.coverage.total_discovered_fields >= 4
    assert snapshot.coverage.required_fields_unknown == snapshot.coverage.total_discovered_fields


def test_fetcher_records_auth_required(monkeypatch, tmp_path: Path) -> None:
    import urllib.error

    def deny(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test", 403, "Forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", deny)
    entries = harvest_public_sources(tmp_path, refresh=True)
    assert entries
    assert any(entry.runtime_access == RuntimeAccess.AUTH_REQUIRED for entry in entries)


def test_template_asset_discovery_finds_public_template_links(tmp_path: Path) -> None:
    page = tmp_path / "page.html"
    page.write_text(
        '<a href="/autoload/documentation/templates/67097">Ноутбуки</a>'
        '<script src="/static/autoload-frontend/client/Documentation.js"></script>'
        '<a href="https://evil.example/template.xml">bad</a>',
        encoding="utf-8",
    )
    links = discover_public_links([page], "https://www.avito.ru/")
    assert "https://www.avito.ru/autoload/documentation/templates/67097" in links
    assert "https://www.avito.ru/static/autoload-frontend/client/Documentation.js" in links
    assert not any("evil.example" in link for link in links)


def test_xml_parser_extracts_field_names() -> None:
    parsed = parse_xml_fields(b"<Ads><Ad><Id>1</Id><Title>x</Title><Price>10</Price></Ad></Ads>")
    assert parsed["root"] == "Ads"
    assert {"Ad", "Id", "Title", "Price"}.issubset(set(parsed["fields"]))


def test_csv_parser_extracts_header_fields() -> None:
    parsed = parse_csv_fields("Id,Title,Price\n1,Phone,10\n")
    assert parsed["fields"] == ["Id", "Title", "Price"]
    assert parsed["rows"] == 1


def test_xlsx_parser_reads_first_row_and_validations() -> None:
    content = _minimal_xlsx(
        worksheet=(
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row></sheetData>'
            '<dataValidations count="1"><dataValidation type="list" sqref="A2:A10"><formula1>"Новое,Б/у"</formula1></dataValidation></dataValidations>'
            "</worksheet>"
        )
    )
    parsed = parse_xlsx_fields(content)
    assert parsed["fields"] == ["Id", "Title"]
    assert parsed["data_validations"][0]["type"] == "list"


def test_zip_parser_skips_unsafe_member_paths() -> None:
    buffer = __import__("io").BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../bad.csv", "Secret\nx\n")
        archive.writestr("safe.csv", "Id,Title\n1,x\n")
    parsed = parse_zip_fields(buffer.getvalue())
    assert "Title" in parsed["fields"]
    assert any(item["status"] == "SKIPPED_UNSAFE_PATH" for item in parsed["members"])


def test_network_manifest_sanitizes_sensitive_headers() -> None:
    sanitized = sanitize_headers({"Cookie": "a=b", "Authorization": "Bearer x", "Content-Type": "application/json"})
    assert sanitized == {"Content-Type": "application/json"}
    manifest = response_manifest(
        method="GET",
        url="https://www.avito.ru/autoload/schema",
        status=200,
        content_type="application/json",
        content=b"{}",
        discovered_from="test",
        headers={"Set-Cookie": "x", "X-Request-Id": "1"},
    )
    assert "Set-Cookie" not in manifest["headers"]
    assert manifest["response_sha256"]


def test_frontend_endpoint_extraction_from_public_static_payload(tmp_path: Path) -> None:
    js = tmp_path / "app.js"
    js.write_text('fetch("/autoload/documentation/templates/67097"); const x="/api/1/schema";', encoding="utf-8")
    endpoints = discover_frontend_endpoints([js], "test")
    assert [item["url"] for item in endpoints] == ["/api/1/schema", "/autoload/documentation/templates/67097"]
    assert all(item["headers"] == {} for item in endpoints)


def test_conflict_resolution_marks_equal_authority_required_conflict(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    snapshot = normalize(root=tmp_path)
    title = [field for field in snapshot.field_definitions if field.field_id == "Title"][0]
    conflict = AvitoFieldContract(**{**title.__dict__, "required": True})
    title.required = False
    from app.integrations.avito_contract.normalizer import _contract_conflicts

    conflicts = _contract_conflicts([title, conflict])
    assert conflicts[0]["unresolved"] is True


def test_zero_coverage_gate_fails_but_generic_readiness_can_continue() -> None:
    markers, readiness = compute_gate_markers(
        implementation_ok=True,
        public_sources_found=True,
        autoload_operations=4,
        template_assets=2,
        current_versions=0,
        listing_core_confirmed=0,
        category_fields_confirmed=0,
        coverage=CoverageMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        conflicts=0,
        security_ok=True,
    )
    assert markers["HARVESTER IMPLEMENTATION"] == "PASS"
    assert readiness["AVITO LISTING CONTRACT GATE"] == "FAIL"
    assert readiness["SPRINT 0.9 GENERIC CONTENT ENGINE READINESS"] == "PASS_WITH_LIMITATIONS"
    assert readiness["SPRINT 0.9 AVITO LISTING ADAPTER READINESS"] == "FAIL"


def test_offline_replay_normalized_hashes_are_deterministic(tmp_path: Path) -> None:
    write_sample_raw(tmp_path)
    harvest(root=tmp_path, offline=True)
    first = (tmp_path / "normalized" / "category_contracts.json").read_bytes()
    harvest(root=tmp_path, offline=True)
    second = (tmp_path / "normalized" / "category_contracts.json").read_bytes()
    assert first == second


def _minimal_xlsx(worksheet: str) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<si><t>Id</t></si><si><t>Title</t></si></sst>",
        )
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return buffer.getvalue()
