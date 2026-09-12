from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from html import unescape
from pathlib import Path
from typing import Any

from app.integrations.avito_contract.provenance import sha256_bytes, utc_now_iso

ASSET_EXTENSIONS = (".xml", ".xlsx", ".xls", ".csv", ".zip", ".json", ".yaml", ".yml")
LINK_RE = re.compile(r"""(?:href|src)=["']([^"']+)["']""", re.I)
INTERESTING_URL_RE = re.compile(
    r"""(?P<url>https?://[^"'`\s)]+|/[A-Za-z0-9_./?=&%:-]*(?:template|download|autoload|field|category|reference|dictionary|catalog|schema)[A-Za-z0-9_./?=&%:-]*)""",
    re.I,
)


def discover_public_links(raw_paths: list[Path], base_url: str) -> list[str]:
    urls: set[str] = set()
    for path in raw_paths:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8", errors="ignore")
        for match in LINK_RE.findall(raw):
            joined = _safe_urljoin(base_url, unescape(match))
            if joined:
                urls.add(joined)
        for match in INTERESTING_URL_RE.finditer(raw):
            joined = _safe_urljoin(base_url, unescape(match.group("url")))
            if joined:
                urls.add(joined)
    return sorted(url for url in urls if _is_public_avito_or_static(url))


def _safe_urljoin(base_url: str, value: str) -> str | None:
    try:
        return urllib.parse.urljoin(base_url, value)
    except ValueError:
        return None


def _is_public_avito_or_static(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.fragment or not parsed.path:
        return False
    if parsed.netloc not in {
        "www.avito.ru",
        "avito.ru",
        "developers.avito.ru",
        "www.avito.st",
        "avito.st",
    }:
        return False
    lowered = parsed.path.lower()
    return (
        "/autoload/documentation" in lowered
        or "/api-catalog" in lowered
        or "/static/autoload" in lowered
        or "/s/autoload" in lowered
        or lowered.endswith(ASSET_EXTENSIONS)
        or any(token in lowered for token in ("/schema", "/field", "/dictionary", "/reference"))
    )


def classify_asset_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in ASSET_EXTENSIONS:
        if path.endswith(ext):
            return ext.lstrip(".")
    if path.endswith(".js"):
        return "javascript"
    if "/autoload/documentation/templates/" in path:
        return "template_page"
    return "public_endpoint"


def asset_raw_path(url: str, index: int) -> str:
    kind = classify_asset_url(url)
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix or ".html"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", parsed.path.strip("/") or "index")[-120:]
    return f"raw/recovery/{index:03d}_{kind}_{safe}{'' if safe.endswith(suffix) else suffix}"


def summarize_downloaded_asset(path: Path, url: str, content_type: str | None) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "url": url,
        "raw_path": str(path),
        "asset_type": classify_asset_url(url),
        "content_type": content_type,
        "sha256": sha256_bytes(content),
        "downloaded_at": utc_now_iso(),
        "parsed": parse_template_asset(path),
    }


def parse_template_asset(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".xml":
            return parse_xml_fields(path.read_bytes())
        if suffix == ".csv":
            return parse_csv_fields(path.read_text(encoding="utf-8", errors="ignore"))
        if suffix == ".xlsx":
            return parse_xlsx_fields(path.read_bytes())
        if suffix == ".json":
            return parse_json_fields(path.read_text(encoding="utf-8", errors="ignore"))
        if suffix == ".zip":
            return parse_zip_fields(path.read_bytes())
    except Exception as exc:
        return {"status": "MALFORMED", "error": str(exc), "fields": []}
    return {"status": "UNSUPPORTED", "fields": []}


def parse_xml_fields(content: bytes) -> dict[str, Any]:
    root = ET.fromstring(content)
    fields = sorted({ _local_name(element.tag) for element in root.iter() if _local_name(element.tag) })
    return {"status": "PARSED", "format": "XML", "root": _local_name(root.tag), "fields": fields}


def parse_csv_fields(text: str) -> dict[str, Any]:
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    header = [cell.strip() for cell in rows[0]] if rows else []
    return {"status": "PARSED", "format": "CSV", "fields": [cell for cell in header if cell], "rows": max(0, len(rows) - 1)}


def parse_json_fields(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    fields = sorted(_json_keys(payload))
    return {"status": "PARSED", "format": "JSON", "fields": fields}


def parse_xlsx_fields(content: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        shared_strings = _xlsx_shared_strings(archive)
        fields: set[str] = set()
        validations: list[dict[str, Any]] = []
        comments: list[str] = []
        for name in archive.namelist():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                root = ET.fromstring(archive.read(name))
                for row in root.findall(".//{*}row"):
                    if row.attrib.get("r") != "1":
                        continue
                    for cell in row.findall("{*}c"):
                        value = _xlsx_cell_value(cell, shared_strings)
                        if value:
                            fields.add(value)
                for validation in root.findall(".//{*}dataValidation"):
                    validations.append(dict(validation.attrib))
            if name.startswith("xl/comments") and name.endswith(".xml"):
                root = ET.fromstring(archive.read(name))
                for text_node in root.findall(".//{*}t"):
                    if text_node.text:
                        comments.append(text_node.text)
        return {
            "status": "PARSED",
            "format": "XLSX",
            "fields": sorted(fields),
            "data_validations": validations,
            "comments": comments,
        }


def parse_zip_fields(content: bytes) -> dict[str, Any]:
    parsed: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            target = Path(name)
            if target.is_absolute() or ".." in target.parts:
                parsed.append({"path": name, "status": "SKIPPED_UNSAFE_PATH"})
                continue
            suffix = target.suffix.lower()
            data = archive.read(name)
            if suffix == ".xml":
                parsed.append({"path": name, **parse_xml_fields(data)})
            elif suffix == ".csv":
                parsed.append({"path": name, **parse_csv_fields(data.decode("utf-8", errors="ignore"))})
            elif suffix == ".xlsx":
                parsed.append({"path": name, **parse_xlsx_fields(data)})
        fields = sorted({field for item in parsed for field in item.get("fields", [])})
        return {"status": "PARSED", "format": "ZIP", "fields": fields, "members": parsed}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":", 1)[-1]


def _json_keys(payload: Any, prefix: str = "") -> set[str]:
    if isinstance(payload, dict):
        keys = set()
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.add(path)
            keys.update(_json_keys(value, path))
        return keys
    if isinstance(payload, list):
        keys = set()
        for item in payload:
            keys.update(_json_keys(item, prefix))
        return keys
    return set()


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.itertext()) for node in root.findall("{*}si")]


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str | None:
    value = cell.find("{*}v")
    if value is None or value.text is None:
        inline = cell.find("{*}is/{*}t")
        return inline.text.strip() if inline is not None and inline.text else None
    if cell.attrib.get("t") == "s":
        index = int(value.text)
        return shared_strings[index].strip() if index < len(shared_strings) else None
    return value.text.strip()
