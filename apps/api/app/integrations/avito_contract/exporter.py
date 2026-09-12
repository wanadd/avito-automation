from __future__ import annotations

from pathlib import Path

from app.integrations.avito_contract.provenance import write_json
from app.integrations.avito_contract.types import AvitoContractSnapshot, to_jsonable


def write_normalized(root: Path, snapshot: AvitoContractSnapshot) -> None:
    normalized = root / "normalized"
    write_json(normalized / "api_surface.json", snapshot.api_surface)
    write_json(normalized / "category_tree.json", snapshot.category_tree)
    write_json(normalized / "field_definitions.json", snapshot.field_definitions)
    write_json(normalized / "enums.json", snapshot.enums)
    write_json(normalized / "dependencies.json", snapshot.dependencies)
    write_json(normalized / "category_contracts.json", snapshot.category_contracts)
    write_json(normalized / "template_assets.json", snapshot.template_assets)
    write_json(normalized / "public_network_endpoints.json", snapshot.public_network_endpoints)
    write_json(normalized / "autoload_versions.json", snapshot.autoload_versions)
    write_json(normalized / "listing_core_contract.json", snapshot.listing_core_contract)
    write_json(normalized / "contract_conflicts.json", snapshot.contract_conflicts)
    write_json(normalized / "provenance.json", snapshot.sources)
    write_json(normalized / "autoload_payload_contract.json", snapshot.autoload_payload_contract)
    write_json(normalized / "auth_matrix.json", snapshot.auth_matrix)
    write_json(normalized / "coverage.json", snapshot.coverage)


def _table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(rows[0]) + " |"
    sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows[1:]]
    return "\n".join([header, sep, *body])


def write_reports(root: Path, snapshot: AvitoContractSnapshot) -> None:
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    mapping_rows = [["Target", "Avito category", "Slug", "Confirmed", "Unknown", "Completeness"]]
    for contract in snapshot.category_contracts:
        mapping_rows.append(
            [
                contract.target,
                contract.display_name or "UNKNOWN",
                contract.category_slug or "UNKNOWN",
                "NO",
                "category, fields",
                contract.contract_completeness.value,
            ]
        )
    (reports / "avito_electronics_mapping.md").write_text(
        "# Avito Electronics Mapping\n\n"
        + _table(mapping_rows)
        + "\n\nMappings from internal product attributes remain UNCONFIRMED unless explicitly present in sources.\n",
        encoding="utf-8",
    )

    gap_rows = [["ID", "Category", "Field", "Severity", "Can Sprint 0.9 proceed?", "Problem"]]
    for gap in snapshot.gaps:
        gap_rows.append(
            [
                gap["id"],
                gap["category"],
                str(gap["field"] or ""),
                gap["severity"],
                str(gap["can_sprint_0_9_proceed"]),
                gap["problem"],
            ]
        )
    (reports / "avito_contract_gaps.md").write_text(
        "# Avito Contract Gaps\n\n" + _table(gap_rows) + "\n",
        encoding="utf-8",
    )

    markers = "\n".join(f"{name}: {status}" for name, status in snapshot.markers.items())
    readiness = "\n".join(f"{name}: {status}" for name, status in snapshot.readiness.items())
    endpoint_rows = [["Method", "Path", "Operation", "Lifecycle", "Runtime access"]]
    for endpoint in snapshot.api_surface:
        endpoint_rows.append(
            [
                endpoint.method,
                endpoint.path,
                endpoint.operation_id or "",
                endpoint.lifecycle.value,
                endpoint.runtime_access.value,
            ]
        )
    source_rows = [["Source", "Type", "Status", "Access", "SHA256"]]
    for source in snapshot.sources:
        source_rows.append(
            [
                source.url,
                source.source_type.value,
                str(source.status or "ERR"),
                source.runtime_access.value,
                source.sha256 or "",
            ]
        )
    coverage = to_jsonable(snapshot.coverage)
    coverage_lines = "\n".join(f"- {key}: {value}" for key, value in coverage.items())
    core_rows = [["Field", "Status", "Source", "Evidence"]]
    for field, item in snapshot.listing_core_contract["fields"].items():
        core_rows.append([field, item["status"], item["source_type"], item["evidence_url"] or ""])
    version_rows = [["Version", "Lifecycle", "Evidence count"]]
    for item in snapshot.autoload_versions["versions"]:
        version_rows.append([item["version"], item["lifecycle"], str(len(item["evidence"]))])
    (reports / "avito_listing_contract_v1.md").write_text(
        "# Avito Listing Contract V1\n\n"
        "## AVITO OPENAPI DISCOVERY\n"
        f"{snapshot.markers['AVITO OPENAPI DISCOVERY']}\n\n"
        "## AUTOLOAD API SURFACE\n"
        + (_table(endpoint_rows) if snapshot.api_surface else "No Autoload endpoints confirmed from raw OpenAPI.")
        + "\n\n## CATEGORY TREE DISCOVERY\n"
        f"{snapshot.markers['CATEGORY TREE DISCOVERY']}\n\n"
        "## CATEGORY FIELD DISCOVERY\n"
        f"{snapshot.markers['CATEGORY FIELD DISCOVERY']}\n\n"
        "## AUTOLOAD FORMAT\n"
        f"{snapshot.autoload_payload_contract['format']}\n\n"
        "## TITLE RULES\nUNKNOWN\n\n"
        "## DESCRIPTION RULES\nUNKNOWN\n\n"
        "## IMAGE RULES\nUNKNOWN\n\n"
        "## PRICE RULES\nAvito payload representation UNKNOWN. Internal pricing engine remains minor integer units.\n\n"
        "## DELIVERY FIELDS\nUNKNOWN\n\n"
        "## LOCATION FIELDS\nUNKNOWN\n\n"
        "## CONTACT FIELDS\nUNKNOWN\n\n"
        "## LIFECYCLE CHECK\n"
        f"{snapshot.markers['LIFECYCLE CHECK']}\n\n"
        "## CURRENT AUTOLOAD VERSION DISCOVERY\n"
        + _table(version_rows)
        + "\n\n## LISTING CORE CONTRACT\n"
        + _table(core_rows)
        + "\n\n"
        "## AUTH MATRIX\n"
        + _table([["Operation", "Schema", "Runtime auth", "Paid", "Account", "Safe"], *[
            [
                item["operation"],
                str(item["public_schema_available"]),
                str(item["runtime_auth_required"]),
                str(item["paid_tariff_likely_required"]),
                str(item["account_specific"]),
                str(item["safe_for_future_use"]),
            ]
            for item in snapshot.auth_matrix
        ]])
        + "\n\n## ELECTRONICS CATEGORY MAPPING\nSee avito_electronics_mapping.md.\n\n"
        "## CONTRACT COVERAGE\n"
        f"{coverage_lines}\n\n"
        "## CONTRACT GAPS\nSee avito_contract_gaps.md.\n\n"
        "## SOURCES\n"
        + _table(source_rows)
        + "\n\n## SPRINT 0.9 READINESS\n"
        f"{readiness}\n\n"
        "## SECURITY CHECK\nNo credentials, cookies, sessions, tokens, or API mutations are used by this harvester.\n\n"
        "## FINAL MARKERS\n"
        f"{markers}\n",
        encoding="utf-8",
    )

    network_rows = [["Method", "URL", "Status", "Content-Type", "Auth", "SHA256"]]
    for item in snapshot.public_network_endpoints[:200]:
        network_rows.append(
            [
                item["method"],
                item["url"],
                str(item["status"] or ""),
                item["content_type"] or "",
                str(item["auth_required"]),
                item["response_sha256"] or "",
            ]
        )
    asset_rows = [["URL", "Type", "Status", "Raw path"]]
    for item in snapshot.template_assets[:200]:
        asset_rows.append(
            [
                item["url"],
                item["asset_type"],
                item["parsed"].get("status", ""),
                item["raw_path"],
            ]
        )
    conflict_rows = [["Field", "Category", "Unresolved", "Reason"]]
    for item in snapshot.contract_conflicts:
        conflict_rows.append(
            [
                item["field"],
                str(item["category"] or ""),
                str(item["unresolved"]),
                item["preference_reason"],
            ]
        )
    (reports / "avito_recovery_pass.md").write_text(
        "# Avito Contract Recovery Pass\n\n"
        "## Sources Discovered\n"
        + _table(source_rows)
        + "\n\n## Template Assets Discovered\n"
        + _table(asset_rows)
        + "\n\n## Public Network Endpoints Discovered\n"
        + _table(network_rows)
        + "\n\n## Autoload Versions\n"
        + _table(version_rows)
        + "\n\n## Listing Core Field Coverage\n"
        + _table(core_rows)
        + "\n\n## Category-Specific Field Coverage\n"
        f"{coverage_lines}\n\n"
        "## Contract Conflicts\n"
        + (_table(conflict_rows) if snapshot.contract_conflicts else "No field-definition contradictions found.")
        + "\n\n## Safe Fallback Architecture Recommendation\n"
        "ProductVariant -> ContentFacts -> ContentDraft -> ImageSet -> GenericListingDraft -> ListingValidation -> AvitoAdapter(DISABLED / CONTRACT_INCOMPLETE)\n\n"
        "## Readiness\n"
        f"{readiness}\n\n"
        "## Final Markers\n"
        f"{markers}\n",
        encoding="utf-8",
    )
