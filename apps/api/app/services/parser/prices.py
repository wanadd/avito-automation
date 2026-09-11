import re


PRICE_PATTERNS = (
    re.compile(r"(?:[-—–]\s*)(?P<price>\d{1,3}(?:[ .]\d{3})+|\d{4,7})(?:\s*₽)?(?:\b|$)"),
    re.compile(r"\b(?P<price>\d{1,3}(?:[ .]\d{3})+|\d{4,7})\s*₽\b"),
)


def parse_price(line: str) -> tuple[int | None, str | None, bool]:
    if re.search(r"[-—–]\s*-+\d", line):
        return None, None, True

    for pattern in PRICE_PATTERNS:
        match = pattern.search(line)
        if not match:
            continue
        raw_price = match.group("price")
        major = int(raw_price.replace(" ", "").replace(".", ""))
        if major <= 0:
            return raw_price, None, True
        return raw_price, major * 100, False
    return None, None, False


def remove_price(line: str) -> str:
    without = line
    for pattern in PRICE_PATTERNS:
        without = pattern.sub(" ", without)
    return without

