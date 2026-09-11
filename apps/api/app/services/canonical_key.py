import re

from app.models.enums import ProductCondition

NULL_TOKEN = "na"


def normalize_key_part(value: object | None) -> str:
    if value is None:
        return NULL_TOKEN
    normalized = re.sub(r"\s+", " ", str(value).strip().lower())
    return normalized if normalized else NULL_TOKEN


def build_canonical_key(
    *,
    brand: str,
    canonical_name: str,
    manufacturer_model_code: str | None,
    ram_gb: int | None,
    storage_gb: int | None,
    color_normalized: str | None,
    region_code: str | None,
    condition: ProductCondition | str,
) -> str:
    parts = [
        brand,
        canonical_name,
        manufacturer_model_code,
        f"{ram_gb}gb" if ram_gb is not None else None,
        f"{storage_gb}gb" if storage_gb is not None else None,
        color_normalized,
        region_code,
        condition.value if isinstance(condition, ProductCondition) else condition,
    ]
    return "|".join(normalize_key_part(part) for part in parts)

