from __future__ import annotations

from pathlib import Path

from app.integrations.avito_contract.parser import extract_template_fields
from app.integrations.avito_contract.types import AvitoFieldContract


def read_template_fields(paths: list[Path]) -> list[AvitoFieldContract]:
    return extract_template_fields(paths)
