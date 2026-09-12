from __future__ import annotations

from pathlib import Path

from app.integrations.avito_contract.parser import text_from_html


def read_public_doc_text(path: Path) -> str:
    return text_from_html(path)
