from app.services.canonical_key import normalize_key_part


def build_parsed_identity_key(
    *,
    brand_normalized: str | None,
    model_normalized: str | None,
    manufacturer_model_code: str | None,
    ram_gb: int | None,
    storage_gb: int | None,
    color_normalized: str | None,
    region_code: str | None,
) -> str | None:
    if not brand_normalized or not model_normalized:
        return None
    parts = [
        brand_normalized,
        model_normalized,
        manufacturer_model_code,
        f"{ram_gb}gb" if ram_gb is not None else None,
        f"{storage_gb}gb" if storage_gb is not None else None,
        color_normalized,
        region_code,
    ]
    return "|".join(normalize_key_part(part) for part in parts)
