from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.integrations.avito_contract.types import (
    AvitoEndpointContract,
    ContractConfidence,
    ContractLifecycle,
    ContractSourceType,
    RuntimeAccess,
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
AUTOLOAD_HINTS = ("autoload", "user-docs", "upload", "report", "status")


def load_openapi(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            import yaml

            loaded = yaml.safe_load(raw)
            return loaded if isinstance(loaded, dict) else None
        except Exception:
            return None


def _schema_ref(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    if "schema" in payload and isinstance(payload["schema"], dict):
        return payload["schema"]
    content = payload.get("content")
    if isinstance(content, dict):
        for media in sorted(content):
            schema = content[media].get("schema") if isinstance(content[media], dict) else None
            if isinstance(schema, dict):
                return schema
    return None


def _auth_type(operation: dict[str, Any], root: dict[str, Any]) -> tuple[str | None, list[str], RuntimeAccess]:
    security = operation.get("security", root.get("security", []))
    if security == []:
        return None, [], RuntimeAccess.PUBLIC
    if isinstance(security, list) and security:
        names: list[str] = []
        scopes: list[str] = []
        for item in security:
            if isinstance(item, dict):
                for name, values in item.items():
                    names.append(str(name))
                    if isinstance(values, list):
                        scopes.extend(str(value) for value in values)
        return ",".join(sorted(set(names))) or "AUTH", sorted(set(scopes)), RuntimeAccess.AUTH_REQUIRED
    return None, [], RuntimeAccess.UNKNOWN


def lifecycle_for(path: str, operation: dict[str, Any]) -> ContractLifecycle:
    if operation.get("deprecated") is True:
        return ContractLifecycle.DEPRECATED
    lowered = path.lower()
    if "/v1/" in lowered or "/v2/" in lowered or "/v3/" in lowered:
        if "/autoload/v4" in lowered:
            return ContractLifecycle.CURRENT
        return ContractLifecycle.LEGACY if "/autoload/" in lowered else ContractLifecycle.UNKNOWN
    if "/autoload/v4" in lowered:
        return ContractLifecycle.CURRENT
    return ContractLifecycle.UNKNOWN


def extract_autoload_endpoints(spec: dict[str, Any], evidence_url: str | None = None) -> list[AvitoEndpointContract]:
    endpoints: list[AvitoEndpointContract] = []
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        return endpoints
    for path, path_item in sorted(paths.items()):
        if not isinstance(path_item, dict):
            continue
        for method, operation in sorted(path_item.items()):
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            tags = [str(tag) for tag in operation.get("tags", []) if tag is not None]
            haystack = " ".join([path, operation.get("operationId", ""), operation.get("summary", ""), *tags]).lower()
            if not any(hint in haystack for hint in AUTOLOAD_HINTS):
                continue
            request_schema = _schema_ref(operation.get("requestBody"))
            responses = operation.get("responses", {})
            response_schema = None
            if isinstance(responses, dict):
                for code in sorted(responses):
                    if str(code).startswith("2") and isinstance(responses[code], dict):
                        response_schema = _schema_ref(responses[code])
                        break
            auth_type, scopes, runtime_access = _auth_type(operation, spec)
            endpoints.append(
                AvitoEndpointContract(
                    path=path,
                    method=method.upper(),
                    operation_id=operation.get("operationId"),
                    tags=tags,
                    summary=operation.get("summary"),
                    request_schema=request_schema,
                    response_schema=response_schema,
                    auth_type=auth_type,
                    deprecated=operation.get("deprecated") is True,
                    lifecycle=lifecycle_for(path, operation),
                    required_scopes=scopes,
                    rate_limits=[],
                    runtime_access=runtime_access,
                    source_type=ContractSourceType.OFFICIAL_OPENAPI,
                    confidence=ContractConfidence.CONFIRMED,
                    evidence_url=evidence_url,
                )
            )
    return endpoints
