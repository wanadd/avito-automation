import re


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_optional(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
