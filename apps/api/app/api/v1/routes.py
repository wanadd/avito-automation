import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.integrations.telegram.client import build_telegram_adapter
from app.integrations.telegram.collector import collect_source as collect_telegram_source
from app.integrations.telegram.collector import check_telegram_source
from app.integrations.telegram.types import TelegramClientAdapter
from app.models.conflict import DataConflict
from app.models.enums import ReviewStatus, SupplierSnapshotStatus, SupplierSnapshotType, TelegramCollectionRunStatus
from app.models.match_review import MatchReview
from app.models.product import Product, ProductVariant
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.raw_source_record import RawSourceRecord
from app.models.source import Source
from app.models.supplier import Supplier
from app.models.supplier_offer import SupplierOffer
from app.models.supplier_snapshot import SupplierSnapshot, SupplierSnapshotItem
from app.models.telegram_collection import TelegramCollectionRun
from app.schemas.conflict import DataConflictRead
from app.schemas.matcher import MatchRawRecordSummary, MatchResult, MatchReviewRead
from app.schemas.product import ProductCreate, ProductRead, ProductVariantCreate, ProductVariantRead
from app.schemas.parsed_supplier_item import ParsedSupplierItemRead, ParseSummary
from app.schemas.raw_source_record import RawSourceRecordCreate, RawSourceRecordRead
from app.schemas.source import SourceCreate, SourceRead
from app.schemas.supplier import SupplierCreate, SupplierRead
from app.schemas.supplier_offer import SupplierOfferCreate, SupplierOfferRead
from app.schemas.supplier_snapshot import (
    ProcessSnapshotSummary,
    SupplierSnapshotCreate,
    SupplierSnapshotItemRead,
    SupplierSnapshotRead,
)
from app.schemas.telegram_collection import (
    TelegramCollectRequest,
    TelegramCollectionResult,
    TelegramCollectionRunRead,
    TelegramSourceTestResult,
)
from app.services.offers import upsert_supplier_offer
from app.services.matcher import match_parsed_item, match_raw_record
from app.services.parser.pipeline import parse_raw_record, summarize
from app.services.products import create_variant
from app.services.raw_records import create_raw_record
from app.services.supplier_snapshots import create_snapshot as create_supplier_snapshot
from app.services.supplier_snapshots import process_snapshot

router = APIRouter(prefix="/api/v1")


def get_telegram_adapter() -> TelegramClientAdapter:
    return build_telegram_adapter()


@router.post("/suppliers", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
async def create_supplier(payload: SupplierCreate, session: AsyncSession = Depends(get_db_session)) -> Supplier:
    supplier = Supplier(**payload.model_dump())
    session.add(supplier)
    await session.commit()
    await session.refresh(supplier)
    return supplier


@router.get("/suppliers", response_model=list[SupplierRead])
async def list_suppliers(session: AsyncSession = Depends(get_db_session)) -> list[Supplier]:
    return list(await session.scalars(select(Supplier).order_by(Supplier.created_at)))


@router.get("/suppliers/{supplier_id}", response_model=SupplierRead)
async def get_supplier(supplier_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> Supplier:
    supplier = await session.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return supplier


@router.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(payload: SourceCreate, session: AsyncSession = Depends(get_db_session)) -> Source:
    source = Source(**payload.model_dump())
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


@router.get("/sources", response_model=list[SourceRead])
async def list_sources(session: AsyncSession = Depends(get_db_session)) -> list[Source]:
    return list(await session.scalars(select(Source).order_by(Source.created_at)))


@router.post("/raw-records", response_model=RawSourceRecordRead, status_code=status.HTTP_201_CREATED)
async def create_raw_source_record(
    payload: RawSourceRecordCreate, session: AsyncSession = Depends(get_db_session)
) -> RawSourceRecord:
    return await create_raw_record(session, payload)


@router.get("/raw-records/{record_id}", response_model=RawSourceRecordRead)
async def get_raw_record(record_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> RawSourceRecord:
    record = await session.get(RawSourceRecord, record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw record not found")
    return record


@router.post("/raw-records/{record_id}/parse", response_model=ParseSummary)
async def parse_raw_source_record(record_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> dict:
    try:
        result, items = await parse_raw_record(session, record_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return summarize(record_id, result.total_lines, items)


@router.get("/raw-records/{record_id}/parsed-items", response_model=list[ParsedSupplierItemRead])
async def list_raw_record_parsed_items(
    record_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)
) -> list[ParsedSupplierItem]:
    return list(
        await session.scalars(
            select(ParsedSupplierItem)
            .where(ParsedSupplierItem.raw_source_record_id == record_id)
            .order_by(ParsedSupplierItem.line_number)
        )
    )


@router.get("/parsed-items/{item_id}", response_model=ParsedSupplierItemRead)
async def get_parsed_item(item_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> ParsedSupplierItem:
    item = await session.get(ParsedSupplierItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parsed item not found")
    return item


@router.post("/parsed-items/{item_id}/match", response_model=MatchResult)
async def match_single_parsed_item(item_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> MatchResult:
    try:
        return await match_parsed_item(session, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/raw-records/{record_id}/match", response_model=MatchRawRecordSummary)
async def match_raw_source_record(record_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> dict:
    return await match_raw_record(session, record_id)


@router.post("/sources/{source_id}/collect", response_model=TelegramCollectionResult)
async def collect_source(
    source_id: uuid.UUID,
    payload: TelegramCollectRequest,
    session: AsyncSession = Depends(get_db_session),
    adapter: TelegramClientAdapter = Depends(get_telegram_adapter),
) -> dict:
    try:
        return await collect_telegram_source(
            session, source_id, mode=payload.mode, limit=payload.limit, adapter=adapter
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/sources/{source_id}/telegram-test", response_model=TelegramSourceTestResult)
async def telegram_source_test(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    adapter: TelegramClientAdapter = Depends(get_telegram_adapter),
) -> dict:
    try:
        return await check_telegram_source(session, source_id, adapter)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/telegram-collection-runs", response_model=list[TelegramCollectionRunRead])
async def list_telegram_collection_runs(
    source_id: uuid.UUID | None = None,
    status_filter: TelegramCollectionRunStatus | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[TelegramCollectionRun]:
    statement = select(TelegramCollectionRun).order_by(TelegramCollectionRun.started_at.desc()).limit(min(limit, 500))
    if source_id is not None:
        statement = statement.where(TelegramCollectionRun.source_id == source_id)
    if status_filter is not None:
        statement = statement.where(TelegramCollectionRun.status == status_filter)
    return list(await session.scalars(statement))


@router.get("/telegram-collection-runs/{run_id}", response_model=TelegramCollectionRunRead)
async def get_telegram_collection_run(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)
) -> TelegramCollectionRun:
    run = await session.get(TelegramCollectionRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TelegramCollectionRun not found")
    return run


@router.post("/supplier-snapshots", response_model=SupplierSnapshotRead, status_code=status.HTTP_201_CREATED)
async def create_snapshot(
    payload: SupplierSnapshotCreate, session: AsyncSession = Depends(get_db_session)
) -> SupplierSnapshot:
    return await create_supplier_snapshot(session, payload)


@router.get("/supplier-snapshots", response_model=list[SupplierSnapshotRead])
async def list_supplier_snapshots(
    supplier_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
    status_filter: SupplierSnapshotStatus | None = None,
    snapshot_type: SupplierSnapshotType | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[SupplierSnapshot]:
    statement = select(SupplierSnapshot).order_by(SupplierSnapshot.captured_at.desc()).limit(min(limit, 500))
    if supplier_id is not None:
        statement = statement.where(SupplierSnapshot.supplier_id == supplier_id)
    if source_id is not None:
        statement = statement.where(SupplierSnapshot.source_id == source_id)
    if status_filter is not None:
        statement = statement.where(SupplierSnapshot.status == status_filter)
    if snapshot_type is not None:
        statement = statement.where(SupplierSnapshot.snapshot_type == snapshot_type)
    return list(await session.scalars(statement))


@router.get("/supplier-snapshots/{snapshot_id}", response_model=SupplierSnapshotRead)
async def get_supplier_snapshot(
    snapshot_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)
) -> SupplierSnapshot:
    snapshot = await session.get(SupplierSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SupplierSnapshot not found")
    return snapshot


@router.post("/supplier-snapshots/{snapshot_id}/process", response_model=ProcessSnapshotSummary)
async def process_supplier_snapshot(snapshot_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> dict:
    try:
        return await process_snapshot(session, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/supplier-snapshots/{snapshot_id}/items", response_model=list[SupplierSnapshotItemRead])
async def list_supplier_snapshot_items(
    snapshot_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)
) -> list[SupplierSnapshotItem]:
    return list(
        await session.scalars(
            select(SupplierSnapshotItem)
            .where(SupplierSnapshotItem.snapshot_id == snapshot_id)
            .order_by(SupplierSnapshotItem.created_at)
        )
    )


@router.get("/match-reviews", response_model=list[MatchReviewRead])
async def list_match_reviews(
    status_filter: ReviewStatus | None = None,
    source_id: uuid.UUID | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[MatchReview]:
    statement = select(MatchReview).order_by(MatchReview.created_at).limit(min(limit, 500))
    if status_filter is not None:
        statement = statement.where(MatchReview.status == status_filter)
    if source_id is not None:
        statement = statement.join(ParsedSupplierItem, ParsedSupplierItem.id == MatchReview.parsed_item_id).where(
            ParsedSupplierItem.source_id == source_id
        )
    return list(await session.scalars(statement))


@router.get("/match-reviews/{review_id}", response_model=MatchReviewRead)
async def get_match_review(review_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> MatchReview:
    review = await session.get(MatchReview, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match review not found")
    return review


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(payload: ProductCreate, session: AsyncSession = Depends(get_db_session)) -> Product:
    product = Product(**payload.model_dump())
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@router.get("/products", response_model=list[ProductRead])
async def list_products(session: AsyncSession = Depends(get_db_session)) -> list[Product]:
    return list(await session.scalars(select(Product).order_by(Product.created_at)))


@router.post("/products/{product_id}/variants", response_model=ProductVariantRead, status_code=status.HTTP_201_CREATED)
async def create_product_variant(
    product_id: uuid.UUID, payload: ProductVariantCreate, session: AsyncSession = Depends(get_db_session)
) -> ProductVariant:
    return await create_variant(session, product_id, payload)


@router.get("/variants/{variant_id}", response_model=ProductVariantRead)
async def get_variant(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> ProductVariant:
    variant = await session.get(ProductVariant, variant_id)
    if variant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found")
    return variant


@router.post("/supplier-offers", response_model=SupplierOfferRead, status_code=status.HTTP_201_CREATED)
async def create_supplier_offer(
    payload: SupplierOfferCreate, session: AsyncSession = Depends(get_db_session)
) -> SupplierOffer:
    return await upsert_supplier_offer(session, payload)


@router.get("/variants/{variant_id}/offers", response_model=list[SupplierOfferRead])
async def list_variant_offers(
    variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)
) -> list[SupplierOffer]:
    return list(
        await session.scalars(
            select(SupplierOffer)
            .where(SupplierOffer.product_variant_id == variant_id)
            .order_by(SupplierOffer.created_at)
        )
    )


@router.get("/conflicts", response_model=list[DataConflictRead])
async def list_conflicts(session: AsyncSession = Depends(get_db_session)) -> list[DataConflict]:
    return list(await session.scalars(select(DataConflict).order_by(DataConflict.created_at)))
