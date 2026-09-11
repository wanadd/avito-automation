import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.enums import ParseStatus, ProductCondition
from app.models.match_review import MatchReview
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.product import Product, ProductAlias, ProductVariant
from app.models.raw_source_record import RawSourceRecord
from app.models.supplier_offer import SupplierOffer, SupplierOfferSnapshot
from app.services.canonical_key import build_canonical_key
from app.services.matcher import match_parsed_item

FIXTURE_TEXT = Path("tests/fixtures/telegram_price.txt").read_text(encoding="utf-8")
pytestmark = pytest.mark.usefixtures("clean_database")


async def seed_context():
    async with AsyncSessionLocal() as session:
        supplier = __import__("app.models.supplier", fromlist=["Supplier"]).Supplier(
            code=f"matcher-supplier-{uuid.uuid4().hex[:8]}", name="Matcher Supplier"
        )
        session.add(supplier)
        await session.flush()
        source = __import__("app.models.source", fromlist=["Source"]).Source(
            supplier_id=supplier.id, source_type="IMPORT", name="Matcher Import"
        )
        session.add(source)
        await session.flush()
        raw = RawSourceRecord(source_id=source.id, raw_text="raw", content_hash="hash")
        session.add(raw)
        await session.commit()
        return supplier.id, source.id, raw.id


async def make_item(
    *,
    brand="Samsung",
    model="Galaxy S25 Ultra",
    model_raw="S25 ultra",
    code="S938B",
    ram=12,
    storage=256,
    color="Silver Blue",
    region="KW",
    condition=None,
    price=6530000,
    confidence="1.0000",
    status=ParseStatus.PARSED,
    flags=None,
):
    supplier_id, source_id, raw_id = await seed_context()
    async with AsyncSessionLocal() as session:
        item = ParsedSupplierItem(
            raw_source_record_id=raw_id,
            source_id=source_id,
            supplier_id=supplier_id,
            line_number=1,
            raw_line=f"{model_raw} {code or ''} {ram or ''}/{storage or ''} {color or ''} - {price or ''}",
            section_raw=brand,
            section_normalized=brand,
            brand_raw=brand,
            brand_normalized=brand,
            model_raw=model_raw,
            model_normalized=model,
            manufacturer_model_code=code,
            ram_gb=ram,
            storage_gb=storage,
            color_raw=color,
            color_normalized=color,
            region_raw=None,
            region_code=region,
            condition=condition,
            price_minor=price,
            parse_confidence=confidence,
            parse_status=status,
            parse_flags=flags or [],
            parsed_payload={},
            parsed_identity_key="test",
        )
        session.add(item)
        await session.commit()
        return item.id


async def seed_variant(
    *,
    brand="Samsung",
    model="Galaxy S25 Ultra",
    code="S938B",
    ram=12,
    storage=256,
    color="Silver Blue",
    region="KW",
    condition=ProductCondition.NEW,
):
    async with AsyncSessionLocal() as session:
        product = await session.scalar(select(Product).where(Product.brand == brand, Product.canonical_name == model))
        if product is None:
            product = Product(brand=brand, canonical_name=model, category="smartphone")
            session.add(product)
            await session.flush()
        variant = ProductVariant(
            product_id=product.id,
            manufacturer_model_code=code,
            ram_gb=ram,
            storage_gb=storage,
            color_raw=color,
            color_normalized=color,
            region_code=region,
            condition=condition,
            canonical_key=build_canonical_key(
                brand=brand,
                canonical_name=model,
                manufacturer_model_code=code,
                ram_gb=ram,
                storage_gb=storage,
                color_normalized=color,
                region_code=region,
                condition=condition,
            ),
        )
        session.add(variant)
        await session.commit()
        return product.id, variant.id


async def count(model):
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_exact_model_code_match():
    await seed_variant()
    item_id = await make_item(condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "EXACT_MATCH"
    assert result.strategy == "MODEL_CODE_EXACT"


async def test_model_code_case_insensitive():
    await seed_variant(code="s938b")
    item_id = await make_item(code="S938B", condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "EXACT_MATCH"


async def test_exact_attribute_match_without_model_code():
    await seed_variant(code=None)
    item_id = await make_item(code=None, condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "EXACT_MATCH"
    assert result.strategy == "ATTRIBUTES_EXACT"


async def test_alias_product_match():
    product_id, variant_id = await seed_variant()
    async with AsyncSessionLocal() as session:
        session.add(ProductAlias(product_id=product_id, alias="S25U", normalized_alias="s25u"))
        await session.commit()
    item_id = await make_item(model_raw="S25U", code=None, condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "EXACT_MATCH"
    assert result.strategy == "ALIAS_EXACT"


async def test_alias_variant_match():
    _, variant_id = await seed_variant()
    async with AsyncSessionLocal() as session:
        session.add(ProductAlias(product_variant_id=variant_id, alias="S25U", normalized_alias="s25u"))
        await session.commit()
    item_id = await make_item(model_raw="S25U", code=None, condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.strategy == "ALIAS_EXACT"


async def test_source_specific_alias():
    _, variant_id = await seed_variant()
    item_id = await make_item(model_raw="S25U", code=None, condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        item = await session.get(ParsedSupplierItem, item_id)
        session.add(ProductAlias(product_variant_id=variant_id, alias="S25U", normalized_alias="s25u", source_id=item.source_id))
        await session.commit()
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.strategy == "ALIAS_EXACT"


async def test_fuzzy_produces_review():
    await seed_variant()
    item_id = await make_item(model="Galaxy S25 Ultr", model_raw="S25 Ultr", code=None, condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "REVIEW"
    assert "FUZZY_CANDIDATE_REVIEW" in result.reasons


async def test_ambiguous_candidate_produces_review():
    await seed_variant(code=None, color="Black")
    await seed_variant(code=None, color="White")
    item_id = await make_item(code=None, color=None, confidence="0.9000")
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "REVIEW"


async def test_storage_conflict():
    await seed_variant(storage=512)
    item_id = await make_item(storage=256, condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "REVIEW"
    assert "STORAGE_CONFLICT" in result.reasons


async def test_ram_conflict():
    await seed_variant(ram=16)
    item_id = await make_item(ram=12, condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert "RAM_CONFLICT" in result.reasons


async def test_region_conflict():
    await seed_variant(region="IN")
    item_id = await make_item(region="KW", condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert "REGION_CONFLICT" in result.reasons


async def test_color_conflict():
    await seed_variant(color="Black")
    item_id = await make_item(color="Silver Blue", condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert "COLOR_CONFLICT" in result.reasons


async def test_condition_conflict():
    await seed_variant(condition=ProductCondition.USED)
    item_id = await make_item(condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert "CONDITION_CONFLICT" in result.reasons


async def test_product_safe_auto_create():
    item_id = await make_item(condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "AUTO_CREATED"
    assert result.created_product
    assert await count(Product) == 1


async def test_product_variant_safe_auto_create():
    async with AsyncSessionLocal() as session:
        session.add(Product(brand="Samsung", canonical_name="Galaxy S25 Ultra", category="smartphone"))
        await session.commit()
    item_id = await make_item(condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.created_variant
    assert await count(ProductVariant) == 1


async def test_low_confidence_no_auto_create():
    item_id = await make_item(confidence="0.7000")
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "REVIEW"
    assert await count(ProductVariant) == 0


async def test_conflict_parsed_item_blocked():
    item_id = await make_item(status=ParseStatus.CONFLICT, flags=["PRICE_CONFLICT"])
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "CONFLICT_BLOCKED"
    assert await count(SupplierOffer) == 0


async def test_missing_price_blocked():
    item_id = await make_item(price=None)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "REVIEW"


async def test_invalid_price_blocked():
    item_id = await make_item(flags=["INVALID_PRICE"])
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "REVIEW"


async def test_supplier_offer_created_after_exact_match():
    await seed_variant()
    item_id = await make_item(condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        await match_parsed_item(session, item_id)
    assert await count(SupplierOffer) == 1


async def test_supplier_offer_created_after_safe_auto_create():
    item_id = await make_item(condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        await match_parsed_item(session, item_id)
    assert await count(SupplierOffer) == 1


async def test_repeated_ingestion_idempotent():
    item_id = await make_item()
    async with AsyncSessionLocal() as session:
        await match_parsed_item(session, item_id)
        await match_parsed_item(session, item_id)
    assert await count(Product) == 1
    assert await count(ProductVariant) == 1
    assert await count(SupplierOffer) == 1


async def test_existing_offer_price_change_uses_snapshot():
    await seed_variant()
    item_id = await make_item(price=6530000, condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        await match_parsed_item(session, item_id)
        item = await session.get(ParsedSupplierItem, item_id)
        item.price_minor = 6630000
        await session.commit()
        await match_parsed_item(session, item_id)
    assert await count(SupplierOfferSnapshot) == 2


async def test_unchanged_offer_no_new_snapshot():
    await seed_variant()
    item_id = await make_item(condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        await match_parsed_item(session, item_id)
        await match_parsed_item(session, item_id)
    assert await count(SupplierOfferSnapshot) == 1


async def test_match_review_created_once():
    item_id = await make_item(confidence="0.7000")
    async with AsyncSessionLocal() as session:
        await match_parsed_item(session, item_id)
        await match_parsed_item(session, item_id)
    assert await count(MatchReview) == 1


async def test_concurrent_variant_creation_safe():
    item_id = await make_item(condition=ProductCondition.NEW)
    async def run_match():
        async with AsyncSessionLocal() as session:
            return await match_parsed_item(session, item_id)
    await asyncio.gather(run_match(), run_match())
    assert await count(Product) == 1
    assert await count(ProductVariant) == 1
    assert await count(SupplierOffer) == 1


async def test_s25_ultra_fixture_end_to_end(client):
    raw = await seed_fixture(client)
    await client.post(f"/api/v1/raw-records/{raw['id']}/parse")
    summary = await client.post(f"/api/v1/raw-records/{raw['id']}/match")
    assert summary.status_code == 200, summary.text
    async with AsyncSessionLocal() as session:
        offer = await session.scalar(select(SupplierOffer).where(SupplierOffer.supplier_title.contains("S25 ultra")))
        variant = await session.get(ProductVariant, offer.product_variant_id)
        product = await session.get(Product, variant.product_id)
    assert product.canonical_name == "Galaxy S25 Ultra"
    assert variant.manufacturer_model_code == "S938B"
    assert variant.storage_gb == 256
    assert variant.region_code == "KW"
    assert offer.price_minor == 6530000


async def test_s26_conflict_remains_blocked(client):
    raw = await seed_fixture(client)
    await client.post(f"/api/v1/raw-records/{raw['id']}/parse")
    await client.post(f"/api/v1/raw-records/{raw['id']}/match")
    async with AsyncSessionLocal() as session:
        s26_offers = await session.scalar(select(func.count()).select_from(SupplierOffer).where(SupplierOffer.supplier_title.contains("S26")))
        conflicts = await session.scalar(select(func.count()).select_from(ParsedSupplierItem).where(ParsedSupplierItem.parse_flags.contains(["PRICE_CONFLICT"])))
    assert s26_offers == 0
    assert conflicts == 2


async def test_apple_pro_max_not_matched_to_pro():
    await seed_variant(brand="Apple", model="iPhone 17 Pro", code=None, ram=None, storage=256, color="Blue", region="HK")
    item_id = await make_item(brand="Apple", model="iPhone 17 Pro Max", model_raw="17 pro max", code=None, ram=None, storage=256, color="Blue", region="HK")
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status != "EXACT_MATCH"


async def test_redmi_note_variants_remain_distinct():
    await seed_variant(brand="Redmi", model="Note 17 Pro", code=None, ram=8, storage=256, color="Black", region="RU")
    item_id = await make_item(brand="Redmi", model="Note 17 Pro 5G", model_raw="Note 17 pro 5g", code=None, ram=8, storage=256, color="Black", region="RU")
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status != "EXACT_MATCH"


async def test_raw_evidence_unchanged(client):
    raw = await seed_fixture(client)
    before = (await client.get(f"/api/v1/raw-records/{raw['id']}")).json()["raw_text"]
    await client.post(f"/api/v1/raw-records/{raw['id']}/parse")
    await client.post(f"/api/v1/raw-records/{raw['id']}/match")
    after = (await client.get(f"/api/v1/raw-records/{raw['id']}")).json()["raw_text"]
    assert before == after == FIXTURE_TEXT


def test_product_variant_canonical_key_deterministic():
    kwargs = dict(
        brand="Samsung",
        canonical_name="Galaxy S25 Ultra",
        manufacturer_model_code="S938B",
        ram_gb=12,
        storage_gb=256,
        color_normalized="Silver Blue",
        region_code="KW",
        condition=ProductCondition.NEW,
    )
    assert build_canonical_key(**kwargs) == build_canonical_key(**kwargs)


async def test_api_single_item_match(client):
    raw = await seed_fixture(client)
    parsed = (await client.post(f"/api/v1/raw-records/{raw['id']}/parse")).json()
    s25 = next(item for item in parsed["items"] if "S25 ultra" in item["raw_line"])
    response = await client.post(f"/api/v1/parsed-items/{s25['id']}/match")
    assert response.status_code == 200
    assert response.json()["status"] in {"AUTO_CREATED", "EXACT_MATCH"}


async def test_api_full_raw_record_match(client):
    raw = await seed_fixture(client)
    await client.post(f"/api/v1/raw-records/{raw['id']}/parse")
    response = await client.post(f"/api/v1/raw-records/{raw['id']}/match")
    assert response.status_code == 200
    assert response.json()["conflict_blocked"] == 2


async def test_match_review_listing(client):
    item_id = await make_item(confidence="0.7000")
    async with AsyncSessionLocal() as session:
        await match_parsed_item(session, item_id)
    response = await client.get("/api/v1/match-reviews")
    assert response.status_code == 200
    assert len(response.json()) == 1
    single = await client.get(f"/api/v1/match-reviews/{response.json()[0]['id']}")
    assert single.status_code == 200


async def test_missing_condition_does_not_become_new():
    item_id = await make_item(condition=None)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
        variant = await session.get(ProductVariant, result.matched_variant_id)
    assert result.status == "AUTO_CREATED"
    assert variant.condition is None


async def test_missing_condition_remains_null_when_schema_allows_auto_create():
    item_id = await make_item(condition=None)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
        variant = await session.get(ProductVariant, result.matched_variant_id)
    assert result.status == "AUTO_CREATED"
    assert variant.condition is None
    assert "new" not in variant.canonical_key


async def test_explicit_new_remains_new():
    item_id = await make_item(condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
        variant = await session.get(ProductVariant, result.matched_variant_id)
    assert variant.condition == ProductCondition.NEW


async def test_explicit_used_remains_used():
    item_id = await make_item(condition=ProductCondition.USED)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
        variant = await session.get(ProductVariant, result.matched_variant_id)
    assert variant.condition == ProductCondition.USED


async def test_explicit_refurbished_remains_refurbished():
    item_id = await make_item(condition=ProductCondition.REFURBISHED)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
        variant = await session.get(ProductVariant, result.matched_variant_id)
    assert variant.condition == ProductCondition.REFURBISHED


async def test_unknown_condition_does_not_exact_match_known_new_variant():
    await seed_variant(condition=ProductCondition.NEW)
    item_id = await make_item(condition=None)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "REVIEW"
    assert "MISSING_CONDITION" in result.reasons


async def test_unknown_condition_does_not_exact_match_known_used_variant():
    await seed_variant(condition=ProductCondition.USED)
    item_id = await make_item(condition=None)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "REVIEW"
    assert "MISSING_CONDITION" in result.reasons


async def test_new_does_not_match_used():
    await seed_variant(condition=ProductCondition.USED)
    item_id = await make_item(condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "REVIEW"
    assert "CONDITION_CONFLICT" in result.reasons


async def test_new_does_not_match_refurbished():
    await seed_variant(condition=ProductCondition.REFURBISHED)
    item_id = await make_item(condition=ProductCondition.NEW)
    async with AsyncSessionLocal() as session:
        result = await match_parsed_item(session, item_id)
    assert result.status == "REVIEW"
    assert "CONDITION_CONFLICT" in result.reasons


async def test_repeated_ingestion_with_unknown_condition_remains_idempotent():
    item_id = await make_item(condition=None)
    async with AsyncSessionLocal() as session:
        first = await match_parsed_item(session, item_id)
        second = await match_parsed_item(session, item_id)
        variant = await session.get(ProductVariant, second.matched_variant_id)
    assert first.matched_variant_id == second.matched_variant_id
    assert variant.condition is None
    assert await count(Product) == 1
    assert await count(ProductVariant) == 1
    assert await count(SupplierOffer) == 1


async def seed_fixture(client):
    supplier = await client.post("/api/v1/suppliers", json={"code": "fixture-matcher", "name": "Fixture Matcher"})
    assert supplier.status_code == 201, supplier.text
    source = await client.post(
        "/api/v1/sources",
        json={"supplier_id": supplier.json()["id"], "source_type": "TELEGRAM", "external_key": "fixture", "name": "Fixture"},
    )
    assert source.status_code == 201, source.text
    raw = await client.post(
        "/api/v1/raw-records",
        json={"source_id": source.json()["id"], "external_record_id": "fixture-match", "raw_text": FIXTURE_TEXT},
    )
    assert raw.status_code == 201, raw.text
    return raw.json()
