import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.integrations.telegram.client import build_telegram_adapter
from app.integrations.telegram.collector import check_telegram_source
from app.integrations.telegram.types import TelegramClientAdapter
from app.integrations.one_c.importer import import_one_c_file, map_one_c_item, unmap_one_c_item
from app.jobs.queue import QueueAdapter, RQQueueAdapter
from app.jobs.service import create_manual_job, operations_status, retry_failed_job, source_status
from app.models.conflict import DataConflict
from app.models.content import ProductContentDraft
from app.models.enums import (
    GenericReadinessStatus,
    ReviewStatus,
    SourceCollectionJobStatus,
    SourceCollectionJobType,
    OneCImportMode,
    OneCImportRunStatus,
    OneCItemMatchStatus,
    SupplierSnapshotStatus,
    SupplierSnapshotType,
    TelegramCollectionRunStatus,
)
from app.models.match_review import MatchReview
from app.models.one_c import OneCImportRun, OneCItem, VariantCostSnapshot, VariantInventoryState, VariantStockSnapshot
from app.models.pricing import PricingDecisionHistory, PricingPolicy, VariantPricingState
from app.models.product import Product, ProductVariant
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.raw_source_record import RawSourceRecord
from app.models.source import Source
from app.models.source_collection_job import SourceCollectionJob
from app.models.supplier import Supplier
from app.models.supplier_offer import SupplierOffer
from app.models.supplier_snapshot import SupplierSnapshot, SupplierSnapshotItem
from app.models.telegram_collection import TelegramCollectionRun
from app.schemas.conflict import DataConflictRead
from app.schemas.content import (
    BulkContentResult,
    GenericListingDraftRead,
    ImageAssetCreate,
    ImageSetCreate,
    ManualFactOverrideRequest,
    ProductContentDraftRead,
    ProductContentFactsRead,
    ProductFactOverrideRead,
    ProductImageAssetRead,
    ProductImageSetRead,
    RejectContentRequest,
)
from app.schemas.matcher import MatchRawRecordSummary, MatchResult, MatchReviewRead
from app.schemas.one_c import InventoryListItem, InventoryStateRead, OneCImportRunRead, OneCItemRead, OneCMapRequest, VariantInventoryRead
from app.schemas.pricing import (
    BulkPricingResult,
    ManualPriceRequest,
    PricingDecisionHistoryRead,
    PricingPolicyCreate,
    PricingPolicyPatch,
    PricingPolicyRead,
    VariantPricingStateRead,
)
from app.schemas.product import ProductCreate, ProductRead, ProductVariantCreate, ProductVariantRead
from app.schemas.parsed_supplier_item import ParsedSupplierItemRead, ParseSummary
from app.schemas.raw_source_record import RawSourceRecordCreate, RawSourceRecordRead
from app.schemas.source import SourceCreate, SourceRead
from app.schemas.source_collection_job import OperationsStatusRead, SourceCollectionJobRead, SourceStatusRead
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
from app.services.pricing.engine import (
    clear_manual_price,
    create_pricing_policy,
    recalculate_all_pricing,
    recalculate_variant_pricing,
    set_manual_price,
    update_pricing_policy,
)
from app.services.content import (
    approve_content_draft,
    approve_image_set,
    approve_listing,
    build_generic_listing,
    create_image_asset as create_content_image_asset,
    create_image_set as create_content_image_set,
    generate_content_draft,
    latest_facts,
    list_variant_drafts,
    list_variant_image_sets,
    list_variant_listings,
    rebuild_content_facts,
    recalculate_listing_readiness_bulk,
    reject_content_draft,
    set_manual_fact_override,
    validate_content_draft,
    validate_image_set,
    validate_listing,
)

router = APIRouter(prefix="/api/v1")


def get_telegram_adapter() -> TelegramClientAdapter:
    return build_telegram_adapter()


def get_queue_adapter() -> QueueAdapter:
    return RQQueueAdapter()


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


@router.get("/sources/{source_id}/status", response_model=SourceStatusRead)
async def get_source_status(source_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> dict:
    try:
        return await source_status(session, source_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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


@router.post("/sources/{source_id}/collect", response_model=SourceCollectionJobRead)
async def collect_source(
    source_id: uuid.UUID,
    payload: TelegramCollectRequest,
    session: AsyncSession = Depends(get_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> SourceCollectionJob:
    try:
        return await create_manual_job(session, queue, source_id=source_id, mode=payload.mode, limit=payload.limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/source-collection-jobs", response_model=list[SourceCollectionJobRead])
async def list_source_collection_jobs(
    source_id: uuid.UUID | None = None,
    status_filter: SourceCollectionJobStatus | None = None,
    job_type: SourceCollectionJobType | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[SourceCollectionJob]:
    statement = select(SourceCollectionJob).order_by(SourceCollectionJob.created_at.desc()).limit(min(limit, 500))
    if source_id is not None:
        statement = statement.where(SourceCollectionJob.source_id == source_id)
    if status_filter is not None:
        statement = statement.where(SourceCollectionJob.status == status_filter)
    if job_type is not None:
        statement = statement.where(SourceCollectionJob.job_type == job_type)
    return list(await session.scalars(statement))


@router.get("/source-collection-jobs/{job_id}", response_model=SourceCollectionJobRead)
async def get_source_collection_job(
    job_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)
) -> SourceCollectionJob:
    job = await session.get(SourceCollectionJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SourceCollectionJob not found")
    return job


@router.post("/source-collection-jobs/{job_id}/retry", response_model=SourceCollectionJobRead)
async def retry_source_collection_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> SourceCollectionJob:
    try:
        return await retry_failed_job(session, queue, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/operations/status", response_model=OperationsStatusRead)
async def get_operations_status(session: AsyncSession = Depends(get_db_session)) -> dict:
    return await operations_status(session)


@router.post("/pricing/policies", response_model=PricingPolicyRead, status_code=status.HTTP_201_CREATED)
async def create_pricing_policy_endpoint(
    payload: PricingPolicyCreate, session: AsyncSession = Depends(get_db_session)
) -> PricingPolicy:
    try:
        return await create_pricing_policy(session, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/pricing/policies", response_model=list[PricingPolicyRead])
async def list_pricing_policies(session: AsyncSession = Depends(get_db_session)) -> list[PricingPolicy]:
    return list(await session.scalars(select(PricingPolicy).order_by(PricingPolicy.created_at)))


@router.get("/pricing/policies/{policy_id}", response_model=PricingPolicyRead)
async def get_pricing_policy(policy_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> PricingPolicy:
    policy = await session.get(PricingPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PricingPolicy not found")
    return policy


@router.patch("/pricing/policies/{policy_id}", response_model=PricingPolicyRead)
async def patch_pricing_policy(
    policy_id: uuid.UUID, payload: PricingPolicyPatch, session: AsyncSession = Depends(get_db_session)
) -> PricingPolicy:
    try:
        return await update_pricing_policy(session, policy_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/pricing/variants/{variant_id}", response_model=VariantPricingStateRead)
async def get_variant_pricing(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> VariantPricingState:
    state = await session.get(VariantPricingState, variant_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VariantPricingState not found")
    return state


@router.post("/pricing/variants/{variant_id}/recalculate", response_model=VariantPricingStateRead)
async def recalculate_variant_pricing_endpoint(
    variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)
) -> VariantPricingState:
    try:
        return await recalculate_variant_pricing(session, variant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/pricing/variants/{variant_id}/history", response_model=list[PricingDecisionHistoryRead])
async def get_variant_pricing_history(
    variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)
) -> list[PricingDecisionHistory]:
    return list(
        await session.scalars(
            select(PricingDecisionHistory)
            .where(PricingDecisionHistory.product_variant_id == variant_id)
            .order_by(PricingDecisionHistory.created_at.desc())
        )
    )


@router.put("/pricing/variants/{variant_id}/manual-price", response_model=VariantPricingStateRead)
async def put_manual_price(
    variant_id: uuid.UUID, payload: ManualPriceRequest, session: AsyncSession = Depends(get_db_session)
) -> VariantPricingState:
    await set_manual_price(session, variant_id, payload.manual_price_minor, payload.note)
    state = await session.get(VariantPricingState, variant_id)
    return state


@router.delete("/pricing/variants/{variant_id}/manual-price", response_model=VariantPricingStateRead)
async def delete_manual_price(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> VariantPricingState:
    await clear_manual_price(session, variant_id)
    state = await session.get(VariantPricingState, variant_id)
    return state


@router.post("/pricing/recalculate", response_model=BulkPricingResult)
async def recalculate_pricing(session: AsyncSession = Depends(get_db_session)) -> dict:
    return await recalculate_all_pricing(session)


@router.post("/1c/import", response_model=OneCImportRunRead)
async def import_one_c_export(
    file: UploadFile = File(...),
    mode: OneCImportMode = OneCImportMode.PARTIAL,
    dry_run: bool = False,
    session: AsyncSession = Depends(get_db_session),
) -> OneCImportRun:
    content = await file.read()
    try:
        return await import_one_c_file(session, content, filename=file.filename, mode=mode, dry_run=dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/1c/import-runs", response_model=list[OneCImportRunRead])
async def list_one_c_import_runs(
    status_filter: OneCImportRunStatus | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[OneCImportRun]:
    statement = select(OneCImportRun).order_by(OneCImportRun.created_at.desc()).limit(min(limit, 500))
    if status_filter is not None:
        statement = statement.where(OneCImportRun.status == status_filter)
    return list(await session.scalars(statement))


@router.get("/1c/import-runs/{run_id}", response_model=OneCImportRunRead)
async def get_one_c_import_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> OneCImportRun:
    run = await session.get(OneCImportRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OneCImportRun not found")
    return run


@router.get("/1c/items", response_model=list[OneCItemRead])
async def list_one_c_items(
    match_status: OneCItemMatchStatus | None = None,
    internal_code: str | None = None,
    search: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[OneCItem]:
    statement = select(OneCItem).order_by(OneCItem.internal_code).limit(min(limit, 500))
    if match_status is not None:
        statement = statement.where(OneCItem.match_status == match_status)
    if internal_code is not None:
        statement = statement.where(OneCItem.internal_code == internal_code)
    if search is not None:
        statement = statement.where(OneCItem.normalized_name.contains(search.lower()))
    return list(await session.scalars(statement))


@router.get("/1c/items/{item_id}", response_model=OneCItemRead)
async def get_one_c_item(item_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> OneCItem:
    item = await session.get(OneCItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OneCItem not found")
    return item


@router.post("/1c/items/{item_id}/map", response_model=OneCItemRead)
async def map_one_c_item_endpoint(
    item_id: uuid.UUID, payload: OneCMapRequest, session: AsyncSession = Depends(get_db_session)
) -> OneCItem:
    try:
        return await map_one_c_item(session, item_id, payload.variant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/1c/items/{item_id}/map", response_model=OneCItemRead)
async def unmap_one_c_item_endpoint(item_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> OneCItem:
    try:
        return await unmap_one_c_item(session, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/inventory", response_model=list[InventoryListItem])
async def list_inventory(
    variant_id: uuid.UUID | None = None,
    in_stock_only: bool = False,
    search: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    statement = select(VariantInventoryState, ProductVariant).join(ProductVariant)
    if variant_id is not None:
        statement = statement.where(VariantInventoryState.variant_id == variant_id)
    if in_stock_only:
        statement = statement.where(VariantInventoryState.own_stock_total > 0)
    if search is not None:
        statement = statement.join(Product).where(Product.canonical_name.ilike(f"%{search}%"))
    rows = (await session.execute(statement.limit(min(limit, 500)))).all()
    return [{"state": state, "variant": variant} for state, variant in rows]


@router.get("/variants/{variant_id}/inventory", response_model=VariantInventoryRead)
async def get_variant_inventory(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> dict:
    state = await session.get(VariantInventoryState, variant_id)
    stock = list(
        await session.scalars(
            select(VariantStockSnapshot)
            .where(VariantStockSnapshot.variant_id == variant_id)
            .order_by(VariantStockSnapshot.created_at.desc())
            .limit(20)
        )
    )
    cost = list(
        await session.scalars(
            select(VariantCostSnapshot)
            .where(VariantCostSnapshot.variant_id == variant_id)
            .order_by(VariantCostSnapshot.created_at.desc())
            .limit(20)
        )
    )
    return {
        "state": state,
        "recent_stock": [
            {"id": snap.id, "stock_total": snap.stock_total, "source_updated_at": snap.source_updated_at}
            for snap in stock
        ],
        "recent_cost": [
            {"id": snap.id, "cost_minor": snap.cost_minor, "currency": snap.currency, "source_updated_at": snap.source_updated_at}
            for snap in cost
        ],
    }


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


@router.get("/content/variants/{variant_id}/facts", response_model=ProductContentFactsRead)
async def get_content_facts(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    facts = await latest_facts(session, variant_id)
    if facts is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ProductContentFacts not found")
    return facts


@router.post("/content/variants/{variant_id}/facts/rebuild", response_model=ProductContentFactsRead)
async def rebuild_content_facts_endpoint(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return await rebuild_content_facts(session, variant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/content/variants/{variant_id}/facts/manual-override", response_model=ProductFactOverrideRead)
async def set_manual_fact_override_endpoint(
    variant_id: uuid.UUID, payload: ManualFactOverrideRequest, session: AsyncSession = Depends(get_db_session)
):
    try:
        return await set_manual_fact_override(session, variant_id, payload.field, payload.value, payload.operator, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/content/variants/{variant_id}/drafts", response_model=list[ProductContentDraftRead])
async def list_content_drafts(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    return await list_variant_drafts(session, variant_id)


@router.post("/content/variants/{variant_id}/generate", response_model=ProductContentDraftRead)
async def generate_content_endpoint(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return await generate_content_draft(session, variant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/content/drafts/{draft_id}", response_model=ProductContentDraftRead)
async def get_content_draft(draft_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    draft = await session.get(ProductContentDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ProductContentDraft not found")
    return draft


@router.post("/content/drafts/{draft_id}/validate", response_model=ProductContentDraftRead)
async def validate_content_endpoint(draft_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return await validate_content_draft(session, draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/content/drafts/{draft_id}/approve", response_model=ProductContentDraftRead)
async def approve_content_endpoint(draft_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return await approve_content_draft(session, draft_id)
    except ValueError as exc:
        code = status.HTTP_409_CONFLICT if str(exc) in {"STALE_FACTS", "CONTENT_INVALID"} else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/content/drafts/{draft_id}/reject", response_model=ProductContentDraftRead)
async def reject_content_endpoint(
    draft_id: uuid.UUID, payload: RejectContentRequest, session: AsyncSession = Depends(get_db_session)
):
    try:
        return await reject_content_draft(session, draft_id, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/content/variants/{variant_id}/images", response_model=list[ProductImageSetRead])
async def list_image_sets(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    return await list_variant_image_sets(session, variant_id)


@router.post("/content/variants/{variant_id}/image-assets", response_model=ProductImageAssetRead, status_code=status.HTTP_201_CREATED)
async def create_image_asset_endpoint(
    variant_id: uuid.UUID, payload: ImageAssetCreate, session: AsyncSession = Depends(get_db_session)
):
    try:
        return await create_content_image_asset(session, variant_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/content/variants/{variant_id}/image-sets", response_model=ProductImageSetRead, status_code=status.HTTP_201_CREATED)
async def create_image_set_endpoint(
    variant_id: uuid.UUID, payload: ImageSetCreate, session: AsyncSession = Depends(get_db_session)
):
    try:
        return await create_content_image_set(session, variant_id, payload.image_asset_ids, payload.cover_image_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/content/image-sets/{image_set_id}/validate", response_model=ProductImageSetRead)
async def validate_image_set_endpoint(image_set_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return await validate_image_set(session, image_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/content/image-sets/{image_set_id}/approve", response_model=ProductImageSetRead)
async def approve_image_set_endpoint(image_set_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return await approve_image_set(session, image_set_id)
    except ValueError as exc:
        code = status.HTTP_409_CONFLICT if str(exc) == "IMAGE_SET_INVALID" else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/listings/variants/{variant_id}", response_model=list[GenericListingDraftRead])
async def get_variant_listings(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    return await list_variant_listings(session, variant_id)


@router.post("/listings/variants/{variant_id}/build", response_model=GenericListingDraftRead)
async def build_listing_endpoint(variant_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return await build_generic_listing(session, variant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/listings", response_model=list[GenericListingDraftRead])
async def list_listings(
    readiness: GenericReadinessStatus | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
):
    return await list_variant_listings(session, status_filter=readiness, limit=limit)


@router.post("/listings/{listing_id}/validate", response_model=GenericListingDraftRead)
async def validate_listing_endpoint(listing_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return await validate_listing(session, listing_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/listings/{listing_id}/approve", response_model=GenericListingDraftRead)
async def approve_listing_endpoint(listing_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return await approve_listing(session, listing_id)
    except ValueError as exc:
        code = status.HTTP_409_CONFLICT if str(exc) in {"PRICING_NOT_READY", "STALE_FACTS"} else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/listings/bulk/recalculate", response_model=BulkContentResult)
async def bulk_recalculate_listings(session: AsyncSession = Depends(get_db_session)):
    return await recalculate_listing_readiness_bulk(session)


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
