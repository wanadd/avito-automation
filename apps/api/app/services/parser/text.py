import re


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def normalize_lookup(value: str) -> str:
    return normalize_spaces(value).casefold()


def tokenize_lines(raw_text: str) -> list[tuple[int, str]]:
    return [(index, line.rstrip()) for index, line in enumerate(raw_text.splitlines(), start=1)]

