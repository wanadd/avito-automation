from pathlib import Path

from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.conflict import DataConflict
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.raw_source_record import RawSourceRecord
from app.models.supplier_offer import SupplierOffer


FIXTURE_TEXT = Path("tests/fixtures/telegram_price.txt").read_text(encoding="utf-8")


async def seed_raw_record(client):
    supplier = await client.post("/api/v1/suppliers", json={"code": "parser-supplier", "name": "Parser Supplier"})
    assert supplier.status_code == 201, supplier.text
    source = await client.post(
        "/api/v1/sources",
        json={
            "supplier_id": supplier.json()["id"],
            "source_type": "TELEGRAM",
            "external_key": "fixture-channel",
            "name": "Fixture Telegram",
        },
    )
    assert source.status_code == 201, source.text
    raw = await client.post(
        "/api/v1/raw-records",
        json={"source_id": source.json()["id"], "external_record_id": "fixture-1", "raw_text": FIXTURE_TEXT},
    )
    assert raw.status_code == 201, raw.text
    return raw.json()


async def test_data_conflict_contains_both_raw_lines_and_prices(client):
    raw = await seed_raw_record(client)
    response = await client.post(f"/api/v1/raw-records/{raw['id']}/parse")
    assert response.status_code == 200, response.text

    async with AsyncSessionLocal() as session:
        conflict = await session.scalar(select(DataConflict).where(DataConflict.conflict_type == "PARSED_SUPPLIER_PRICE_MISMATCH"))
    assert conflict is not None
    assert conflict.details["prices_minor"] == [6350000, 6450000]
    raw_lines = [item["raw_line"] for item in conflict.details["evidence"]]
    assert "🇮🇳S26 S942B 12/256 violet - 63500" in raw_lines
    assert "🇮🇳S26 S942B 12/256 violet - 64500" in raw_lines


async def test_conflict_does_not_create_supplier_offer(client):
    raw = await seed_raw_record(client)
    await client.post(f"/api/v1/raw-records/{raw['id']}/parse")

    async with AsyncSessionLocal() as session:
        offer_count = await session.scalar(select(func.count()).select_from(SupplierOffer))
    assert offer_count == 0


async def test_parse_endpoint_works(client):
    raw = await seed_raw_record(client)
    response = await client.post(f"/api/v1/raw-records/{raw['id']}/parse")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["raw_record_id"] == raw["id"]
    assert payload["total_lines"] == len(FIXTURE_TEXT.splitlines())
    assert payload["conflict_count"] == 2
    assert payload["ignored_count"] >= 6
    assert payload["items"]


async def test_repeated_parse_is_idempotent(client):
    raw = await seed_raw_record(client)
    first = await client.post(f"/api/v1/raw-records/{raw['id']}/parse")
    second = await client.post(f"/api/v1/raw-records/{raw['id']}/parse")
    assert first.status_code == second.status_code == 200

    async with AsyncSessionLocal() as session:
        item_count = await session.scalar(select(func.count()).select_from(ParsedSupplierItem))
        conflict_count = await session.scalar(select(func.count()).select_from(DataConflict))
    assert item_count == len(FIXTURE_TEXT.splitlines())
    assert conflict_count == 1


async def test_raw_source_record_remains_unchanged_after_parse(client):
    raw = await seed_raw_record(client)
    await client.post(f"/api/v1/raw-records/{raw['id']}/parse")

    async with AsyncSessionLocal() as session:
        stored = await session.get(RawSourceRecord, raw["id"])
    assert stored.raw_text == FIXTURE_TEXT


async def test_get_parsed_items_endpoints(client):
    raw = await seed_raw_record(client)
    await client.post(f"/api/v1/raw-records/{raw['id']}/parse")
    listed = await client.get(f"/api/v1/raw-records/{raw['id']}/parsed-items")
    assert listed.status_code == 200
    first_id = listed.json()[0]["id"]
    single = await client.get(f"/api/v1/parsed-items/{first_id}")
    assert single.status_code == 200
    assert single.json()["id"] == first_id
