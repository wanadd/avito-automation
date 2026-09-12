import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.integrations.one_c.importer import import_one_c_file, map_one_c_item, unmap_one_c_item
from app.integrations.one_c.parser import parse_file_bytes, parse_cost_minor
from app.models.enums import OneCImportMode, OneCImportRunStatus, OneCItemMatchStatus, OneCItemMatchStrategy, ProductCondition
from app.models.one_c import OneCImportRun, OneCItem, VariantCostSnapshot, VariantInventoryState, VariantStockSnapshot
from app.models.product import Product, ProductAlias, ProductVariant
from app.models.audit_log import AuditLog
from app.services.canonical_key import build_canonical_key

pytestmark = pytest.mark.usefixtures("clean_database")

T1 = datetime(2026, 9, 11, 14, 30, tzinfo=UTC)
T2 = T1 + timedelta(minutes=10)


def json_file(items, exported_at=T1):
    return json.dumps({"exported_at": exported_at.isoformat(), "source": "1c", "items": items}).encode()


def row(code="000123", name="Samsung Galaxy S25 Ultra S938B 12/256 Silverblue", stock=2, cost="65000.00", **overrides):
    payload = {
        "internal_code": code,
        "sku": f"SKU-{code}",
        "barcode": f"BAR-{code}",
        "name": name,
        "stock_total": stock,
        "cost": cost,
        "currency": "RUB",
        "updated_at": T1.isoformat(),
    }
    payload.update(overrides)
    return payload


async def count(model):
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def seed_variant(brand="Samsung", name=None, code="S938B", storage=256, alias=None):
    name = name or f"Samsung Galaxy S25 Ultra {code}"
    async with AsyncSessionLocal() as session:
        product = Product(brand=brand, canonical_name=name, category="smartphone")
        session.add(product)
        await session.flush()
        variant = ProductVariant(
            product_id=product.id,
            manufacturer_model_code=code,
            ram_gb=12,
            storage_gb=storage,
            color_raw="Silverblue",
            color_normalized="silverblue",
            region_code=None,
            condition=ProductCondition.NEW,
            canonical_key=build_canonical_key(
                brand=brand,
                canonical_name=name,
                manufacturer_model_code=code,
                ram_gb=12,
                storage_gb=storage,
                color_normalized="silverblue",
                region_code=None,
                condition=ProductCondition.NEW,
            ) + uuid.uuid4().hex[:6],
        )
        session.add(variant)
        await session.flush()
        if alias:
            session.add(ProductAlias(product_variant_id=variant.id, alias=alias, normalized_alias=alias.lower()))
        await session.commit()
        return variant.id


async def run_import(items, *, mode=OneCImportMode.PARTIAL, dry_run=False, exported_at=T1):
    async with AsyncSessionLocal() as session:
        return await import_one_c_file(session, json_file(items, exported_at), filename="onec.json", mode=mode, dry_run=dry_run)


def test_json_import_valid():
    parsed = parse_file_bytes(json_file([row()]), filename="stock.json")
    assert parsed.rows[0].internal_code == "000123"
    assert parsed.rows[0].cost_minor == 6500000


def test_csv_comma_valid():
    content = b"internal_code,sku,barcode,name,stock_total,cost,currency,updated_at\n1,S,B,Phone S938B,2,65300.00,RUB,2026-09-11T14:30:00+00:00\n"
    assert parse_file_bytes(content, filename="stock.csv").rows[0].stock_total == 2


def test_csv_semicolon_valid():
    content = "internal_code;sku;barcode;name;stock_total;cost;currency;updated_at\n1;S;B;Телефон S938B;2;65300,00;RUB;2026-09-11T14:30:00+00:00\n".encode("utf-8")
    parsed = parse_file_bytes(content, filename="stock.csv")
    assert parsed.rows[0].raw_name == "Телефон S938B"
    assert parsed.rows[0].cost_minor == 6530000


def test_utf8_bom_and_cyrillic_preserved():
    content = ("\ufeffinternal_code,sku,barcode,name,stock_total,cost,currency,updated_at\n1,S,B,Айфон,1,10,RUB,2026-09-11T14:30:00+00:00\n").encode()
    assert parse_file_bytes(content, filename="stock.csv").rows[0].raw_name == "Айфон"


@pytest.mark.parametrize("value,minor", [("65300", 6530000), ("65300.00", 6530000), ("65300,00", 6530000), ("65 300,00", 6530000)])
def test_cost_decimal_formats(value, minor):
    assert parse_cost_minor(value) == minor


@pytest.mark.parametrize("bad", ["abc", "-1", "65,300.00"])
def test_invalid_cost_rejected(bad):
    parsed = parse_file_bytes(json_file([row(cost=bad)]), filename="stock.json")
    assert parsed.invalid_rows


@pytest.mark.parametrize("stock", ["abc", "-1", "1.5"])
def test_invalid_stock_rejected(stock):
    parsed = parse_file_bytes(json_file([row(stock=stock)]), filename="stock.json")
    assert parsed.invalid_rows


def test_missing_internal_code_rejected():
    parsed = parse_file_bytes(json_file([row(internal_code="")]), filename="stock.json")
    assert parsed.invalid_rows[0].reason == "missing internal_code"


def test_unknown_json_key_rejected():
    payload = {"exported_at": T1.isoformat(), "source": "1c", "items": [], "customers": []}
    with pytest.raises(ValueError, match="Unexpected"):
        parse_file_bytes(json.dumps(payload).encode(), filename="stock.json")


async def test_import_matches_by_model_code_and_creates_state():
    variant_id = await seed_variant(code="S938B")
    run = await run_import([row()])
    state = await load_state(variant_id)
    assert run.status == OneCImportRunStatus.COMPLETED
    assert state.own_stock_total == 2
    assert state.own_cost_minor == 6500000


async def test_import_matches_by_sku_alias():
    variant_id = await seed_variant(code="OTHER", alias="SKU-000123")
    await run_import([row()])
    assert (await load_state(variant_id)).own_stock_total == 2


async def test_import_matches_by_barcode_alias():
    variant_id = await seed_variant(code="OTHER", alias="BAR-000123")
    await run_import([row(sku=None)])
    assert (await load_state(variant_id)).own_cost_minor == 6500000


async def test_unknown_item_not_auto_created():
    run = await run_import([row(name="Unknown Device XYZ", sku=None, barcode=None)])
    assert run.unmatched_rows == 1
    assert await count(ProductVariant) == 0


async def test_ambiguous_candidate_blocked():
    await seed_variant(code="S938B")
    await seed_variant(code="S938B", storage=512, name="Samsung Galaxy S25 Ultra S938B 512")
    run = await run_import([row()])
    assert run.ambiguous_rows == 1
    assert await count(VariantInventoryState) == 0


async def test_duplicate_identical_internal_code_deduped():
    await seed_variant(code="S938B")
    run = await run_import([row(), row()])
    assert run.duplicate_rows == 1
    assert await count(OneCItem) == 1


async def test_duplicate_conflicting_internal_code_does_not_update():
    await seed_variant(code="S938B")
    run = await run_import([row(), row(stock=9)])
    assert run.invalid_rows == 1
    assert (await count(VariantInventoryState)) == 1


async def test_same_file_imported_twice_duplicate_without_history_spam():
    await seed_variant(code="S938B")
    first = await run_import([row()])
    second = await run_import([row()])
    assert first.status == OneCImportRunStatus.COMPLETED
    assert second.status == OneCImportRunStatus.DUPLICATE
    assert await count(VariantStockSnapshot) == 1
    assert await count(VariantCostSnapshot) == 1


async def test_unchanged_row_no_extra_snapshots():
    await seed_variant(code="S938B")
    await run_import([row()], exported_at=T1)
    await run_import([row(updated_at=T2.isoformat())], exported_at=T2)
    assert await count(VariantStockSnapshot) == 1
    assert await count(VariantCostSnapshot) == 1


async def test_stock_and_cost_changes_create_history_once():
    variant_id = await seed_variant(code="S938B")
    await run_import([row()], exported_at=T1)
    await run_import([row(stock=1, cost="64000", updated_at=T2.isoformat())], exported_at=T2)
    state = await load_state(variant_id)
    assert state.own_stock_total == 1
    assert state.own_cost_minor == 6400000
    assert await count(VariantStockSnapshot) == 2
    assert await count(VariantCostSnapshot) == 2


async def test_out_of_order_import_does_not_regress_current_state():
    variant_id = await seed_variant(code="S938B")
    await run_import([row(stock=1, cost="64000", updated_at=T2.isoformat())], exported_at=T2)
    await run_import([row(stock=2, cost="65000", updated_at=T1.isoformat())], exported_at=T1)
    state = await load_state(variant_id)
    assert state.own_stock_total == 1
    assert state.own_cost_minor == 6400000


async def test_partial_missing_item_unchanged():
    variant_id = await seed_variant(code="S938B")
    await run_import([row()])
    await run_import([], mode=OneCImportMode.PARTIAL, exported_at=T2)
    assert (await load_state(variant_id)).own_stock_total == 2


async def test_full_missing_item_zeroes_stock_and_retains_cost():
    variant_id = await seed_variant(code="S938B")
    await seed_variant(code="S939B")
    await run_import([row(), row("000124", name="Samsung Galaxy S25 Ultra S939B", sku=None, barcode=None)], mode=OneCImportMode.FULL)
    await run_import([row("000124", name="Samsung Galaxy S25 Ultra S939B", sku=None, barcode=None, updated_at=T2.isoformat())], mode=OneCImportMode.FULL, exported_at=T2)
    state = await load_state(variant_id)
    assert state.own_stock_total == 0
    assert state.own_cost_minor == 6500000


async def test_empty_full_rejected_without_zeroing():
    variant_id = await seed_variant(code="S938B")
    await run_import([row()], mode=OneCImportMode.FULL)
    run = await run_import([], mode=OneCImportMode.FULL, exported_at=T2)
    assert run.status == OneCImportRunStatus.REJECTED
    assert (await load_state(variant_id)).own_stock_total == 2


async def test_mass_zero_protection_rejects_excessive_missing():
    variants = [await seed_variant(code=f"S93{i}B") for i in range(3)]
    await run_import([row(str(i), name=f"Phone S93{i}B", sku=None, barcode=None) for i in range(3)], mode=OneCImportMode.FULL)
    run = await run_import([row("0", name="Phone S930B", sku=None, barcode=None, updated_at=T2.isoformat())], mode=OneCImportMode.FULL, exported_at=T2)
    assert run.status == OneCImportRunStatus.REJECTED
    assert [((await load_state(variant)).own_stock_total) for variant in variants].count(2) == 3


async def test_dry_run_reports_changes_without_mutating():
    variant_id = await seed_variant(code="S938B")
    await run_import([row()], mode=OneCImportMode.FULL)
    run = await run_import([row(stock=1, cost="64000", updated_at=T2.isoformat())], mode=OneCImportMode.FULL, dry_run=True, exported_at=T2)
    state = await load_state(variant_id)
    assert run.dry_run is True
    assert run.would_update_stock == 1
    assert run.would_update_cost == 1
    assert state.own_stock_total == 2


async def test_manual_map_and_unmap():
    variant_id = await seed_variant(code="S938B")
    await run_import([row(name="Unknown", sku=None, barcode=None)])
    async with AsyncSessionLocal() as session:
        item = await session.scalar(select(OneCItem))
        mapped = await map_one_c_item(session, item.id, variant_id)
        assert mapped.match_strategy == OneCItemMatchStrategy.MANUAL
        unmapped = await unmap_one_c_item(session, item.id)
        assert unmapped.match_status == OneCItemMatchStatus.UNMATCHED
    assert await count(AuditLog) >= 2


async def test_explicit_mapping_wins_future_import():
    variant_id = await seed_variant(code="S938B")
    await run_import([row(name="Unknown", sku=None, barcode=None)])
    async with AsyncSessionLocal() as session:
        item = await session.scalar(select(OneCItem))
        await map_one_c_item(session, item.id, variant_id)
    await run_import([row(name="Different Unknown", sku=None, barcode=None, updated_at=T2.isoformat())], exported_at=T2)
    assert (await load_state(variant_id)).own_stock_total == 2


async def test_api_upload_json_and_inventory_endpoints(client):
    variant_id = await seed_variant(code="S938B")
    response = await client.post(
        "/api/v1/1c/import?mode=PARTIAL",
        files={"file": ("stock.json", json_file([row()]), "application/json")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["matched_rows"] == 1
    inventory = await client.get("/api/v1/inventory")
    variant_inventory = await client.get(f"/api/v1/variants/{variant_id}/inventory")
    assert inventory.status_code == 200
    assert variant_inventory.status_code == 200
    assert variant_inventory.json()["state"]["own_cost_minor"] == 6500000


async def test_api_upload_csv_dry_run_and_list_resources(client):
    await seed_variant(code="S938B")
    content = b"internal_code,sku,barcode,name,stock_total,cost,currency,updated_at\n1,S,B,Phone S938B,2,65300,RUB,2026-09-11T14:30:00+00:00\n"
    response = await client.post("/api/v1/1c/import?mode=PARTIAL&dry_run=true", files={"file": ("stock.csv", content, "text/csv")})
    assert response.status_code == 200
    run_id = response.json()["id"]
    assert (await client.get("/api/v1/1c/import-runs")).status_code == 200
    assert (await client.get(f"/api/v1/1c/import-runs/{run_id}")).status_code == 200
    assert (await client.get("/api/v1/1c/items")).json() == []


async def test_api_manual_map_and_unmap(client):
    variant_id = await seed_variant(code="S938B")
    await run_import([row(name="Unknown", sku=None, barcode=None)])
    async with AsyncSessionLocal() as session:
        item = await session.scalar(select(OneCItem))
    mapped = await client.post(f"/api/v1/1c/items/{item.id}/map", json={"variant_id": str(variant_id)})
    unmapped = await client.delete(f"/api/v1/1c/items/{item.id}/map")
    assert mapped.status_code == 200
    assert unmapped.status_code == 200


async def test_e2e_full_import_values():
    a = await seed_variant(code="S938B")
    b = await seed_variant(brand="Apple", name="Apple iPhone", code="A9999")
    await run_import([row("A", name="Samsung S938B", stock=2, cost="65000"), row("B", name="Apple A9999", stock=1, cost="30000")], mode=OneCImportMode.FULL)
    await run_import([row("A", name="Samsung S938B", stock=1, cost="64000", updated_at=T2.isoformat())], mode=OneCImportMode.FULL, exported_at=T2)
    state_a = await load_state(a)
    state_b = await load_state(b)
    assert (state_a.own_stock_total, state_a.own_cost_minor) == (1, 6400000)
    assert (state_b.own_stock_total, state_b.own_cost_minor) == (0, 3000000)


async def load_state(variant_id):
    async with AsyncSessionLocal() as session:
        return await session.get(VariantInventoryState, variant_id)
