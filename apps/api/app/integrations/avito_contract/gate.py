from __future__ import annotations

from app.integrations.avito_contract.types import CoverageMetrics, GateStatus


def compute_gate_markers(
    *,
    implementation_ok: bool,
    public_sources_found: bool,
    autoload_operations: int,
    template_assets: int,
    current_versions: int,
    listing_core_confirmed: int,
    category_fields_confirmed: int,
    coverage: CoverageMetrics,
    conflicts: int,
    security_ok: bool,
) -> tuple[dict[str, str], dict[str, str]]:
    markers = {
        "HARVESTER IMPLEMENTATION": GateStatus.PASS.value if implementation_ok else GateStatus.FAIL.value,
        "PUBLIC TEMPLATE ASSET DISCOVERY": GateStatus.PASS_WITH_LIMITATIONS.value if template_assets else GateStatus.FAIL.value,
        "PUBLIC NETWORK CONTRACT DISCOVERY": GateStatus.PASS_WITH_LIMITATIONS.value if public_sources_found else GateStatus.FAIL.value,
        "CURRENT AUTOLOAD VERSION DISCOVERY": GateStatus.PASS.value if current_versions else GateStatus.FAIL.value,
        "LISTING CORE CONTRACT": GateStatus.PASS_WITH_LIMITATIONS.value if listing_core_confirmed else GateStatus.FAIL.value,
        "CATEGORY FIELD CONTRACT": GateStatus.PASS.value if category_fields_confirmed else GateStatus.AUTH_REQUIRED.value,
        "TITLE/DESCRIPTION CONTRACT": GateStatus.UNKNOWN.value,
        "IMAGE CONTRACT": GateStatus.UNKNOWN.value,
        "PRICE CONTRACT": GateStatus.UNKNOWN.value,
        "ELECTRONICS CATEGORY MAPPING": GateStatus.PASS_WITH_LIMITATIONS.value if template_assets else GateStatus.FAIL.value,
        "CONTRACT CONFLICT CHECK": GateStatus.PASS.value if conflicts == 0 else GateStatus.FAIL.value,
        "OFFLINE REPRODUCIBILITY": GateStatus.PASS.value,
        "SECURITY CHECK": GateStatus.PASS.value if security_ok else GateStatus.FAIL.value,
    }
    zero_contract = (
        coverage.confirmed_fields == 0
        and listing_core_confirmed == 0
        and category_fields_confirmed == 0
    )
    adapter_ready = GateStatus.FAIL.value
    if (
        not zero_contract
        and listing_core_confirmed >= 5
        and category_fields_confirmed > 0
        and current_versions > 0
        and conflicts == 0
    ):
        adapter_ready = GateStatus.PASS_WITH_LIMITATIONS.value
    generic_ready = GateStatus.PASS_WITH_LIMITATIONS.value if public_sources_found else GateStatus.FAIL.value
    listing_gate = GateStatus.FAIL.value if zero_contract or category_fields_confirmed == 0 else adapter_ready
    readiness = {
        "SPRINT 0.9 GENERIC CONTENT ENGINE READINESS": generic_ready,
        "SPRINT 0.9 AVITO LISTING ADAPTER READINESS": adapter_ready,
        "AVITO LISTING CONTRACT GATE": listing_gate,
        "AVITO PUBLIC RESEARCH": GateStatus.PASS_WITH_LIMITATIONS.value if public_sources_found else GateStatus.FAIL.value,
    }
    return markers, readiness
