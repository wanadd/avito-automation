import logging
import uuid
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.enums import Availability, MatchStatus, MatchStrategy, ParseStatus, ProductCondition, ReviewStatus
from app.models.match_review import MatchReview
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.product import Product, ProductAlias, ProductVariant
from app.models.supplier_offer import SupplierOffer
from app.schemas.matcher import MatchCandidate, MatchResult
from app.schemas.supplier_offer import SupplierOfferCreate
from app.services.canonical_key import build_canonical_key, normalize_key_part
from app.services.offers import upsert_supplier_offer

logger = logging.getLogger("app.matcher")

MATCH_AUTO_CREATE_THRESHOLD = Decimal("0.9800")
FUZZY_REVIEW_THRESHOLD = Decimal("0.7600")

CONFLICT_REASONS = {
    "brand": "BRAND_CONFLICT",
    "model": "MODEL_CONFLICT",
    "model_code": "MODEL_CODE_CONFLICT",
    "ram_gb": "RAM_CONFLICT",
    "storage_gb": "STORAGE_CONFLICT",
    "color_normalized": "COLOR_CONFLICT",
    "region_code": "REGION_CONFLICT",
    "condition": "CONDITION_CONFLICT",
}


def norm(value: object | None) -> str:
    return normalize_key_part(value)


def model_similarity(left: str | None, right: str | None) -> Decimal:
    if not left or not right:
        return Decimal("0.0000")
    return Decimal(str(SequenceMatcher(None, norm(left), norm(right)).ratio())).quantize(Decimal("0.0001"))


def effective_condition(item: ParsedSupplierItem, default_condition: ProductCondition | None = None) -> ProductCondition | None:
    return item.condition if item.condition is not None else default_condition


def variant_canonical_key(product: Product, item: ParsedSupplierItem) -> str:
    return build_canonical_key(
        brand=product.brand,
        canonical_name=product.canonical_name,
        manufacturer_model_code=item.manufacturer_model_code,
        ram_gb=item.ram_gb,
        storage_gb=item.storage_gb,
        color_normalized=item.color_normalized,
        region_code=item.region_code,
        condition=effective_condition(item),
    )


def candidate_score(item: ParsedSupplierItem, product: Product, variant: ProductVariant | None, reasons: list[str]) -> Decimal:
    score = Decimal("0.0000")
    if norm(product.brand) == norm(item.brand_normalized):
        score += Decimal("0.16")
    if norm(product.canonical_name) == norm(item.model_normalized):
        score += Decimal("0.20")
    if variant is None:
        return score
    if item.manufacturer_model_code and norm(variant.manufacturer_model_code) == norm(item.manufacturer_model_code):
        score += Decimal("0.18")
    if item.storage_gb is not None and variant.storage_gb == item.storage_gb:
        score += Decimal("0.14")
    if item.ram_gb is not None and variant.ram_gb == item.ram_gb:
        score += Decimal("0.10")
    if item.color_normalized and norm(variant.color_normalized) == norm(item.color_normalized):
        score += Decimal("0.08")
    if item.region_code and norm(variant.region_code) == norm(item.region_code):
        score += Decimal("0.08")
    if item.condition and variant.condition == item.condition:
        score += Decimal("0.06")
    if "ALIAS_EXACT" in reasons:
        score += Decimal("0.12")
    return min(score, Decimal("1.0000")).quantize(Decimal("0.0001"))


def attribute_conflicts(item: ParsedSupplierItem, product: Product, variant: ProductVariant) -> list[str]:
    conflicts: list[str] = []
    if item.brand_normalized and norm(product.brand) != norm(item.brand_normalized):
        conflicts.append(CONFLICT_REASONS["brand"])
    if item.model_normalized and norm(product.canonical_name) != norm(item.model_normalized):
        conflicts.append(CONFLICT_REASONS["model"])
    if item.manufacturer_model_code and variant.manufacturer_model_code and norm(variant.manufacturer_model_code) != norm(item.manufacturer_model_code):
        conflicts.append(CONFLICT_REASONS["model_code"])
    if item.ram_gb is not None and variant.ram_gb is not None and variant.ram_gb != item.ram_gb:
        conflicts.append(CONFLICT_REASONS["ram_gb"])
    if item.storage_gb is not None and variant.storage_gb is not None and variant.storage_gb != item.storage_gb:
        conflicts.append(CONFLICT_REASONS["storage_gb"])
    if item.color_normalized and variant.color_normalized and norm(variant.color_normalized) != norm(item.color_normalized):
        conflicts.append(CONFLICT_REASONS["color_normalized"])
    if item.region_code and variant.region_code and norm(variant.region_code) != norm(item.region_code):
        conflicts.append(CONFLICT_REASONS["region_code"])
    if item.condition is not None and variant.condition is not None and variant.condition != item.condition:
        conflicts.append(CONFLICT_REASONS["condition"])
    if item.condition is None and variant.condition is not None:
        conflicts.append("MISSING_CONDITION")
    if item.condition is not None and variant.condition is None:
        conflicts.append("MISSING_CONDITION")
    return conflicts


def exact_variant_attributes(item: ParsedSupplierItem, product: Product, variant: ProductVariant) -> bool:
    if norm(product.brand) != norm(item.brand_normalized) or norm(product.canonical_name) != norm(item.model_normalized):
        return False
    required_pairs = [(variant.storage_gb, item.storage_gb)]
    optional_pairs = [
        (variant.ram_gb, item.ram_gb),
        (variant.manufacturer_model_code, item.manufacturer_model_code),
        (variant.color_normalized, item.color_normalized),
        (variant.region_code, item.region_code),
    ]
    if any(left != right for left, right in required_pairs if left is not None and right is not None):
        return False
    if item.storage_gb is not None and variant.storage_gb != item.storage_gb:
        return False
    for left, right in optional_pairs:
        if right is not None and left != right:
            return False
    if item.region_code is not None and variant.region_code is None:
        return False
    if item.color_normalized is not None and variant.color_normalized is None:
        return False
    if item.condition is None and variant.condition is not None:
        return False
    if item.condition is not None and variant.condition != item.condition:
        return False
    return True


async def match_parsed_item(session: AsyncSession, parsed_item_id: uuid.UUID) -> MatchResult:
    item = await session.get(ParsedSupplierItem, parsed_item_id)
    if item is None:
        raise ValueError("ParsedSupplierItem not found")

    result = await _match_loaded_item(session, item)
    logger.info(
        "product_match",
        extra={
            "parsed_item_id": str(item.id),
            "strategy": result.strategy.value,
            "status": result.status.value,
            "candidate_count": result.candidate_count,
            "selected_variant_id": str(result.matched_variant_id) if result.matched_variant_id else None,
            "confidence": str(result.confidence),
            "reasons": result.reasons,
        },
    )
    return result


async def _match_loaded_item(session: AsyncSession, item: ParsedSupplierItem) -> MatchResult:
    blocking = blocking_reasons(item)
    if blocking:
        status = MatchStatus.CONFLICT_BLOCKED if "PRICE_CONFLICT" in blocking else MatchStatus.REVIEW
        strategy = MatchStrategy.PARSER_CONFLICT if status == MatchStatus.CONFLICT_BLOCKED else MatchStrategy.INSUFFICIENT_DATA
        result = MatchResult(
            parsed_item_id=item.id,
            status=status,
            confidence=item.parse_confidence,
            strategy=strategy,
            reasons=blocking,
            candidate_count=0,
            candidates=[],
        )
        if status == MatchStatus.REVIEW:
            await upsert_match_review(session, item, result)
        return result

    candidates = await collect_candidates(session, item)
    model_code_result = await try_model_code_exact(session, item, candidates)
    if model_code_result is not None:
        return model_code_result

    alias_result = await try_alias_exact(session, item)
    if alias_result is not None:
        return alias_result

    exact_candidates = [candidate for candidate in candidates if candidate.variant and exact_variant_attributes(item, candidate.product, candidate.variant)]
    if len(exact_candidates) == 1:
        return await finalize_match(session, item, exact_candidates[0], MatchStatus.EXACT_MATCH, MatchStrategy.ATTRIBUTES_EXACT, ["ATTRIBUTES_EXACT"])
    if len(exact_candidates) > 1:
        result = review_result(item, MatchStrategy.AMBIGUOUS, ["AMBIGUOUS_CANDIDATES"], exact_candidates)
        await upsert_match_review(session, item, result)
        return result

    fuzzy_candidates = [
        candidate for candidate in candidates if "FUZZY_MODEL" in candidate.reasons or candidate.score >= FUZZY_REVIEW_THRESHOLD
    ]
    if fuzzy_candidates:
        result = review_result(item, MatchStrategy.AMBIGUOUS, ["FUZZY_CANDIDATE_REVIEW"], fuzzy_candidates)
        await upsert_match_review(session, item, result)
        return result

    auto = await try_safe_auto_create(session, item, candidates)
    if auto is not None:
        return auto

    result = review_result(item, MatchStrategy.INSUFFICIENT_DATA, ["NO_SAFE_MATCH"], candidates)
    await upsert_match_review(session, item, result)
    return result


def blocking_reasons(item: ParsedSupplierItem) -> list[str]:
    reasons: list[str] = []
    if item.parse_status == ParseStatus.CONFLICT or "PRICE_CONFLICT" in item.parse_flags:
        reasons.append("PRICE_CONFLICT")
    if item.price_minor is None:
        reasons.append("MISSING_PRICE")
    if "INVALID_PRICE" in item.parse_flags:
        reasons.append("INVALID_PRICE")
    if item.parse_status == ParseStatus.IGNORED:
        reasons.append("IGNORED")
    return reasons


class Candidate:
    def __init__(self, product: Product, variant: ProductVariant | None, reasons: list[str]):
        self.product = product
        self.variant = variant
        self.reasons = reasons
        self.score = candidate_score_placeholder


candidate_score_placeholder = Decimal("0.0000")


async def collect_candidates(session: AsyncSession, item: ParsedSupplierItem) -> list[Candidate]:
    products = list(await session.scalars(select(Product).where(Product.is_active.is_(True))))
    variants = list(await session.scalars(select(ProductVariant).where(ProductVariant.is_active.is_(True))))
    product_by_id = {product.id: product for product in products}
    candidates: list[Candidate] = []

    for variant in variants:
        product = product_by_id[variant.product_id]
        reasons: list[str] = []
        if item.manufacturer_model_code and variant.manufacturer_model_code and norm(item.manufacturer_model_code) == norm(variant.manufacturer_model_code):
            reasons.append("MODEL_CODE_EXACT")
        if norm(product.brand) == norm(item.brand_normalized):
            reasons.append("BRAND_EXACT")
        if norm(product.canonical_name) == norm(item.model_normalized):
            reasons.append("MODEL_EXACT")
        sim = model_similarity(product.canonical_name, item.model_normalized or item.model_raw)
        if sim >= FUZZY_REVIEW_THRESHOLD and "MODEL_EXACT" not in reasons:
            reasons.append("FUZZY_MODEL")
        candidate = Candidate(product, variant, reasons)
        candidate.score = candidate_score(item, product, variant, reasons)
        if reasons or candidate.score >= Decimal("0.3000"):
            candidates.append(candidate)

    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


async def try_model_code_exact(session: AsyncSession, item: ParsedSupplierItem, candidates: list[Candidate]) -> MatchResult | None:
    if not item.manufacturer_model_code:
        return None
    code_matches = [candidate for candidate in candidates if "MODEL_CODE_EXACT" in candidate.reasons and candidate.variant is not None]
    if not code_matches:
        return None
    compatible: list[Candidate] = []
    conflict_reasons: list[str] = []
    for candidate in code_matches:
        conflicts = attribute_conflicts(item, candidate.product, candidate.variant)
        if conflicts:
            conflict_reasons.extend(conflicts)
        elif item.brand_normalized and norm(candidate.product.brand) == norm(item.brand_normalized):
            compatible.append(candidate)
    if len(compatible) == 1:
        return await finalize_match(session, item, compatible[0], MatchStatus.EXACT_MATCH, MatchStrategy.MODEL_CODE_EXACT, ["MODEL_CODE_EXACT"])
    result = review_result(item, MatchStrategy.MODEL_CODE_EXACT, sorted(set(conflict_reasons)) or ["MODEL_CODE_AMBIGUOUS"], code_matches)
    await upsert_match_review(session, item, result)
    return result


async def try_alias_exact(session: AsyncSession, item: ParsedSupplierItem) -> MatchResult | None:
    if not item.model_raw:
        return None
    aliases = list(
        await session.scalars(
            select(ProductAlias).where(
                ProductAlias.normalized_alias == norm(item.model_raw),
                or_(ProductAlias.source_id.is_(None), ProductAlias.source_id == item.source_id),
            )
        )
    )
    if not aliases:
        return None
    candidates: list[Candidate] = []
    for alias in aliases:
        if alias.product_variant_id:
            variant = await session.get(ProductVariant, alias.product_variant_id)
            if not variant:
                continue
            product = await session.get(Product, variant.product_id)
            if product and (not item.brand_normalized or norm(product.brand) == norm(item.brand_normalized)):
                candidates.append(Candidate(product, variant, ["ALIAS_EXACT"]))
        elif alias.product_id:
            product = await session.get(Product, alias.product_id)
            if not product or (item.brand_normalized and norm(product.brand) != norm(item.brand_normalized)):
                continue
            variants = list(await session.scalars(select(ProductVariant).where(ProductVariant.product_id == product.id)))
            exact = [variant for variant in variants if exact_variant_attributes(item, product, variant)]
            for variant in exact:
                candidates.append(Candidate(product, variant, ["ALIAS_EXACT"]))
    for candidate in candidates:
        candidate.score = candidate_score(item, candidate.product, candidate.variant, candidate.reasons)
    if len(candidates) == 1:
        return await finalize_match(session, item, candidates[0], MatchStatus.EXACT_MATCH, MatchStrategy.ALIAS_EXACT, ["ALIAS_EXACT"])
    if len(candidates) > 1:
        result = review_result(item, MatchStrategy.AMBIGUOUS, ["ALIAS_AMBIGUOUS"], candidates)
        await upsert_match_review(session, item, result)
        return result
    return None


async def try_safe_auto_create(session: AsyncSession, item: ParsedSupplierItem, candidates: list[Candidate]) -> MatchResult | None:
    if not auto_create_allowed(item):
        result = review_result(item, MatchStrategy.INSUFFICIENT_DATA, ["AUTO_CREATE_NOT_ALLOWED"], candidates)
        await upsert_match_review(session, item, result)
        return result
    if [candidate for candidate in candidates if candidate.score >= FUZZY_REVIEW_THRESHOLD]:
        result = review_result(item, MatchStrategy.AMBIGUOUS, ["SIMILAR_PRODUCT_REVIEW"], candidates)
        await upsert_match_review(session, item, result)
        return result

    product, created_product = await get_or_create_product(session, item)
    variant, created_variant = await get_or_create_variant(session, product, item)
    result = await finalize_match(
        session,
        item,
        Candidate(product, variant, ["AUTO_CREATE_SAFE"]),
        MatchStatus.AUTO_CREATED,
        MatchStrategy.AUTO_CREATE_SAFE,
        ["AUTO_CREATE_SAFE"],
        created_product=created_product,
        created_variant=created_variant,
    )
    if created_product:
        session.add(AuditLog(entity_type="Product", entity_id=product.id, action="PRODUCT_AUTO_CREATED", old_value=None, new_value={"brand": product.brand, "canonical_name": product.canonical_name}, actor_type="SYSTEM"))
    if created_variant:
        session.add(AuditLog(entity_type="ProductVariant", entity_id=variant.id, action="VARIANT_AUTO_CREATED", old_value=None, new_value={"canonical_key": variant.canonical_key}, actor_type="SYSTEM"))
    await session.commit()
    return result


def auto_create_allowed(item: ParsedSupplierItem) -> bool:
    return (
        item.parse_status in {ParseStatus.PARSED, ParseStatus.PARTIAL}
        and "PRICE_CONFLICT" not in item.parse_flags
        and item.brand_normalized is not None
        and item.model_normalized is not None
        and item.storage_gb is not None
        and item.price_minor is not None
        and item.parse_confidence >= MATCH_AUTO_CREATE_THRESHOLD
        and "AMBIGUOUS_MODEL" not in item.parse_flags
    )


async def get_or_create_product(session: AsyncSession, item: ParsedSupplierItem) -> tuple[Product, bool]:
    brand = item.brand_normalized
    canonical_name = item.model_normalized
    existing = await session.scalar(select(Product).where(Product.brand == brand, Product.canonical_name == canonical_name))
    if existing:
        return existing, False
    product = Product(brand=brand, canonical_name=canonical_name, category="smartphone")
    session.add(product)
    try:
        await session.flush()
        return product, True
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(select(Product).where(Product.brand == brand, Product.canonical_name == canonical_name))
        if existing is None:
            raise
        return existing, False


async def get_or_create_variant(session: AsyncSession, product: Product, item: ParsedSupplierItem) -> tuple[ProductVariant, bool]:
    canonical_key = variant_canonical_key(product, item)
    manufacturer_model_code = item.manufacturer_model_code
    ram_gb = item.ram_gb
    storage_gb = item.storage_gb
    color_raw = item.color_raw
    color_normalized = item.color_normalized
    region_code = item.region_code
    condition = effective_condition(item)
    existing = await session.scalar(select(ProductVariant).where(ProductVariant.canonical_key == canonical_key))
    if existing:
        return existing, False
    variant = ProductVariant(
        product_id=product.id,
        manufacturer_model_code=manufacturer_model_code,
        ram_gb=ram_gb,
        storage_gb=storage_gb,
        color_raw=color_raw,
        color_normalized=color_normalized,
        region_code=region_code,
        condition=condition,
        canonical_key=canonical_key,
    )
    session.add(variant)
    try:
        await session.flush()
        return variant, True
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(select(ProductVariant).where(ProductVariant.canonical_key == canonical_key))
        if existing is None:
            raise
        return existing, False


async def finalize_match(
    session: AsyncSession,
    item: ParsedSupplierItem,
    candidate: Candidate,
    status: MatchStatus,
    strategy: MatchStrategy,
    reasons: list[str],
    *,
    created_product: bool = False,
    created_variant: bool = False,
) -> MatchResult:
    supplier_sku = str(candidate.variant.id)
    existing_offer = await session.scalar(
        select(SupplierOffer).where(
            SupplierOffer.supplier_id == item.supplier_id,
            SupplierOffer.supplier_sku == supplier_sku,
        )
    )
    offer = await upsert_supplier_offer(
        session,
        SupplierOfferCreate(
            supplier_id=item.supplier_id,
            product_variant_id=candidate.variant.id,
            source_id=item.source_id,
            supplier_sku=supplier_sku,
            supplier_title=item.raw_line,
            price_minor=item.price_minor,
            currency=item.currency,
            availability=Availability.UNKNOWN,
            source_record_id=item.raw_source_record_id,
        ),
    )
    offer_created = existing_offer is None
    if offer_created:
        session.add(AuditLog(entity_type="SupplierOffer", entity_id=offer.id, action="SUPPLIER_OFFER_CREATED_BY_MATCH", old_value=None, new_value={"parsed_item_id": str(item.id)}, actor_type="SYSTEM"))
        await session.commit()
    return MatchResult(
        parsed_item_id=item.id,
        status=status,
        matched_product_id=candidate.product.id,
        matched_variant_id=candidate.variant.id,
        confidence=Decimal("1.0000") if status == MatchStatus.EXACT_MATCH else item.parse_confidence,
        strategy=strategy,
        reasons=reasons,
        candidate_count=1,
        candidates=[to_schema_candidate(candidate)],
        created_product=created_product,
        created_variant=created_variant,
        offer_created=offer_created,
        offer_updated=not offer_created,
    )


def review_result(item: ParsedSupplierItem, strategy: MatchStrategy, reasons: list[str], candidates: list[Candidate]) -> MatchResult:
    return MatchResult(
        parsed_item_id=item.id,
        status=MatchStatus.REVIEW,
        confidence=max([candidate.score for candidate in candidates], default=item.parse_confidence),
        strategy=strategy,
        reasons=reasons,
        candidate_count=len(candidates),
        candidates=[to_schema_candidate(candidate) for candidate in candidates[:10]],
    )


def to_schema_candidate(candidate: Candidate) -> MatchCandidate:
    return MatchCandidate(
        product_id=candidate.product.id,
        variant_id=candidate.variant.id if candidate.variant else None,
        score=candidate.score,
        reasons=candidate.reasons,
    )


async def upsert_match_review(session: AsyncSession, item: ParsedSupplierItem, result: MatchResult) -> None:
    existing = await session.scalar(
        select(MatchReview).where(MatchReview.parsed_item_id == item.id, MatchReview.status == ReviewStatus.PENDING)
    )
    candidate_variant_id = result.candidates[0].variant_id if result.candidates else None
    payload = {
        "reasons": result.reasons,
        "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
    }
    if existing is None:
        session.add(
            MatchReview(
                parsed_item_id=item.id,
                source_record_id=item.raw_source_record_id,
                candidate_variant_id=candidate_variant_id,
                confidence=result.confidence,
                status=ReviewStatus.PENDING,
                reason=";".join(result.reasons)[:1024],
                strategy=result.strategy.value,
                candidate_details=payload,
            )
        )
    else:
        existing.candidate_variant_id = candidate_variant_id
        existing.confidence = result.confidence
        existing.reason = ";".join(result.reasons)[:1024]
        existing.strategy = result.strategy.value
        existing.candidate_details = payload
    await session.commit()


async def match_raw_record(session: AsyncSession, raw_record_id: uuid.UUID) -> dict:
    items = list(
        await session.scalars(
            select(ParsedSupplierItem)
            .where(ParsedSupplierItem.raw_source_record_id == raw_record_id, ParsedSupplierItem.parse_status != ParseStatus.IGNORED)
            .order_by(ParsedSupplierItem.line_number)
        )
    )
    results: list[MatchResult] = []
    for item in items:
        results.append(await match_parsed_item(session, item.id))
    return {
        "raw_record_id": raw_record_id,
        "exact_match": sum(result.status == MatchStatus.EXACT_MATCH for result in results),
        "auto_created": sum(result.status == MatchStatus.AUTO_CREATED for result in results),
        "review": sum(result.status == MatchStatus.REVIEW for result in results),
        "rejected": sum(result.status == MatchStatus.REJECTED for result in results),
        "conflict_blocked": sum(result.status == MatchStatus.CONFLICT_BLOCKED for result in results),
        "offers_created": sum(result.offer_created for result in results),
        "offers_updated": sum(result.offer_updated for result in results),
        "results": results,
    }
