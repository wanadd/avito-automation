import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.enums import Availability, ProductCondition, SupplierSnapshotStatus, SupplierSnapshotType
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.product import Product, ProductVariant
from app.models.raw_source_record import RawSourceRecord
from app.models.supplier_offer import SupplierOffer, SupplierOfferSnapshot
from app.models.supplier_snapshot import SupplierSnapshot, SupplierSnapshotItem
from app.services.canonical_key import build_canonical_key
import app.services.supplier_snapshots as snapshot_service
from app.services.supplier_snapshots import process_snapshot

pytestmark = pytest.mark.usefixtures("clean_database")


LINES = {
    "a": "🇰🇼S25 ultra S938B 12/256 silverblue - 65300",
    "b": "🇰🇼S25 ultra S939B 12/512 silverblue - 75300",
    "c": "🇰🇼S25 ultra S940B 16/512 black - 85300",
}


def raw_text(keys: list[str]) -> str:
    return "Samsung 🇰🇷\n" + "\n".join(LINES[key] for key in keys)


async def create_context(client, *, code: str | None = None):
    suffix = code or uuid.uuid4().hex[:8]
    supplier = await client.post("/api/v1/suppliers", json={"code": f"snap-{suffix}", "name": "Snapshot Supplier"})
    assert supplier.status_code == 201, supplier.text
    source = await client.post(
        "/api/v1/sources",
        json={
            "supplier_id": supplier.json()["id"],
            "source_type": "TELEGRAM",
            "external_key": f"tg-{suffix}",
            "name": "Telegram price",
        },
    )
    assert source.status_code == 201, source.text
    return supplier.json(), source.json()


async def create_raw(client, source_id: str, text: str, *, external_id: str | None = None):
    response = await client.post(
        "/api/v1/raw-records",
        json={"source_id": source_id, "external_record_id": external_id or uuid.uuid4().hex, "raw_text": text},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_snapshot(
    client,
    supplier_id: str,
    source_id: str,
    raw_id: str,
    *,
    snapshot_type: str = "FULL",
    captured_at: datetime | None = None,
):
    response = await client.post(
        "/api/v1/supplier-snapshots",
        json={
            "supplier_id": supplier_id,
            "source_id": source_id,
            "raw_source_record_id": raw_id,
            "snapshot_type": snapshot_type,
            "captured_at": (captured_at or datetime.now(UTC)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def process_via_api(client, snapshot_id: str):
    response = await client.post(f"/api/v1/supplier-snapshots/{snapshot_id}/process")
    assert response.status_code == 200, response.text
    return response.json()


async def ingest_snapshot(
    client,
    keys: list[str],
    *,
    snapshot_type: str = "FULL",
    captured_at: datetime | None = None,
    supplier=None,
    source=None,
):
    if supplier is None or source is None:
        supplier, source = await create_context(client)
    raw = await create_raw(client, source["id"], raw_text(keys))
    snapshot = await create_snapshot(
        client, supplier["id"], source["id"], raw["id"], snapshot_type=snapshot_type, captured_at=captured_at
    )
    summary = await process_via_api(client, snapshot["id"])
    return supplier, source, raw, snapshot, summary


async def get_offer_by_code(code: str) -> SupplierOffer:
    async with AsyncSessionLocal() as session:
        variant = await session.scalar(select(ProductVariant).where(ProductVariant.manufacturer_model_code == code))
        assert variant is not None
        offer = await session.scalar(select(SupplierOffer).where(SupplierOffer.product_variant_id == variant.id))
        assert offer is not None
        return offer


async def count_model(model) -> int:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


@pytest.mark.parametrize("snapshot_type", ["FULL", "PARTIAL"])
async def test_snapshot_create_accepts_full_and_partial(client, snapshot_type):
    supplier, source = await create_context(client)
    raw = await create_raw(client, source["id"], raw_text(["a"]))
    snapshot = await create_snapshot(client, supplier["id"], source["id"], raw["id"], snapshot_type=snapshot_type)
    assert snapshot["snapshot_type"] == snapshot_type
    assert snapshot["status"] == "PENDING"


async def test_snapshot_create_is_idempotent_for_same_raw_record(client):
    supplier, source = await create_context(client)
    raw = await create_raw(client, source["id"], raw_text(["a"]))
    first = await create_snapshot(client, supplier["id"], source["id"], raw["id"])
    second = await create_snapshot(client, supplier["id"], source["id"], raw["id"])
    assert first["id"] == second["id"]
    assert await count_model(SupplierSnapshot) == 1


async def test_processing_creates_snapshot_items_for_seen_rows(client):
    _, _, _, snapshot, summary = await ingest_snapshot(client, ["a", "b"])
    assert summary["status"] == "COMPLETED"
    response = await client.get(f"/api/v1/supplier-snapshots/{snapshot['id']}/items")
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert {item["item_status"] for item in response.json()} == {"SEEN"}


async def test_full_snapshot_marks_seen_offers_in_stock(client):
    await ingest_snapshot(client, ["a"])
    offer = await get_offer_by_code("S938B")
    assert offer.availability == Availability.IN_STOCK
    assert offer.consecutive_missing_count == 0
    assert offer.last_seen_snapshot_id is not None


async def test_full_snapshot_missing_once_moves_to_suspect_missing(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a", "b"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    await ingest_snapshot(client, ["a"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC))
    offer = await get_offer_by_code("S939B")
    assert offer.availability == Availability.SUSPECT_MISSING
    assert offer.consecutive_missing_count == 1


async def test_full_snapshot_missing_twice_moves_to_out_of_stock(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a", "b"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    await ingest_snapshot(client, ["a"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC))
    _, _, _, _, summary = await ingest_snapshot(
        client, ["a"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 12, tzinfo=UTC)
    )
    offer = await get_offer_by_code("S939B")
    assert offer.availability == Availability.OUT_OF_STOCK
    assert offer.consecutive_missing_count == 2
    assert summary["moved_to_out_of_stock"] == 1


async def test_restored_offer_returns_to_in_stock_and_resets_counter(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a", "b"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    await ingest_snapshot(client, ["a"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC))
    await ingest_snapshot(client, ["a"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 12, tzinfo=UTC))
    _, _, _, _, summary = await ingest_snapshot(
        client, ["a", "b"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 13, tzinfo=UTC)
    )
    offer = await get_offer_by_code("S939B")
    assert offer.availability == Availability.IN_STOCK
    assert offer.consecutive_missing_count == 0
    assert summary["restored"] == 1


async def test_partial_snapshot_never_marks_absent_offers_missing(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a", "b"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    await ingest_snapshot(
        client, ["a"], supplier=supplier, source=source, snapshot_type="PARTIAL", captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC)
    )
    offer = await get_offer_by_code("S939B")
    assert offer.availability == Availability.IN_STOCK
    assert offer.consecutive_missing_count == 0


async def test_partial_snapshot_marks_seen_offer_in_stock(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    async with AsyncSessionLocal() as session:
        offer = await session.scalar(select(SupplierOffer))
        offer.availability = Availability.UNKNOWN
        await session.commit()
    await ingest_snapshot(
        client, ["a"], supplier=supplier, source=source, snapshot_type="PARTIAL", captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC)
    )
    offer = await get_offer_by_code("S938B")
    assert offer.availability == Availability.IN_STOCK


async def test_empty_full_snapshot_is_rejected_and_does_not_mark_missing(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    raw = await create_raw(client, source["id"], "")
    snapshot = await create_snapshot(
        client, supplier["id"], source["id"], raw["id"], captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC)
    )
    summary = await process_via_api(client, snapshot["id"])
    offer = await get_offer_by_code("S938B")
    assert summary["status"] == "REJECTED"
    assert summary["quality_gate_passed"] is False
    assert offer.availability == Availability.IN_STOCK


async def test_low_quality_full_snapshot_is_rejected_without_missing_transition(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    low_quality_text = (
        raw_text(["a"])
        + "\n🇮🇳S26 S942B 12/256 violet - 63500"
        + "\n🇮🇳S26 S942B 12/256 violet - 64500"
    )
    raw = await create_raw(client, source["id"], low_quality_text)
    snapshot = await create_snapshot(
        client, supplier["id"], source["id"], raw["id"], captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC)
    )
    summary = await process_via_api(client, snapshot["id"])
    offer = await get_offer_by_code("S938B")
    assert summary["status"] == "REJECTED"
    assert offer.availability == Availability.IN_STOCK
    assert offer.consecutive_missing_count == 0


async def test_out_of_order_older_snapshot_does_not_increment_missing(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a", "b"], captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC))
    await ingest_snapshot(client, ["a"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    offer = await get_offer_by_code("S939B")
    assert offer.availability == Availability.IN_STOCK
    assert offer.consecutive_missing_count == 0


async def test_reprocessing_completed_snapshot_is_idempotent(client):
    supplier, source, raw, snapshot, _ = await ingest_snapshot(client, ["a", "b"])
    first_count = await count_model(SupplierSnapshotItem)
    first_offer_count = await count_model(SupplierOffer)
    second = await process_via_api(client, snapshot["id"])
    assert second["status"] == "COMPLETED"
    assert await count_model(SupplierSnapshotItem) == first_count
    assert await count_model(SupplierOffer) == first_offer_count
    assert raw["source_id"] == source["id"]
    assert supplier["id"]


async def test_processing_nonexistent_snapshot_returns_404(client):
    response = await client.post(f"/api/v1/supplier-snapshots/{uuid.uuid4()}/process")
    assert response.status_code == 404


async def test_get_and_list_snapshot_endpoints(client):
    supplier, source, _, snapshot, _ = await ingest_snapshot(client, ["a"])
    single = await client.get(f"/api/v1/supplier-snapshots/{snapshot['id']}")
    listing = await client.get(f"/api/v1/supplier-snapshots?supplier_id={supplier['id']}&source_id={source['id']}")
    assert single.status_code == 200
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == snapshot["id"]


@pytest.mark.parametrize(
    ("status_filter", "expected_count"),
    [("COMPLETED", 1), ("REJECTED", 0), ("PENDING", 0)],
)
async def test_list_snapshot_status_filter(client, status_filter, expected_count):
    await ingest_snapshot(client, ["a"])
    response = await client.get(f"/api/v1/supplier-snapshots?status_filter={status_filter}")
    assert response.status_code == 200
    assert len(response.json()) == expected_count


async def test_unknown_condition_snapshot_creates_null_condition_variant(client):
    await ingest_snapshot(client, ["a"])
    async with AsyncSessionLocal() as session:
        item = await session.scalar(select(ParsedSupplierItem).where(ParsedSupplierItem.raw_line.contains("S25 ultra")))
        variant = await session.scalar(select(ProductVariant).where(ProductVariant.manufacturer_model_code == "S938B"))
    assert item.condition is None
    assert variant.condition is None


@pytest.mark.parametrize("condition", [ProductCondition.NEW, ProductCondition.USED, ProductCondition.REFURBISHED])
async def test_explicit_condition_offer_remains_distinct_in_snapshot(client, condition):
    supplier, source = await create_context(client)
    product = await create_product_variant(condition)
    raw = await create_raw(client, source["id"], raw_text(["a"]))
    snapshot = await create_snapshot(client, supplier["id"], source["id"], raw["id"])
    summary = await process_via_api(client, snapshot["id"])
    assert summary["review"] == 1
    async with AsyncSessionLocal() as session:
        variant = await session.get(ProductVariant, product)
    assert variant.condition == condition


async def create_product_variant(condition: ProductCondition) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        product = Product(brand="Samsung", canonical_name="Galaxy S25 Ultra", category="smartphone")
        session.add(product)
        await session.flush()
        variant = ProductVariant(
            product_id=product.id,
            manufacturer_model_code="S938B",
            ram_gb=12,
            storage_gb=256,
            color_raw="Silver Blue",
            color_normalized="Silver Blue",
            region_code="KW",
            condition=condition,
            canonical_key=build_canonical_key(
                brand=product.brand,
                canonical_name=product.canonical_name,
                manufacturer_model_code="S938B",
                ram_gb=12,
                storage_gb=256,
                color_normalized="Silver Blue",
                region_code="KW",
                condition=condition,
            ),
        )
        session.add(variant)
        await session.commit()
        return variant.id


async def test_unknown_condition_repeated_snapshot_stays_idempotent(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    await ingest_snapshot(client, ["a"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC))
    async with AsyncSessionLocal() as session:
        variant_count = await session.scalar(select(func.count()).select_from(ProductVariant))
        offer_count = await session.scalar(select(func.count()).select_from(SupplierOffer))
        variant = await session.scalar(select(ProductVariant))
    assert variant_count == 1
    assert offer_count == 1
    assert variant.condition is None


async def test_conflict_rows_do_not_create_offers(client):
    supplier, source = await create_context(client)
    raw = await create_raw(
        client,
        source["id"],
        "Samsung 🇰🇷\n🇮🇳S26 S942B 12/256 violet - 63500\n🇮🇳S26 S942B 12/256 violet - 64500",
    )
    snapshot = await create_snapshot(client, supplier["id"], source["id"], raw["id"])
    summary = await process_via_api(client, snapshot["id"])
    assert summary["conflict"] == 2
    assert await count_model(SupplierOffer) == 0


async def test_conflict_snapshot_items_have_no_offer(client):
    supplier, source = await create_context(client)
    raw = await create_raw(
        client,
        source["id"],
        "Samsung 🇰🇷\n🇮🇳S26 S942B 12/256 violet - 63500\n🇮🇳S26 S942B 12/256 violet - 64500",
    )
    snapshot = await create_snapshot(client, supplier["id"], source["id"], raw["id"])
    await process_via_api(client, snapshot["id"])
    async with AsyncSessionLocal() as session:
        items = list(await session.scalars(select(SupplierSnapshotItem)))
    assert len(items) == 2
    assert all(item.supplier_offer_id is None for item in items)


async def test_availability_transition_records_snapshots_and_audit_logs(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a", "b"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    await ingest_snapshot(client, ["a"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC))
    async with AsyncSessionLocal() as session:
        audits = await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "SUPPLIER_OFFER_SUSPECT_MISSING")
        )
        snapshots = await session.scalar(select(func.count()).select_from(SupplierOfferSnapshot))
    assert audits == 1
    assert snapshots >= 3


async def test_seen_offer_records_last_processed_snapshot_at(client):
    await ingest_snapshot(client, ["a"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    offer = await get_offer_by_code("S938B")
    assert offer.last_processed_snapshot_at == datetime(2026, 9, 11, 10, tzinfo=UTC)


async def test_missing_offer_records_last_missing_snapshot_id(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a", "b"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    _, _, _, snapshot, _ = await ingest_snapshot(
        client, ["a"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC)
    )
    offer = await get_offer_by_code("S939B")
    assert str(offer.last_missing_snapshot_id) == snapshot["id"]


async def test_concurrent_processing_does_not_duplicate_offers(client):
    supplier, source = await create_context(client)
    raw = await create_raw(client, source["id"], raw_text(["a"]))
    snapshot = await create_snapshot(client, supplier["id"], source["id"], raw["id"])

    async def run_once():
        async with AsyncSessionLocal() as session:
            return await process_snapshot(session, uuid.UUID(snapshot["id"]))

    await asyncio.gather(run_once(), run_once())
    assert await count_model(SupplierOffer) == 1
    assert await count_model(SupplierSnapshotItem) == 1


async def test_failed_snapshot_status_is_set_on_processing_error(client, monkeypatch):
    supplier, source = await create_context(client)
    raw = await create_raw(client, source["id"], raw_text(["a"]))
    snapshot = await create_snapshot(client, supplier["id"], source["id"], raw["id"])

    async def fail_parse(*args, **kwargs):
        raise RuntimeError("forced parser failure")

    monkeypatch.setattr(snapshot_service, "parse_raw_record", fail_parse)
    async with AsyncSessionLocal() as session:
        with pytest.raises(RuntimeError):
            await snapshot_service.process_snapshot(session, uuid.UUID(snapshot["id"]))
    async with AsyncSessionLocal() as session:
        stored = await session.get(SupplierSnapshot, uuid.UUID(snapshot["id"]))
    assert stored.status == SupplierSnapshotStatus.FAILED


async def test_full_snapshot_summary_counts_seen_and_matched(client):
    _, _, _, _, summary = await ingest_snapshot(client, ["a", "b", "c"])
    assert summary["offers_seen"] == 3
    assert summary["auto_created"] == 3
    assert summary["parsed"] == 3
    assert summary["quality_gate_passed"] is True


async def test_full_snapshot_summary_reports_created_then_updated(client):
    supplier, source, *_ = await ingest_snapshot(client, ["a"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    _, _, _, _, summary = await ingest_snapshot(
        client, ["a"], supplier=supplier, source=source, captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC)
    )
    assert summary["offers_created"] == 0
    assert summary["offers_updated"] == 1


async def test_snapshot_items_keep_match_status(client):
    _, _, _, snapshot, _ = await ingest_snapshot(client, ["a"])
    async with AsyncSessionLocal() as session:
        item = await session.scalar(select(SupplierSnapshotItem).where(SupplierSnapshotItem.snapshot_id == uuid.UUID(snapshot["id"])))
    assert item.match_status in {"AUTO_CREATED", "EXACT_MATCH"}


async def test_missing_threshold_is_supplier_scoped(client):
    supplier_one, source_one, *_ = await ingest_snapshot(client, ["a", "b"], captured_at=datetime(2026, 9, 11, 10, tzinfo=UTC))
    await ingest_snapshot(client, ["a"], supplier=supplier_one, source=source_one, captured_at=datetime(2026, 9, 11, 11, tzinfo=UTC))
    await ingest_snapshot(client, ["a"])
    async with AsyncSessionLocal() as session:
        suspect = await session.scalar(
            select(func.count()).select_from(SupplierOffer).where(SupplierOffer.availability == Availability.SUSPECT_MISSING)
        )
        in_stock = await session.scalar(
            select(func.count()).select_from(SupplierOffer).where(SupplierOffer.availability == Availability.IN_STOCK)
        )
    assert suspect == 1
    assert in_stock >= 2


@pytest.mark.parametrize("offset", [1, 2, 3])
async def test_snapshot_captured_at_is_preserved(client, offset):
    captured = datetime(2026, 9, 11, 10, tzinfo=UTC) + timedelta(hours=offset)
    _, _, _, snapshot, _ = await ingest_snapshot(client, ["a"], captured_at=captured)
    response = await client.get(f"/api/v1/supplier-snapshots/{snapshot['id']}")
    assert response.status_code == 200
    assert response.json()["captured_at"].startswith(captured.isoformat().replace("+00:00", "Z")[:13])
