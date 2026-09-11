import re

from app.services.parser.text import normalize_lookup, normalize_spaces


def normalize_model(section: str | None, text: str) -> tuple[str | None, str | None, bool]:
    raw = normalize_spaces(text)
    raw = re.sub(r"^[^\w]+", "", raw, flags=re.UNICODE).strip()
    if not raw:
        return None, None, False
    lookup = normalize_lookup(raw)

    if section == "Apple":
        match = re.search(r"\b(?:iphone\s*)?(?P<num>1[0-9])\s+(?P<tier>pro\s+max|pro|plus)?\b", lookup)
        if match:
            tier = normalize_spaces(match.group("tier") or "")
            model = f"iPhone {match.group('num')}"
            if tier:
                model = f"{model} {tier.title()}"
            return raw, model.replace(" Pro Max", " Pro Max"), False

    if section == "Samsung":
        match = re.search(r"\b(?P<family>s)\s*(?P<num>\d{2})\s*(?P<tier>ultra|plus)?\b", lookup)
        if match:
            tier = match.group("tier")
            model = f"Galaxy S{match.group('num')}"
            if tier:
                model = f"{model} {tier.title()}"
            return raw, model, False

    if section in {"Xiaomi", "Redmi"}:
        if lookup.startswith("note "):
            return raw, normalize_spaces(raw).title().replace(" 5G", " 5G"), False
        if lookup.startswith("mi "):
            return raw, normalize_spaces(raw).title().replace(" 5G", " 5G"), False

    return raw, None, True


def normalize_brand(section: str | None, model_normalized: str | None) -> tuple[str | None, str | None]:
    if section == "Xiaomi" and model_normalized and model_normalized.startswith("Note "):
        return "Xiaomi", "Redmi"
    if section:
        return section, section
    return None, None

