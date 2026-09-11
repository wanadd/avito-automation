from uuid import UUID

from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.conflict import DataConflict
from app.models.enums import Availability
from app.models.raw_source_record import RawSourceRecord
from app.models.supplier_offer import SupplierOffer, SupplierOfferSnapshot
from app.services.canonical_key import build_canonical_key
from app.services.offers import record_price_conflict


async def create_supplier(client, code="supplier-a"):
    response = await client.post("/api/v1/suppliers", json={"code": code, "name": code.title()})
    assert response.status_code == 201, response.text
    return response.json()


async def create_source(client, supplier_id):
    response = await client.post(
        "/api/v1/sources",
        json={
            "supplier_id": supplier_id,
            "source_type": "IMPORT",
            "external_key": "price-list",
            "name": "Price list",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_product(client):
    response = await client.post(
        "/api/v1/products",
        json={"brand": "Apple", "canonical_name": "Apple iPhone 17 Pro Max", "category": "smartphone"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_variant(client, product_id):
    response = await client.post(
        f"/api/v1/products/{product_id}/variants",
        json={
            "manufacturer_model_code": "A9999",
            "ram_gb": 12,
            "storage_gb": 512,
            "color_raw": "Deep Blue",
            "color_normalized": "Blue",
            "region_code": "RU",
            "condition": "NEW",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_raw_record(client, source_id, external_record_id="row-1"):
    response = await client.post(
        "/api/v1/raw-records",
        json={
            "source_id": source_id,
            "external_record_id": external_record_id,
            "raw_text": "iphone 17 pro max 512 blue 150000",
            "raw_payload": {"row": 1},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_offer(client, supplier_id, variant_id, source_id=None, source_record_id=None, sku="sku-1", price=15000000, availability="IN_STOCK"):
    response = await client.post(
        "/api/v1/supplier-offers",
        json={
            "supplier_id": supplier_id,
            "product_variant_id": variant_id,
            "source_id": source_id,
            "supplier_sku": sku,
            "supplier_title": "Apple iPhone 17 Pro Max 512 Blue",
            "price_minor": price,
            "currency": "RUB",
            "availability": availability,
            "source_record_id": source_record_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def snapshot_count():
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(SupplierOfferSnapshot))


async def test_create_supplier(client):
    supplier = await create_supplier(client)
    response = await client.get(f"/api/v1/suppliers/{supplier['id']}")
    assert response.status_code == 200
    assert response.json()["code"] == "supplier-a"


async def test_create_product(client):
    product = await create_product(client)
    response = await client.get("/api/v1/products")
    assert response.status_code == 200
    assert response.json()[0]["canonical_name"] == product["canonical_name"]


async def test_create_variant(client):
    product = await create_product(client)
    variant = await create_variant(client, product["id"])
    response = await client.get(f"/api/v1/variants/{variant['id']}")
    assert response.status_code == 200
    assert response.json()["canonical_key"] == "apple|apple iphone 17 pro max|a9999|12gb|512gb|blue|ru|new"


def test_deterministic_canonical_key():
    first = build_canonical_key(
        brand=" Apple ",
        canonical_name="Apple   iPhone 17 Pro Max",
        manufacturer_model_code=None,
        ram_gb=12,
        storage_gb=512,
        color_normalized=" Blue ",
        region_code="RU",
        condition="NEW",
    )
    second = build_canonical_key(
        brand="apple",
        canonical_name="Apple iPhone 17 Pro Max",
        manufacturer_model_code=None,
        ram_gb=12,
        storage_gb=512,
        color_normalized="blue",
        region_code="ru",
        condition="new",
    )
    assert first == second == "apple|apple iphone 17 pro max|na|12gb|512gb|blue|ru|new"


async def test_one_variant_can_have_three_supplier_offers(client):
    product = await create_product(client)
    variant = await create_variant(client, product["id"])
    for suffix in ("a", "b", "c"):
        supplier = await create_supplier(client, f"supplier-{suffix}")
        await create_offer(client, supplier["id"], variant["id"], sku=f"sku-{suffix}", price=15000000)

    response = await client.get(f"/api/v1/variants/{variant['id']}/offers")
    assert response.status_code == 200
    assert len(response.json()) == 3


async def test_price_change_creates_snapshot(client):
    supplier = await create_supplier(client)
    source = await create_source(client, supplier["id"])
    raw = await create_raw_record(client, source["id"])
    variant = await create_variant(client, (await create_product(client))["id"])
    await create_offer(client, supplier["id"], variant["id"], source["id"], raw["id"], price=15000000)
    await create_offer(client, supplier["id"], variant["id"], source["id"], raw["id"], price=15100000)

    assert await snapshot_count() == 2


async def test_same_price_does_not_create_extra_snapshot(client):
    supplier = await create_supplier(client)
    variant = await create_variant(client, (await create_product(client))["id"])
    await create_offer(client, supplier["id"], variant["id"], price=15000000)
    await create_offer(client, supplier["id"], variant["id"], price=15000000)

    assert await snapshot_count() == 1


async def test_availability_change_creates_snapshot(client):
    supplier = await create_supplier(client)
    variant = await create_variant(client, (await create_product(client))["id"])
    await create_offer(client, supplier["id"], variant["id"], availability="IN_STOCK")
    await create_offer(client, supplier["id"], variant["id"], availability="OUT_OF_STOCK")

    assert await snapshot_count() == 2


async def test_duplicate_raw_record_is_not_imported_twice(client):
    supplier = await create_supplier(client)
    source = await create_source(client, supplier["id"])
    first = await create_raw_record(client, source["id"], external_record_id="telegram-42")
    second = await create_raw_record(client, source["id"], external_record_id="telegram-42")

    async with AsyncSessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(RawSourceRecord))
    assert first["id"] == second["id"]
    assert count == 1


async def test_conflicting_prices_create_data_conflict(client):
    supplier = await create_supplier(client)
    source = await create_source(client, supplier["id"])
    raw = await create_raw_record(client, source["id"])
    variant = await create_variant(client, (await create_product(client))["id"])

    async with AsyncSessionLocal() as session:
        conflict = await record_price_conflict(
            session,
            supplier_id=UUID(supplier["id"]),
            product_variant_id=UUID(variant["id"]),
            source_id=UUID(source["id"]),
            raw_source_record_id=UUID(raw["id"]),
            first_price_minor=15000000,
            second_price_minor=15100000,
        )

    assert conflict is not None
    response = await client.get("/api/v1/conflicts")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "OPEN"


async def test_conflict_does_not_overwrite_current_price(client):
    supplier = await create_supplier(client)
    variant = await create_variant(client, (await create_product(client))["id"])
    offer = await create_offer(client, supplier["id"], variant["id"], price=15000000)

    async with AsyncSessionLocal() as session:
        await record_price_conflict(
            session,
            supplier_id=UUID(supplier["id"]),
            product_variant_id=UUID(variant["id"]),
            source_id=None,
            raw_source_record_id=None,
            first_price_minor=15000000,
            second_price_minor=15100000,
        )
        current = await session.get(SupplierOffer, offer["id"])
        assert current.price_minor == 15000000


async def test_audit_log_created_on_price_change(client):
    supplier = await create_supplier(client)
    variant = await create_variant(client, (await create_product(client))["id"])
    await create_offer(client, supplier["id"], variant["id"], price=15000000)
    await create_offer(client, supplier["id"], variant["id"], price=15100000)

    async with AsyncSessionLocal() as session:
        audit = await session.scalar(select(AuditLog).where(AuditLog.action == "UPDATED"))
    assert audit is not None
    assert audit.old_value["price_minor"] == 15000000
    assert audit.new_value["price_minor"] == 15100000
