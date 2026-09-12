from __future__ import annotations

import re
import json
from html import unescape
from pathlib import Path
from typing import Any

from app.integrations.avito_contract.types import (
    AvitoCategoryNode,
    AvitoFieldContract,
    ContractConfidence,
    ContractSourceType,
    RuntimeAccess,
)

TAG_RE = re.compile(r"<[^>]+>")
XML_FIELD_RE = re.compile(r"<([A-Za-zА-Яа-я0-9_:-]+)>")
MARKDOWN_ENDPOINT_RE = re.compile(r"(?:\*\*)?\b(GET|POST|PUT|PATCH|DELETE)\b(?:\*\*)?\s+(/autoload/[^\s`|]+)", re.I)
TEMPLATE_CATEGORY_RE = re.compile(
    r'href="(/autoload/documentation/templates/(\d+))"[^>]*>\s*<span[^>]*>(.*?)</span>',
    re.I | re.S,
)
PRELOADED_STATE_RE = re.compile(r"window\.__preloadedState__\s*=\s*(?P<value>\".*?\");", re.S)
HTML_TAGS = {
    "a",
    "body",
    "br",
    "button",
    "div",
    "form",
    "h1",
    "h2",
    "h3",
    "head",
    "html",
    "iframe",
    "img",
    "input",
    "label",
    "li",
    "link",
    "meta",
    "option",
    "p",
    "script",
    "select",
    "span",
    "style",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}


def text_from_html(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    return unescape(TAG_RE.sub(" ", text))


def extract_template_fields(paths: list[Path]) -> list[AvitoFieldContract]:
    fields: dict[str, AvitoFieldContract] = {}
    for path in paths:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8", errors="ignore")
        for name in sorted(set(XML_FIELD_RE.findall(raw))):
            if name.lower() in HTML_TAGS or name.lower().startswith("xml"):
                continue
            if name and name[0].islower():
                continue
            if name not in fields:
                fields[name] = AvitoFieldContract(
                    field_id=name,
                    api_name=name,
                    display_name=None,
                    field_type="xml_element",
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
                    source_type=ContractSourceType.OFFICIAL_TEMPLATE,
                    confidence=ContractConfidence.PARTIAL,
                    runtime_access=RuntimeAccess.PUBLIC.value,
                    evidence_url=None,
                )
    return list(fields.values())


def extract_markdown_autoload_endpoints(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="ignore")
    found: dict[tuple[str, str], dict[str, str]] = {}
    for method, endpoint_path in MARKDOWN_ENDPOINT_RE.findall(raw):
        key = (method.upper(), endpoint_path.rstrip("/"))
        found[key] = {"method": key[0], "path": key[1]}
    return [found[key] for key in sorted(found)]


def extract_category_nodes_from_openapi(endpoints: list[Any]) -> list[AvitoCategoryNode]:
    nodes: list[AvitoCategoryNode] = []
    for endpoint in endpoints:
        if "user-docs/tree" in endpoint.path:
            nodes.append(
                AvitoCategoryNode(
                    slug=None,
                    name=None,
                    parent_slug=None,
                    path=[],
                    source_type=endpoint.source_type,
                    confidence=ContractConfidence.UNKNOWN,
                    runtime_access=endpoint.runtime_access.value,
                )
            )
            break
    return nodes


def extract_template_category_nodes(paths: list[Path]) -> list[AvitoCategoryNode]:
    nodes: dict[str, AvitoCategoryNode] = {}
    for path in paths:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8", errors="ignore")
        for _, template_id, name_html in TEMPLATE_CATEGORY_RE.findall(raw):
            name = unescape(TAG_RE.sub(" ", name_html)).strip()
            if not name:
                continue
            slug = f"autoload-template-{template_id}"
            nodes[slug] = AvitoCategoryNode(
                slug=slug,
                name=name,
                parent_slug=None,
                path=[name],
                source_type=ContractSourceType.OFFICIAL_TEMPLATE,
                confidence=ContractConfidence.PARTIAL,
                runtime_access=RuntimeAccess.PUBLIC.value,
            )
    return [nodes[key] for key in sorted(nodes)]


def extract_embedded_category_tree_nodes(paths: list[Path]) -> list[AvitoCategoryNode]:
    nodes: dict[str, AvitoCategoryNode] = {}
    for path in paths:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8", errors="ignore")
        for match in PRELOADED_STATE_RE.finditer(raw):
            try:
                state = json.loads(json.loads(match.group("value")))
            except json.JSONDecodeError:
                continue
            roots = (
                state.get("layout", {})
                .get("header", {})
                .get("categoryTree", [])
            )
            _walk_embedded_nodes(roots, [], nodes)
    return [nodes[key] for key in sorted(nodes)]


def _walk_embedded_nodes(items: list[dict], path: list[str], nodes: dict[str, AvitoCategoryNode]) -> None:
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        current_path = [*path, str(name)]
        slug = f"avito-mc-{item.get('mcId') or item.get('categoryId') or item.get('id')}"
        nodes[slug] = AvitoCategoryNode(
            slug=slug,
            name=str(name),
            parent_slug=None,
            path=current_path,
            source_type=ContractSourceType.PUBLIC_FRONTEND_CONTRACT,
            confidence=ContractConfidence.PARTIAL,
            runtime_access=RuntimeAccess.PUBLIC.value,
        )
        subs = item.get("subs")
        if isinstance(subs, list):
            _walk_embedded_nodes(subs, current_path, nodes)
