import re


PAIR_RE = re.compile(r"\b(?P<ram>4|6|8|10|12|16|18|24|32)\s*/\s*(?P<storage>64|128|256|512|1024|2048)\s*(?:gb|гб)?\b", re.IGNORECASE)
STORAGE_GB_RE = re.compile(r"\b(?P<storage>64|128|256|512|1024|2048)\s*(?:gb|гб)\b", re.IGNORECASE)
STORAGE_TB_RE = re.compile(r"\b(?P<storage>1|2)\s*(?:tb|тб)\b", re.IGNORECASE)


def parse_memory(line: str) -> tuple[int | None, int | None, str | None, bool]:
    pairs = list(PAIR_RE.finditer(line))
    if len(pairs) > 1:
        match = pairs[0]
        return int(match.group("ram")), int(match.group("storage")), match.group(0), True
    if pairs:
        match = pairs[0]
        return int(match.group("ram")), int(match.group("storage")), match.group(0), False

    tb = STORAGE_TB_RE.search(line)
    if tb:
        return None, int(tb.group("storage")) * 1024, tb.group(0), False

    gb = STORAGE_GB_RE.search(line)
    if gb:
        return None, int(gb.group("storage")), gb.group(0), False

    return None, None, None, False


def remove_memory(line: str) -> str:
    for pattern in (PAIR_RE, STORAGE_TB_RE, STORAGE_GB_RE):
        line = pattern.sub(" ", line)
    return line

