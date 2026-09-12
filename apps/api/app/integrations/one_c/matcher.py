import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.one_c.types import OneCParsedRow
from app.models.enums import OneCItemMatchStatus, OneCItemMatchStrategy
from app.models.one_c import OneCItem
from app.models.product import Product, ProductAlias, ProductVariant


@dataclass(frozen=True)
class OneCMatchResult:
    status: OneCItemMatchStatus
    variant_id: object | None
    strategy: OneCItemMatchStrategy | None
    confidence: float | None


async def match_one_c_row(session: AsyncSession, row: OneCParsedRow, existing_item: OneCItem | None) -> OneCMatchResult:
    if existing_item and existing_item.explicit_mapping and existing_item.matched_variant_id:
        return OneCMatchResult(OneCItemMatchStatus.MATCHED, existing_item.matched_variant_id, OneCItemMatchStrategy.MANUAL, 1.0)

    for value, strategy in ((row.barcode, OneCItemMatchStrategy.BARCODE_EXACT), (row.sku, OneCItemMatchStrategy.SKU_EXACT)):
        if value:
            matched = await variants_for_alias(session, value)
            if len(matched) == 1:
                return OneCMatchResult(OneCItemMatchStatus.MATCHED, matched[0].id, strategy, 1.0)
            if len(matched) > 1:
                return OneCMatchResult(OneCItemMatchStatus.AMBIGUOUS, None, strategy, 0.90)

    model_code = extract_model_code(row.raw_name) or row.sku
    if model_code:
        variants = list(
            await session.scalars(
                select(ProductVariant).where(ProductVariant.manufacturer_model_code.ilike(model_code))
            )
        )
        if len(variants) == 1:
            return OneCMatchResult(OneCItemMatchStatus.MATCHED, variants[0].id, OneCItemMatchStrategy.MODEL_CODE_EXACT, 0.99)
        if len(variants) > 1:
            return OneCMatchResult(OneCItemMatchStatus.AMBIGUOUS, None, OneCItemMatchStrategy.MODEL_CODE_EXACT, 0.90)

    exact_name = list(
        await session.scalars(
            select(ProductVariant)
            .join(Product)
            .where(Product.canonical_name.ilike(row.normalized_name))
        )
    )
    if len(exact_name) == 1:
        return OneCMatchResult(OneCItemMatchStatus.MATCHED, exact_name[0].id, OneCItemMatchStrategy.NAME_EXACT, 0.98)
    if len(exact_name) > 1:
        return OneCMatchResult(OneCItemMatchStatus.AMBIGUOUS, None, OneCItemMatchStrategy.NAME_EXACT, 0.90)

    tokens = [token for token in re.split(r"\W+", row.normalized_name) if len(token) >= 3]
    candidates = list(await session.scalars(select(ProductVariant).join(Product)))
    scored = []
    for variant in candidates:
        product = await session.get(Product, variant.product_id)
        haystack = " ".join(
            str(part).lower()
            for part in (
                product.brand,
                product.canonical_name,
                variant.manufacturer_model_code,
                variant.ram_gb,
                variant.storage_gb,
                variant.color_normalized,
            )
            if part is not None
        )
        hits = sum(1 for token in tokens if token in haystack)
        confidence = hits / max(len(tokens), 1)
        if confidence >= 0.98:
            scored.append((variant, confidence))
    if len(scored) == 1:
        return OneCMatchResult(OneCItemMatchStatus.MATCHED, scored[0][0].id, OneCItemMatchStrategy.FUZZY_NAME, scored[0][1])
    if len(scored) > 1:
        return OneCMatchResult(OneCItemMatchStatus.AMBIGUOUS, None, OneCItemMatchStrategy.FUZZY_NAME, 0.90)
    return OneCMatchResult(OneCItemMatchStatus.UNMATCHED, None, None, None)


async def variants_for_alias(session: AsyncSession, value: str) -> list[ProductVariant]:
    normalized = value.strip().lower()
    aliases = list(
        await session.scalars(
            select(ProductAlias).where(ProductAlias.normalized_alias == normalized, ProductAlias.product_variant_id.is_not(None))
        )
    )
    variants = []
    seen = set()
    for alias in aliases:
        if alias.product_variant_id not in seen:
            variant = await session.get(ProductVariant, alias.product_variant_id)
            if variant:
                variants.append(variant)
                seen.add(alias.product_variant_id)
    return variants


def extract_model_code(value: str) -> str | None:
    match = re.search(r"\b([A-Z]{1,4}-?[A-Z]?\d{3,5}[A-Z]?)\b", value.upper())
    return match.group(1).replace("-", "") if match else None
