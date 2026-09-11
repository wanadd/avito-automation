import re

from app.services.parser.constants import COLOR_MAP
from app.services.parser.text import normalize_lookup


def extract_color(line: str) -> tuple[str | None, str | None]:
    lookup = normalize_lookup(line)
    for raw, normalized in sorted(COLOR_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(raw)}\b", lookup):
            return raw, normalized
    tokens = lookup.split()
    if tokens:
        tail = tokens[-1]
        if tail.isalpha() and len(tail) >= 3:
            return tail, None
    return None, None


def remove_color(line: str, color_raw: str | None) -> str:
    if color_raw is None:
        return line
    return re.sub(rf"\b{re.escape(color_raw)}\b", " ", line, flags=re.IGNORECASE)

