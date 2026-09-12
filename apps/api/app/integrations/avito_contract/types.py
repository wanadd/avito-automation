from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ContractSourceType(StrEnum):
    OFFICIAL_OPENAPI = "OFFICIAL_OPENAPI"
    OFFICIAL_DOCS = "OFFICIAL_DOCS"
    OFFICIAL_TEMPLATE = "OFFICIAL_TEMPLATE"
    OFFICIAL_REFERENCE = "OFFICIAL_REFERENCE"
    PUBLIC_FRONTEND_CONTRACT = "PUBLIC_FRONTEND_CONTRACT"
    PUBLIC_API_MIRROR = "PUBLIC_API_MIRROR"
    THIRD_PARTY_DOC = "THIRD_PARTY_DOC"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class ContractConfidence(StrEnum):
    CONFIRMED = "CONFIRMED"
    STRONG = "STRONG"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class ContractLifecycle(StrEnum):
    CURRENT = "CURRENT"
    DEPRECATED = "DEPRECATED"
    LEGACY = "LEGACY"
    REMOVED = "REMOVED"
    UNKNOWN = "UNKNOWN"


class RuntimeAccess(StrEnum):
    PUBLIC = "PUBLIC"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNKNOWN = "UNKNOWN"


class Completeness(StrEnum):
    COMPLETE = "COMPLETE"
    MOSTLY_COMPLETE = "MOSTLY_COMPLETE"
    PARTIAL = "PARTIAL"
    BLOCKED_BY_AUTH = "BLOCKED_BY_AUTH"
    UNKNOWN = "UNKNOWN"


class GateStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_LIMITATIONS = "PASS_WITH_LIMITATIONS"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNKNOWN = "UNKNOWN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class SourceCandidate:
    url: str
    raw_path: str
    source_type: ContractSourceType
    expected_kind: str


@dataclass
class SourceManifestEntry:
    url: str
    path: str
    downloaded_at: str | None
    sha256: str | None
    content_type: str | None
    source_type: ContractSourceType
    status: int | None
    runtime_access: RuntimeAccess
    error: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source_type, str):
            self.source_type = ContractSourceType(self.source_type)
        if isinstance(self.runtime_access, str):
            self.runtime_access = RuntimeAccess(self.runtime_access)


@dataclass
class AvitoEndpointContract:
    path: str
    method: str
    operation_id: str | None
    tags: list[str]
    summary: str | None
    request_schema: dict[str, Any] | None
    response_schema: dict[str, Any] | None
    auth_type: str | None
    deprecated: bool
    lifecycle: ContractLifecycle
    required_scopes: list[str]
    rate_limits: list[str]
    runtime_access: RuntimeAccess
    source_type: ContractSourceType
    confidence: ContractConfidence
    evidence_url: str | None


@dataclass
class AvitoCategoryNode:
    slug: str | None
    name: str | None
    parent_slug: str | None
    path: list[str]
    source_type: ContractSourceType
    confidence: ContractConfidence
    runtime_access: str


@dataclass
class AvitoFieldContract:
    field_id: str
    api_name: str | None
    display_name: str | None
    field_type: str | None
    required: bool | None
    conditional: bool
    enum_values: list[str]
    min_value: int | float | None
    max_value: int | float | None
    min_length: int | None
    max_length: int | None
    pattern: str | None
    depends_on: list[str]
    dependencies_raw: dict[str, Any] | None
    category_slugs: list[str]
    source_type: ContractSourceType
    confidence: ContractConfidence
    runtime_access: str
    evidence_url: str | None


@dataclass
class AvitoImageContract:
    min_count: int | None
    max_count: int | None
    formats: list[str]
    min_width: int | None
    min_height: int | None
    max_size_bytes: int | None
    remote_url_allowed: bool | None
    ordering_supported: bool | None
    source_type: ContractSourceType
    confidence: ContractConfidence


@dataclass
class ElectronicsCategoryContract:
    target: str
    display_name: str | None = None
    category_path: list[str] = field(default_factory=list)
    category_slug: str | None = None
    parent_category: str | None = None
    autoload_category_value: str | None = None
    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    conditional_fields: list[str] = field(default_factory=list)
    enum_fields: list[str] = field(default_factory=list)
    auth_locked_fields: list[str] = field(default_factory=list)
    contract_completeness: Completeness = Completeness.UNKNOWN
    mapping_status: str = "UNCONFIRMED"


@dataclass
class CoverageMetrics:
    total_discovered_fields: int
    confirmed_fields: int
    strong_fields: int
    partial_fields: int
    unknown_fields: int
    auth_locked_fields: int
    enum_fields_with_values: int
    enum_fields_without_values: int
    required_fields_confirmed: int
    required_fields_unknown: int


@dataclass
class AvitoContractSnapshot:
    api_surface: list[AvitoEndpointContract]
    category_tree: list[AvitoCategoryNode]
    field_definitions: list[AvitoFieldContract]
    enums: list[dict[str, Any]]
    dependencies: list[dict[str, Any]]
    category_contracts: list[ElectronicsCategoryContract]
    template_assets: list[dict[str, Any]]
    public_network_endpoints: list[dict[str, Any]]
    autoload_versions: dict[str, Any]
    listing_core_contract: dict[str, Any]
    contract_conflicts: list[dict[str, Any]]
    image_contract: AvitoImageContract
    autoload_payload_contract: dict[str, Any]
    title_description_rules: dict[str, Any]
    price_contract: dict[str, Any]
    auth_matrix: list[dict[str, Any]]
    coverage: CoverageMetrics
    gaps: list[dict[str, Any]]
    markers: dict[str, str]
    readiness: dict[str, str]
    sources: list[SourceManifestEntry]


class AvitoContractProvider(Protocol):
    async def get_category_tree(self) -> list[AvitoCategoryNode]:
        ...

    async def get_category_fields(self, node_slug: str) -> list[AvitoFieldContract]:
        ...


def to_jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    return value
