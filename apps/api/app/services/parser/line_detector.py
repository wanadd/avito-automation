import re

from app.services.parser.constants import IGNORED_PATTERNS
from app.services.parser.prices import parse_price
from app.services.parser.text import normalize_lookup


PHONE_RE = re.compile(r"(?:\+?\d[\s\-()]*){9,}")
DATE_RE = re.compile(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b")


def is_ignored_line(line: str) -> bool:
    lookup = normalize_lookup(line)
    if not lookup:
        return True
    if any(pattern in lookup for pattern in IGNORED_PATTERNS):
        return True
    if PHONE_RE.fullmatch(lookup):
        return True
    if DATE_RE.fullmatch(lookup):
        return True
    return False


def classify_line(line: str, section: str | None) -> str:
    if is_ignored_line(line):
        return "ignored"
    _, price_minor, invalid_price = parse_price(line)
    has_digit = any(char.isdigit() for char in line)
    if price_minor is not None and has_digit:
        return "product"
    if invalid_price or (section is not None and has_digit):
        return "review"
    return "ignored"
