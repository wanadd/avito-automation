import re

from app.services.parser.constants import KNOWN_SECTIONS
from app.services.parser.text import normalize_lookup, normalize_spaces
from app.services.parser.types import SectionContext


def strip_emoji_and_symbols(value: str) -> str:
    return re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)


def detect_section(line: str) -> SectionContext | None:
    cleaned = normalize_lookup(strip_emoji_and_symbols(line))
    if not cleaned:
        return None
    words = cleaned.split()
    if len(words) > 3:
        return None
    for word in words:
        if word in KNOWN_SECTIONS:
            return SectionContext(raw=normalize_spaces(line), normalized=KNOWN_SECTIONS[word])
    return None

