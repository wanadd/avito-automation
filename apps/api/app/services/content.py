import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit_log import AuditLog
from app.models.content import (
    GenericListingDraft,
    ProductContentDraft,
    ProductContentFacts,
    ProductFactOverride,
    ProductImageAsset,
    ProductImageSet,
    ProductImageSetItem,
)
from app.models.enums import (
    ContentDraftStatus,
    ContentFactConfidence,
    ContentFactSource,
    ContentValidationStatus,
    FulfillmentSource,
    GenericCategory,
    GenericListingStatus,
    GenericReadinessStatus,
    ImageAssetSourceType,
    ImageAssetStatus,
    ImageSetStatus,
    ListingReadinessReason,
    MarketplaceReadinessStatus,
    PricingReasonCode,
    StockDecision,
)
from app.models.pricing import VariantPricingState
from app.models.product import Product, ProductVariant

CONTENT_PROMPT_V1 = "CONTENT_PROMPT_V1"
DETERMINISTIC_GENERATOR_VERSION = "deterministic-v1"
GENERIC_TITLE_SOFT_LIMIT = 120
FACT_FIELDS = ("brand", "model", "model_code", "ram", "storage", "color", "region", "condition")
MANUAL_OVERRIDE_FIELDS = FACT_FIELDS + ("warranty_text", "package_contents")
SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


@dataclass(frozen=True)
class GeneratedContent:
    title: str
    description: str


class ContentGenerationProvider:
    name = "base"
    version = "base"
    prompt_version = CONTENT_PROMPT_V1

    def generate_content(self, facts: ProductContentFacts) -> GeneratedContent:
        raise NotImplementedError

    def generate_title(self, facts: ProductContentFacts) -> str:
        return self.generate_content(facts).title

    def generate_description(self, facts: ProductContentFacts) -> str:
        return self.generate_content(facts).description


class DeterministicContentProvider(ContentGenerationProvider):
    name = "DETERMINISTIC"
    version = DETERMINISTIC_GENERATOR_VERSION

    def generate_content(self, facts: ProductContentFacts) -> GeneratedContent:
        title = build_title(facts)
        description = build_description(facts)
        return GeneratedContent(title=title, description=description)


class LLMContentProvider(ContentGenerationProvider):
    name = "LLM_OPTIONAL"
    version = "unconfigured"

    def generate_content(self, facts: ProductContentFacts) -> GeneratedContent:
        raise RuntimeError("LLM content provider is optional and is not configured")


def stable_hash(payload: dict | list) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def fact_source(field: str, value, source: ContentFactSource, source_id: str | None, confidence: ContentFactConfidence = ContentFactConfidence.CONFIRMED) -> dict:
    return {
        "field": field,
        "value": value.value if hasattr(value, "value") else value,
        "source": source.value,
        "source_id": source_id,
        "confidence": confidence.value,
    }


async def rebuild_content_facts(session: AsyncSession, variant_id: uuid.UUID) -> ProductContentFacts:
    variant = await session.get(ProductVariant, variant_id)
    if variant is None:
        raise ValueError("ProductVariant not found")
    product = await session.get(Product, variant.product_id)
    overrides = {
        override.field: override
        for override in await session.scalars(select(ProductFactOverride).where(ProductFactOverride.variant_id == variant_id))
    }
    facts_payload, sources, conflicts = build_fact_payload(product, variant, overrides)
    fact_hash = stable_hash(facts_payload)
    existing = await session.scalar(
        select(ProductContentFacts).where(ProductContentFacts.variant_id == variant_id, ProductContentFacts.fact_hash == fact_hash)
    )
    if existing is not None:
        return existing

    previous = await latest_facts(session, variant_id)
    facts = ProductContentFacts(
        variant_id=variant_id,
        fact_hash=fact_hash,
        fact_sources=sources,
        has_conflicts=bool(conflicts),
        requires_review=bool(conflicts),
        completeness_score=completeness_score(facts_payload),
        **facts_payload,
    )
    session.add(facts)
    if previous is None:
        audit_action = "FACTS_BUILT"
        old_value = None
    else:
        audit_action = "FACTS_CHANGED" if previous.fact_hash != fact_hash else "FACTS_BUILT"
        old_value = {"fact_hash": previous.fact_hash}
    session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action=audit_action, old_value=old_value, new_value={"fact_hash": fact_hash}, actor_type="SYSTEM"))
    for conflict in conflicts:
        session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action="FACT_CONFLICT", old_value=None, new_value=conflict, actor_type="SYSTEM"))
    await supersede_stale_content(session, variant_id, fact_hash)
    await session.commit()
    await session.refresh(facts)
    return facts


def build_fact_payload(product: Product, variant: ProductVariant, overrides: dict[str, ProductFactOverride]) -> tuple[dict, list[dict], list[dict]]:
    sources: list[dict] = []
    conflicts: list[dict] = []
    values = {
        "brand": product.brand,
        "model": product.canonical_name,
        "model_code": variant.manufacturer_model_code,
        "ram": f"{variant.ram_gb}GB" if variant.ram_gb is not None else None,
        "storage": f"{variant.storage_gb}GB" if variant.storage_gb is not None else None,
        "color": variant.color_raw or variant.color_normalized,
        "region": variant.region_code,
        "condition": variant.condition,
    }
    for field, value in list(values.items()):
        source = ContentFactSource.PRODUCT if field in {"brand", "model"} else ContentFactSource.PRODUCT_VARIANT
        if value is not None:
            sources.append(fact_source(field, value, source, str(product.id if source == ContentFactSource.PRODUCT else variant.id)))
    warranty_status = "UNKNOWN"
    warranty_text = None
    package_contents_status = "UNKNOWN"
    package_contents: list[str] = []
    for field, override in overrides.items():
        if field not in MANUAL_OVERRIDE_FIELDS:
            continue
        old_value = values.get(field)
        new_value = override.value
        if field == "package_contents":
            package_contents = [item.strip() for item in new_value.split(",") if item.strip()]
            package_contents_status = "KNOWN" if package_contents else "UNKNOWN"
            sources.append(fact_source(field, package_contents, ContentFactSource.MANUAL, str(override.id)))
        elif field == "warranty_text":
            warranty_text = new_value
            warranty_status = "KNOWN"
            sources.append(fact_source(field, new_value, ContentFactSource.MANUAL, str(override.id)))
        else:
            if old_value is not None and str(old_value.value if hasattr(old_value, "value") else old_value).lower() != new_value.lower():
                conflicts.append({"field": field, "higher_trust_value": str(old_value), "manual_value": new_value, "reason": "MANUAL_IDENTITY_CHANGE_REQUIRES_REVIEW"})
            values[field] = new_value
            sources.append(fact_source(field, new_value, ContentFactSource.MANUAL, str(override.id)))
    known_attributes = {key: (value.value if hasattr(value, "value") else value) for key, value in values.items() if value is not None}
    canonical_variant_name = " ".join(str(known_attributes[key]) for key in ("brand", "model", "model_code", "ram", "storage", "color") if key in known_attributes)
    return (
        {
            **values,
            "canonical_product_name": product.canonical_name,
            "canonical_variant_name": canonical_variant_name or None,
            "known_attributes": known_attributes,
            "warranty_status": warranty_status,
            "warranty_text": warranty_text,
            "package_contents_status": package_contents_status,
            "package_contents": package_contents,
            "additional_facts": {"fact_state": fact_state(values, warranty_status, package_contents_status), "conflicts": conflicts},
        },
        sources,
        conflicts,
    )


def fact_state(values: dict, warranty_status: str, package_contents_status: str) -> dict:
    state = {field: ("KNOWN" if values.get(field) is not None else "UNKNOWN") for field in FACT_FIELDS}
    state["warranty"] = warranty_status
    state["package_contents"] = package_contents_status
    return state


def completeness_score(payload: dict) -> int:
    known = sum(1 for field in FACT_FIELDS if payload.get(field) is not None)
    return int(known / len(FACT_FIELDS) * 100)


async def latest_facts(session: AsyncSession, variant_id: uuid.UUID) -> ProductContentFacts | None:
    return await session.scalar(
        select(ProductContentFacts).where(ProductContentFacts.variant_id == variant_id).order_by(ProductContentFacts.created_at.desc(), ProductContentFacts.id.desc()).limit(1)
    )


async def set_manual_fact_override(session: AsyncSession, variant_id: uuid.UUID, field: str, value: str, operator: str, reason: str | None = None) -> ProductFactOverride:
    if field not in MANUAL_OVERRIDE_FIELDS:
        raise ValueError("Unsupported manual fact field")
    if await session.get(ProductVariant, variant_id) is None:
        raise ValueError("ProductVariant not found")
    override = await session.scalar(select(ProductFactOverride).where(ProductFactOverride.variant_id == variant_id, ProductFactOverride.field == field))
    old_value = None
    if override is None:
        override = ProductFactOverride(variant_id=variant_id, field=field, value=value, operator=operator, reason=reason)
    else:
        old_value = {"value": override.value, "reason": override.reason}
        override.value = value
        override.operator = operator
        override.reason = reason
    session.add(override)
    await session.flush()
    session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action="FACT_OVERRIDE_SET", old_value=old_value, new_value={"field": field, "value": value, "operator": operator, "reason": reason}, actor_type="USER", actor_id=operator))
    await session.commit()
    await session.refresh(override)
    return override


def build_title(facts: ProductContentFacts) -> str:
    parts = [facts.brand, facts.model, facts.model_code]
    memory = "/".join(part for part in (facts.ram, facts.storage) if part)
    if memory:
        parts.append(memory)
    parts.append(facts.color)
    title = " ".join(part for part in parts if part)
    if len(title) <= GENERIC_TITLE_SOFT_LIMIT:
        return title
    required = [facts.brand, facts.model, facts.model_code, memory]
    return " ".join(part for part in required if part)


def build_description(facts: ProductContentFacts) -> str:
    lines = []
    identity = " ".join(part for part in (facts.brand, facts.model, facts.model_code) if part)
    if identity:
        lines.append(identity)
    specs = []
    for label, value in (("RAM", facts.ram), ("Storage", facts.storage), ("Color", facts.color), ("Region", facts.region), ("Condition", facts.condition.value if facts.condition else None)):
        if value:
            specs.append(f"{label}: {value}")
    if specs:
        lines.extend(specs)
    if facts.warranty_status == "KNOWN" and facts.warranty_text:
        lines.append(f"Warranty: {facts.warranty_text}")
    if facts.package_contents_status == "KNOWN" and facts.package_contents:
        lines.append("Package: " + ", ".join(facts.package_contents))
    return "\n".join(lines)


async def generate_content_draft(session: AsyncSession, variant_id: uuid.UUID, provider: ContentGenerationProvider | None = None) -> ProductContentDraft:
    facts = await latest_facts(session, variant_id) or await rebuild_content_facts(session, variant_id)
    provider = provider or DeterministicContentProvider()
    generated = provider.generate_content(facts)
    content_hash = stable_hash({"title": generated.title, "description": generated.description, "input_fact_hash": facts.fact_hash, "provider": provider.name, "prompt_version": provider.prompt_version})
    existing = await session.scalar(
        select(ProductContentDraft).where(
            ProductContentDraft.variant_id == variant_id,
            ProductContentDraft.input_fact_hash == facts.fact_hash,
            ProductContentDraft.content_hash == content_hash,
        )
    )
    if existing is not None:
        return existing
    draft = ProductContentDraft(
        variant_id=variant_id,
        facts_id=facts.id,
        status=ContentDraftStatus.GENERATED,
        title=generated.title,
        description=generated.description,
        title_generation_mode="DETERMINISTIC",
        description_generation_mode="DETERMINISTIC",
        generator=provider.name,
        generator_version=provider.version,
        prompt_version=provider.prompt_version,
        input_fact_hash=facts.fact_hash,
        content_hash=content_hash,
        validation_status=ContentValidationStatus.NOT_VALIDATED,
        created_by="SYSTEM",
    )
    session.add(draft)
    session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action="CONTENT_GENERATED", old_value=None, new_value={"content_hash": content_hash}, actor_type="SYSTEM"))
    await session.commit()
    await session.refresh(draft)
    return draft


async def validate_content_draft(session: AsyncSession, draft_id: uuid.UUID) -> ProductContentDraft:
    draft = await session.get(ProductContentDraft, draft_id)
    if draft is None:
        raise ValueError("ProductContentDraft not found")
    facts = await session.get(ProductContentFacts, draft.facts_id)
    errors, warnings = validate_copy_claims(f"{draft.title}\n{draft.description}", facts)
    draft.validation_errors = errors
    draft.validation_warnings = warnings
    draft.validation_status = ContentValidationStatus.INVALID if errors else ContentValidationStatus.VALID
    draft.status = ContentDraftStatus.REVIEW_REQUIRED if errors else ContentDraftStatus.VALID
    draft.requires_review = bool(errors or facts.requires_review)
    session.add(AuditLog(entity_type="ProductContentDraft", entity_id=draft.id, action="CONTENT_VALIDATED", old_value=None, new_value={"status": draft.validation_status.value, "errors": errors}, actor_type="SYSTEM"))
    await session.commit()
    await session.refresh(draft)
    return draft


def validate_copy_claims(text: str, facts: ProductContentFacts) -> tuple[list[dict], list[dict]]:
    normalized = text.lower()
    errors: list[dict] = []
    known_values = {
        "brand": facts.brand,
        "model": facts.model,
        "model_code": facts.model_code,
        "ram": facts.ram,
        "storage": facts.storage,
        "color": facts.color,
        "region": facts.region,
        "condition": facts.condition.value if facts.condition else None,
        "warranty": facts.warranty_text,
        "package_contents": ", ".join(facts.package_contents) if facts.package_contents else None,
    }
    for field, value in known_values.items():
        if value and value.lower() not in normalized and field in {"brand", "model", "storage", "color"}:
            continue
    if facts.storage:
        for match in re.findall(r"\b(\d{2,4})\s*(?:gb|гб)\b", normalized):
            token = f"{match}GB"
            if token.lower() != facts.storage.lower() and (facts.ram is None or token.lower() != facts.ram.lower()):
                errors.append({"code": "FACT_CONTRADICTION", "field": "storage", "value": token, "expected": facts.storage})
    color_tokens = ("silverblue", "black", "blue", "white", "green")
    if facts.color and any(re.search(rf"\b{re.escape(color)}\b", normalized) for color in color_tokens):
        known = facts.color.lower()
        for color in color_tokens:
            if re.search(rf"\b{re.escape(color)}\b", normalized) and color != known:
                errors.append({"code": "FACT_CONTRADICTION", "field": "color", "value": color, "expected": facts.color})
    forbidden = (
        (r"официальн\w*\s+гаранти\w*", "UNSUPPORTED_WARRANTY_CLAIM", "официальная гарантия"),
        (r"гаранти\w*\s+производител\w*", "UNSUPPORTED_WARRANTY_CLAIM", "гарантия производителя"),
        (r"100%\s*оригинал", "UNSUPPORTED_AUTHENTICITY_CLAIM", "100% оригинал"),
        (r"\bоригиналь\w*\b", "UNSUPPORTED_AUTHENTICITY_CLAIM", "оригинальный"),
        (r"\bнов(ый|ая|ое|ые)\b", "UNSUPPORTED_CONDITION_CLAIM", "новый"),
        (r"\bnew\b", "UNSUPPORTED_CONDITION_CLAIM", "new"),
        (r"не\s+вскрывал\w*", "UNSUPPORTED_CONDITION_CLAIM", "не вскрывался"),
        (r"не\s+активирован\w*", "UNSUPPORTED_CONDITION_CLAIM", "не активирован"),
        (r"\bростест\b", "UNSUPPORTED_CERTIFICATION_CLAIM", "Ростест"),
        (r"\beac\b", "UNSUPPORTED_CERTIFICATION_CLAIM", "EAC"),
        (r"идеальн\w*\s+состояни\w*", "UNSUPPORTED_CONDITION_CLAIM", "идеальное состояние"),
        (r"полн\w*\s+комплект", "UNSUPPORTED_PACKAGE_CLAIM", "полный комплект"),
        (r"в\s+наличии", "UNSUPPORTED_AVAILABILITY_CLAIM", "в наличии"),
        (r"доставка\s+сегодня", "UNSUPPORTED_DELIVERY_CLAIM", "доставка сегодня"),
    )
    for pattern, code, claim in forbidden:
        if re.search(pattern, normalized):
            if code == "UNSUPPORTED_CONDITION_CLAIM" and facts.condition is not None:
                continue
            if code == "UNSUPPORTED_WARRANTY_CLAIM" and facts.warranty_status == "KNOWN":
                continue
            if code == "UNSUPPORTED_PACKAGE_CLAIM" and facts.package_contents_status == "KNOWN":
                continue
            errors.append({"code": code, "claim": claim})
    return errors, []


async def approve_content_draft(session: AsyncSession, draft_id: uuid.UUID) -> ProductContentDraft:
    draft = await session.get(ProductContentDraft, draft_id)
    if draft is None:
        raise ValueError("ProductContentDraft not found")
    current_facts = await latest_facts(session, draft.variant_id)
    if current_facts is None or current_facts.fact_hash != draft.input_fact_hash:
        raise ValueError("STALE_FACTS")
    if draft.validation_status != ContentValidationStatus.VALID:
        raise ValueError("CONTENT_INVALID")
    draft.status = ContentDraftStatus.APPROVED
    draft.approved_at = datetime.now(UTC)
    draft.requires_review = False
    session.add(AuditLog(entity_type="ProductContentDraft", entity_id=draft.id, action="CONTENT_APPROVED", old_value=None, new_value={"content_hash": draft.content_hash}, actor_type="USER"))
    await session.commit()
    await session.refresh(draft)
    return draft


async def reject_content_draft(session: AsyncSession, draft_id: uuid.UUID, reason: str | None = None) -> ProductContentDraft:
    draft = await session.get(ProductContentDraft, draft_id)
    if draft is None:
        raise ValueError("ProductContentDraft not found")
    draft.status = ContentDraftStatus.REJECTED
    draft.rejected_at = datetime.now(UTC)
    draft.rejection_reason = reason
    session.add(AuditLog(entity_type="ProductContentDraft", entity_id=draft.id, action="CONTENT_REJECTED", old_value=None, new_value={"reason": reason}, actor_type="USER"))
    await session.commit()
    await session.refresh(draft)
    return draft


async def supersede_stale_content(session: AsyncSession, variant_id: uuid.UUID, current_fact_hash: str) -> None:
    drafts = list(await session.scalars(select(ProductContentDraft).where(ProductContentDraft.variant_id == variant_id, ProductContentDraft.input_fact_hash != current_fact_hash, ProductContentDraft.status == ContentDraftStatus.APPROVED)))
    for draft in drafts:
        draft.status = ContentDraftStatus.SUPERSEDED
        draft.requires_review = True
        session.add(AuditLog(entity_type="ProductContentDraft", entity_id=draft.id, action="LISTING_STALE", old_value={"status": "APPROVED"}, new_value={"reason": "FACTS_CHANGED"}, actor_type="SYSTEM"))
    listings = list(await session.scalars(select(GenericListingDraft).where(GenericListingDraft.variant_id == variant_id, GenericListingDraft.generic_readiness.in_([GenericReadinessStatus.READY, GenericReadinessStatus.APPROVED]))))
    for listing in listings:
        listing.generic_readiness = GenericReadinessStatus.STALE
        listing.status = GenericListingStatus.STALE
        listing.readiness_reasons = sorted(set(listing.readiness_reasons + [ListingReadinessReason.FACTS_CHANGED.value]))


async def create_image_asset(session: AsyncSession, variant_id: uuid.UUID, *, source_type: ImageAssetSourceType, sha256: str, mime_type: str, size_bytes: int, width: int | None = None, height: int | None = None, storage_path: str | None = None, source_reference: str | None = None, original_filename: str | None = None, sort_order: int = 0) -> ProductImageAsset:
    if await session.get(ProductVariant, variant_id) is None:
        raise ValueError("ProductVariant not found")
    existing = await session.scalar(select(ProductImageAsset).where(ProductImageAsset.variant_id == variant_id, ProductImageAsset.sha256 == sha256))
    if existing is not None:
        return existing
    status = ImageAssetStatus.READY
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES or size_bytes <= 0:
        status = ImageAssetStatus.INVALID
    if storage_path and not Path(storage_path).exists():
        status = ImageAssetStatus.INVALID
    asset = ProductImageAsset(variant_id=variant_id, source_type=source_type, source_reference=source_reference, storage_path=storage_path, original_filename=original_filename, mime_type=mime_type, width=width, height=height, size_bytes=size_bytes, sha256=sha256, sort_order=sort_order, status=status)
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


async def create_image_set(session: AsyncSession, variant_id: uuid.UUID, image_asset_ids: list[uuid.UUID], cover_image_id: uuid.UUID | None = None) -> ProductImageSet:
    assets = list(await session.scalars(select(ProductImageAsset).where(ProductImageAsset.id.in_(image_asset_ids), ProductImageAsset.variant_id == variant_id).order_by(ProductImageAsset.sort_order, ProductImageAsset.created_at)))
    if len(assets) != len(set(image_asset_ids)):
        raise ValueError("IMAGE_SET_INVALID")
    ordered_ids = [str(asset.id) for asset in assets]
    cover = cover_image_id or (assets[0].id if assets else None)
    content_hash = stable_hash({"variant_id": str(variant_id), "image_ids": ordered_ids, "cover_image_id": str(cover) if cover else None})
    existing = await session.scalar(select(ProductImageSet).where(ProductImageSet.variant_id == variant_id, ProductImageSet.content_hash == content_hash).options(selectinload(ProductImageSet.items)))
    if existing is not None:
        return existing
    image_set = ProductImageSet(variant_id=variant_id, status=ImageSetStatus.DRAFT, cover_image_id=cover, content_hash=content_hash)
    session.add(image_set)
    await session.flush()
    for index, asset in enumerate(assets):
        session.add(ProductImageSetItem(image_set_id=image_set.id, image_asset_id=asset.id, sort_order=index))
    session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action="IMAGE_SET_CREATED", old_value=None, new_value={"content_hash": content_hash}, actor_type="SYSTEM"))
    await session.commit()
    await session.refresh(image_set)
    return image_set


async def validate_image_set(session: AsyncSession, image_set_id: uuid.UUID) -> ProductImageSet:
    image_set = await session.scalar(select(ProductImageSet).where(ProductImageSet.id == image_set_id).options(selectinload(ProductImageSet.items).selectinload(ProductImageSetItem.image_asset)))
    if image_set is None:
        raise ValueError("ProductImageSet not found")
    errors = []
    if not image_set.items:
        errors.append("NO_IMAGES")
    asset_ids = {item.image_asset_id for item in image_set.items}
    if image_set.cover_image_id and image_set.cover_image_id not in asset_ids:
        errors.append("COVER_NOT_IN_SET")
    seen_sha = set()
    for item in sorted(image_set.items, key=lambda row: row.sort_order):
        asset = item.image_asset
        if asset.status != ImageAssetStatus.READY:
            errors.append("IMAGE_INVALID")
        if asset.sha256 in seen_sha:
            errors.append("DUPLICATE_SHA")
        seen_sha.add(asset.sha256)
    image_set.status = ImageSetStatus.REVIEW_REQUIRED if errors else ImageSetStatus.READY
    session.add(AuditLog(entity_type="ProductImageSet", entity_id=image_set.id, action="IMAGE_SET_VALIDATED", old_value=None, new_value={"status": image_set.status.value, "errors": errors}, actor_type="SYSTEM"))
    await session.commit()
    await session.refresh(image_set)
    return image_set


async def approve_image_set(session: AsyncSession, image_set_id: uuid.UUID) -> ProductImageSet:
    image_set = await session.get(ProductImageSet, image_set_id)
    if image_set is None:
        raise ValueError("ProductImageSet not found")
    if image_set.status != ImageSetStatus.READY:
        raise ValueError("IMAGE_SET_INVALID")
    image_set.status = ImageSetStatus.APPROVED
    image_set.approved_at = datetime.now(UTC)
    session.add(AuditLog(entity_type="ProductImageSet", entity_id=image_set.id, action="IMAGE_SET_APPROVED", old_value=None, new_value={"content_hash": image_set.content_hash}, actor_type="USER"))
    await session.commit()
    await session.refresh(image_set)
    return image_set


async def build_generic_listing(session: AsyncSession, variant_id: uuid.UUID) -> GenericListingDraft:
    content = await latest_approved_content(session, variant_id)
    image_set = await latest_approved_image_set(session, variant_id)
    pricing = await session.get(VariantPricingState, variant_id)
    facts = await latest_facts(session, variant_id)
    readiness, reasons = evaluate_readiness(content, image_set, pricing, facts)
    content_hash = stable_hash(
        {
            "variant_id": str(variant_id),
            "content_draft_id": str(content.id) if content else None,
            "image_set_id": str(image_set.id) if image_set else None,
            "pricing": pricing_snapshot(pricing),
            "generic_readiness": readiness.value,
            "reasons": sorted(reasons),
        }
    )
    existing = await session.scalar(select(GenericListingDraft).where(GenericListingDraft.variant_id == variant_id, GenericListingDraft.content_hash == content_hash))
    if existing is not None:
        return existing
    listing = GenericListingDraft(
        variant_id=variant_id,
        content_draft_id=content.id if content else None,
        image_set_id=image_set.id if image_set else None,
        pricing_state_id=pricing.product_variant_id if pricing else None,
        status=listing_status_for(readiness),
        generic_category=classify_category(facts),
        generic_attributes=facts.known_attributes if facts else {},
        title=content.title if content else None,
        description=content.description if content else None,
        price_minor=pricing.final_price_minor if pricing else None,
        stock_decision=pricing.stock_decision.value if pricing else None,
        fulfillment_source=pricing.fulfillment_source.value if pricing else None,
        generic_readiness=readiness,
        avito_readiness=MarketplaceReadinessStatus.DISABLED_CONTRACT_INCOMPLETE,
        readiness_reasons=sorted(reasons),
        content_hash=content_hash,
    )
    session.add(listing)
    await session.flush()
    session.add(AuditLog(entity_type="ProductVariant", entity_id=variant_id, action="LISTING_BUILT", old_value=None, new_value={"content_hash": content_hash, "generic_readiness": readiness.value}, actor_type="SYSTEM"))
    if readiness == GenericReadinessStatus.READY:
        session.add(AuditLog(entity_type="GenericListingDraft", entity_id=listing.id, action="LISTING_READY", old_value=None, new_value={"avito_readiness": MarketplaceReadinessStatus.DISABLED_CONTRACT_INCOMPLETE.value}, actor_type="SYSTEM"))
    await session.commit()
    await session.refresh(listing)
    return listing


async def validate_listing(session: AsyncSession, listing_id: uuid.UUID) -> GenericListingDraft:
    listing = await session.get(GenericListingDraft, listing_id)
    if listing is None:
        raise ValueError("GenericListingDraft not found")
    rebuilt = await build_generic_listing(session, listing.variant_id)
    if rebuilt.content_hash != listing.content_hash:
        listing.generic_readiness = GenericReadinessStatus.STALE
        listing.status = GenericListingStatus.STALE
        listing.readiness_reasons = sorted(set(listing.readiness_reasons + [ListingReadinessReason.FACTS_CHANGED.value]))
        await session.commit()
        await session.refresh(listing)
    return listing


async def approve_listing(session: AsyncSession, listing_id: uuid.UUID) -> GenericListingDraft:
    listing = await validate_listing(session, listing_id)
    if listing.generic_readiness != GenericReadinessStatus.READY:
        raise ValueError("PRICING_NOT_READY")
    listing.generic_readiness = GenericReadinessStatus.APPROVED
    listing.status = GenericListingStatus.APPROVED
    listing.approved_at = datetime.now(UTC)
    session.add(AuditLog(entity_type="GenericListingDraft", entity_id=listing.id, action="LISTING_APPROVED", old_value=None, new_value={"content_hash": listing.content_hash}, actor_type="USER"))
    await session.commit()
    await session.refresh(listing)
    return listing


def evaluate_readiness(content: ProductContentDraft | None, image_set: ProductImageSet | None, pricing: VariantPricingState | None, facts: ProductContentFacts | None) -> tuple[GenericReadinessStatus, list[str]]:
    reasons: list[str] = []
    if facts and facts.has_conflicts:
        reasons.append(ListingReadinessReason.FACT_CONFLICT.value)
    if facts and facts.condition is None:
        reasons.append(ListingReadinessReason.UNKNOWN_CONDITION.value)
    if content is None:
        reasons.append(ListingReadinessReason.MISSING_CONTENT.value)
    elif content.status != ContentDraftStatus.APPROVED or content.validation_status != ContentValidationStatus.VALID:
        reasons.append(ListingReadinessReason.CONTENT_NOT_APPROVED.value)
    if image_set is None:
        reasons.append(ListingReadinessReason.NO_IMAGES.value)
    elif image_set.status != ImageSetStatus.APPROVED:
        reasons.append(ListingReadinessReason.IMAGES_NOT_APPROVED.value)
    if pricing is None or pricing.final_price_minor is None:
        reasons.append(ListingReadinessReason.NO_PRICE.value)
    elif pricing.stock_decision == StockDecision.ACTIVE:
        pass
    elif pricing.stock_decision == StockDecision.REVIEW:
        reasons.append(ListingReadinessReason.PRICING_REVIEW.value)
    elif pricing.stock_decision == StockDecision.PAUSE:
        reasons.append(ListingReadinessReason.SUPPLIER_STALE.value)
    elif pricing.stock_decision == StockDecision.OUT_OF_STOCK:
        reasons.append(ListingReadinessReason.NO_STOCK.value)
    if pricing and PricingReasonCode.MANUAL_PRICE_BELOW_FLOOR.value in pricing.reason_codes:
        reasons.append(ListingReadinessReason.BELOW_HARD_FLOOR.value)
    if pricing and PricingReasonCode.SUPPLIER_CONFLICT.value in pricing.reason_codes:
        reasons.append(ListingReadinessReason.SUPPLIER_CONFLICT.value)
    blocking = set(reasons) - {ListingReadinessReason.UNKNOWN_CONDITION.value}
    if not blocking:
        return GenericReadinessStatus.READY, reasons
    if ListingReadinessReason.FACT_CONFLICT.value in reasons or ListingReadinessReason.PRICING_REVIEW.value in reasons:
        return GenericReadinessStatus.REVIEW_REQUIRED, reasons
    return GenericReadinessStatus.NOT_READY, reasons


def pricing_snapshot(pricing: VariantPricingState | None) -> dict | None:
    if pricing is None:
        return None
    return {
        "price_minor": pricing.final_price_minor,
        "stock_decision": pricing.stock_decision.value,
        "fulfillment_source": pricing.fulfillment_source.value,
        "pricing_supplier_id": str(pricing.pricing_supplier_id) if pricing.pricing_supplier_id else None,
        "reason_codes": sorted(pricing.reason_codes),
    }


def listing_status_for(readiness: GenericReadinessStatus) -> GenericListingStatus:
    return {
        GenericReadinessStatus.READY: GenericListingStatus.READY,
        GenericReadinessStatus.REVIEW_REQUIRED: GenericListingStatus.REVIEW_REQUIRED,
        GenericReadinessStatus.APPROVED: GenericListingStatus.APPROVED,
        GenericReadinessStatus.STALE: GenericListingStatus.STALE,
    }.get(readiness, GenericListingStatus.NOT_READY)


def classify_category(facts: ProductContentFacts | None) -> GenericCategory:
    if facts is None:
        return GenericCategory.OTHER
    text = " ".join(str(part).lower() for part in (facts.model, facts.canonical_product_name) if part)
    if any(token in text for token in ("galaxy", "iphone", "pixel", "smartphone")):
        return GenericCategory.SMARTPHONE
    if "tablet" in text or "ipad" in text:
        return GenericCategory.TABLET
    if "watch" in text:
        return GenericCategory.SMART_WATCH
    if "headphone" in text or "buds" in text:
        return GenericCategory.HEADPHONES
    if "laptop" in text or "macbook" in text:
        return GenericCategory.LAPTOP
    if "generator" in text:
        return GenericCategory.GENERATOR
    if "power station" in text:
        return GenericCategory.POWER_STATION
    return GenericCategory.OTHER


async def latest_approved_content(session: AsyncSession, variant_id: uuid.UUID) -> ProductContentDraft | None:
    return await session.scalar(select(ProductContentDraft).where(ProductContentDraft.variant_id == variant_id, ProductContentDraft.status == ContentDraftStatus.APPROVED).order_by(ProductContentDraft.approved_at.desc()).limit(1))


async def latest_approved_image_set(session: AsyncSession, variant_id: uuid.UUID) -> ProductImageSet | None:
    return await session.scalar(select(ProductImageSet).where(ProductImageSet.variant_id == variant_id, ProductImageSet.status == ImageSetStatus.APPROVED).order_by(ProductImageSet.approved_at.desc()).limit(1))


async def list_variant_drafts(session: AsyncSession, variant_id: uuid.UUID) -> list[ProductContentDraft]:
    return list(await session.scalars(select(ProductContentDraft).where(ProductContentDraft.variant_id == variant_id).order_by(ProductContentDraft.created_at.desc())))


async def list_variant_image_sets(session: AsyncSession, variant_id: uuid.UUID) -> list[ProductImageSet]:
    return list(await session.scalars(select(ProductImageSet).where(ProductImageSet.variant_id == variant_id).order_by(ProductImageSet.created_at.desc())))


async def list_variant_listings(session: AsyncSession, variant_id: uuid.UUID | None = None, *, status_filter: GenericReadinessStatus | None = None, limit: int = 100) -> list[GenericListingDraft]:
    statement = select(GenericListingDraft).order_by(GenericListingDraft.created_at.desc()).limit(min(limit, 500))
    if variant_id is not None:
        statement = statement.where(GenericListingDraft.variant_id == variant_id)
    if status_filter is not None:
        statement = statement.where(GenericListingDraft.generic_readiness == status_filter)
    return list(await session.scalars(statement))


async def recalculate_listing_readiness_bulk(session: AsyncSession, *, limit: int = 100) -> dict:
    variant_ids = list(await session.scalars(select(ProductVariant.id).order_by(ProductVariant.created_at).limit(min(limit, 500))))
    result = {"processed": 0, "created": 0, "updated": 0, "unchanged": 0, "review_required": 0, "failed": 0, "skipped": 0}
    for variant_id in variant_ids:
        before_count = await session.scalar(select(func.count()).select_from(GenericListingDraft).where(GenericListingDraft.variant_id == variant_id))
        try:
            listing = await build_generic_listing(session, variant_id)
            after_count = await session.scalar(select(func.count()).select_from(GenericListingDraft).where(GenericListingDraft.variant_id == variant_id))
            result["processed"] += 1
            if after_count > before_count:
                result["created"] += 1
            else:
                result["unchanged"] += 1
            if listing.generic_readiness == GenericReadinessStatus.REVIEW_REQUIRED:
                result["review_required"] += 1
        except ValueError:
            result["failed"] += 1
    return result


class MarketplaceListingAdapter:
    def validate_contract(self) -> dict:
        raise NotImplementedError

    def prepare_payload(self, listing: GenericListingDraft) -> dict:
        raise NotImplementedError

    def publication_readiness(self, listing: GenericListingDraft) -> MarketplaceReadinessStatus:
        raise NotImplementedError


class AvitoListingAdapter(MarketplaceListingAdapter):
    def validate_contract(self) -> dict:
        return {"status": MarketplaceReadinessStatus.DISABLED_CONTRACT_INCOMPLETE.value, "reason": "AVITO_LISTING_CONTRACT_GATE_FAIL"}

    def prepare_payload(self, listing: GenericListingDraft) -> dict:
        raise ValueError("AVITO_CONTRACT_INCOMPLETE")

    def publication_readiness(self, listing: GenericListingDraft) -> MarketplaceReadinessStatus:
        return MarketplaceReadinessStatus.DISABLED_CONTRACT_INCOMPLETE
