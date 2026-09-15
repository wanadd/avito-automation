import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
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
from app.models.content import GenericListingDraft, ProductContentDraft
from app.models.enums import (
    GenericListingStatus,
    GenericReadinessStatus,
    Marketplace,
    PublicationJobStatus,
    ReviewStatus,
    SourceCollectionJobStatus,
    SourceCollectionJobType,
    OneCImportMode,
    OneCImportRunStatus,
    OneCItemMatchStatus,
    OperationalAlertStatus,
    OperatorRole,
    SupplierSnapshotStatus,
    SupplierSnapshotType,
    TelegramCollectionRunStatus,
)
from app.models.match_review import MatchReview
from app.models.manual_import import ManualImportBatch
from app.models.one_c import OneCImportRun, OneCItem, VariantCostSnapshot, VariantInventoryState, VariantStockSnapshot
from app.models.pricing import PricingDecisionHistory, PricingPolicy, VariantPricingState
from app.models.product import Product, ProductVariant
from app.models.publication import MarketplaceListingBinding, OperationalAlert, PublicationIntent, PublicationJob
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.raw_source_record import RawSourceRecord
from app.models.source import Source
from app.models.source_collection_job import SourceCollectionJob
from app.models.supplier import Supplier
from app.models.supplier_offer import SupplierOffer
from app.models.supplier_snapshot import SupplierSnapshot, SupplierSnapshotItem
from app.models.telegram_collection import TelegramCollectionRun
from app.models.telegram_price import TelegramPriceBatch, TelegramPriceMessage, TelegramPriceSource
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
from app.schemas.onboarding import (
    ConfirmImportRequest,
    ConflictResolveRequest,
    ManualImportBatchRead,
    MatchReviewAcceptRequest,
    OneCManualPreviewRequest,
    PilotReadinessReport,
    ProductOnboardingRequest,
    ProductOnboardingResult,
    TelegramManualPreviewRequest,
)
from app.schemas.operator import OperatorCreateRequest, OperatorListItem, OperatorLoginRequest, OperatorSessionRead, OperatorUserRead
from app.schemas.operator_read import AlertActionRequest, BackupSmokeRead, DashboardRead, Page, SettingsRead, SystemHealthRead
from app.schemas.pricing import (
    BulkPricingResult,
    ManualPriceRequest,
    PricingDecisionHistoryRead,
    PricingPolicyCreate,
    PricingPolicyPatch,
    PricingPolicyRead,
    VariantPricingStateRead,
)
from app.schemas.publication import (
    ControlOverviewRead,
    MarketplaceListingBindingRead,
    OperationalAlertRead,
    PublicationIntentCreate,
    PublicationIntentRead,
    PublicationJobRead,
    ReconcileRequest,
    RetryCancelRequest,
)
from app.schemas.product import ProductCreate, ProductRead, ProductVariantCreate, ProductVariantRead
from app.schemas.parsed_supplier_item import ParsedSupplierItemRead, ParseSummary
from app.schemas.raw_source_record import RawSourceRecordCreate, RawSourceRecordRead
from app.schemas.source import SourceCreate, SourceRead
from app.schemas.source_collection_job import OperationsStatusRead, SourceCollectionJobRead, SourceStatusRead
from app.schemas.supplier import OperatorSupplierCreate, SupplierCreate, SupplierRead
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
from app.schemas.telegram_prices import (
    TelegramPriceBatchRead,
    TelegramPriceMessageRead,
    TelegramPriceSourceMapRequest,
    TelegramPriceSourceRead,
    TelegramPriceStatusRead,
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
from app.services.publication import (
    cancel_publication_job,
    control_overview,
    create_publication_intent,
    process_publication_job,
    reconcile_listing,
    retry_publication_job,
    review_queue,
)
from app.services.suppliers import create_operator_supplier
from app.services.operator_auth import (
    AuthenticatedOperator,
    authenticate_operator,
    create_operator_user,
    get_authenticated_operator,
    require_role,
    revoke_current_session,
)
from app.services.operator_read import (
    alert_page,
    audit_page,
    backup_smoke,
    dashboard,
    inventory_list,
    product_list,
    publication_job_detail,
    publication_jobs,
    pricing_list,
    settings_read,
    source_health,
    supplier_list,
    system_health,
    update_alert_status,
    variant_detail,
)
from app.services.onboarding import (
    confirm_one_c_manual_import,
    confirm_telegram_manual_import,
    accept_match_review,
    listing_dry_run_validation,
    onboard_product,
    pilot_readiness,
    preview_one_c_manual_import,
    preview_telegram_manual_import,
    resolve_conflict,
)
from app.services.telegram_prices import (
    map_telegram_price_source,
    reprocess_telegram_price_batch,
    telegram_prices_status,
)

router = APIRouter(prefix="/api/v1")


def get_telegram_adapter() -> TelegramClientAdapter:
    return build_telegram_adapter()


def get_queue_adapter() -> QueueAdapter:
    return RQQueueAdapter()


@router.post("/auth/login", response_model=OperatorSessionRead)
async def login_operator(
    payload: OperatorLoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    user, csrf_token, expires_at = await authenticate_operator(
        session,
        response,
        request,
        username=payload.username,
        password=payload.password,
    )
    return {"user": user, "csrf_token": csrf_token, "expires_at": expires_at}


@router.post("/auth/logout")
async def logout_operator(
    response: Response,
    auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    await revoke_current_session(response, auth, session)
    return {"status": "ok"}


@router.get("/auth/session", response_model=OperatorUserRead)
async def current_operator(auth: AuthenticatedOperator = Depends(get_authenticated_operator)) -> object:
    return auth.user


@router.post("/operators", response_model=OperatorUserRead, status_code=status.HTTP_201_CREATED)
async def create_operator(
    payload: OperatorCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN)),
) -> object:
    try:
        return await create_operator_user(session, payload.username, payload.password, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/operators", response_model=list[OperatorListItem])
async def list_operators(
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN)),
) -> list:
    from app.models.operator import OperatorUser

    return list(await session.scalars(select(OperatorUser).order_by(OperatorUser.username)))


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


@router.post(
    "/onboarding/telegram/preview",
    response_model=ManualImportBatchRead,
    dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))],
)
async def preview_telegram_manual_import_endpoint(
    payload: TelegramManualPreviewRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ManualImportBatch:
    return await preview_telegram_manual_import(
        session,
        source_id=payload.source_id,
        raw_text=payload.raw_text,
        snapshot_type=payload.snapshot_type,
        captured_at=payload.captured_at,
        actor=payload.actor,
    )


@router.post(
    "/onboarding/telegram/{batch_id}/confirm",
    response_model=ManualImportBatchRead,
    dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))],
)
async def confirm_telegram_manual_import_endpoint(
    batch_id: uuid.UUID,
    payload: ConfirmImportRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ManualImportBatch:
    return await confirm_telegram_manual_import(session, batch_id, actor=payload.actor)


@router.post(
    "/onboarding/1c/preview",
    response_model=ManualImportBatchRead,
    dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))],
)
async def preview_one_c_manual_import_endpoint(
    payload: OneCManualPreviewRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ManualImportBatch:
    return await preview_one_c_manual_import(
        session,
        filename=payload.filename,
        content=payload.content,
        mode=payload.mode,
        actor=payload.actor,
    )


@router.post(
    "/onboarding/1c/{batch_id}/confirm",
    response_model=ManualImportBatchRead,
    dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))],
)
async def confirm_one_c_manual_import_endpoint(
    batch_id: uuid.UUID,
    payload: ConfirmImportRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ManualImportBatch:
    return await confirm_one_c_manual_import(session, batch_id, actor=payload.actor)


@router.get(
    "/onboarding/imports",
    response_model=list[ManualImportBatchRead],
    dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))],
)
async def list_manual_import_batches(
    import_type: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
) -> list[ManualImportBatch]:
    statement = select(ManualImportBatch).order_by(ManualImportBatch.created_at.desc()).limit(min(limit, 500))
    if import_type is not None:
        statement = statement.where(ManualImportBatch.import_type == import_type)
    return list(await session.scalars(statement))


@router.post(
    "/onboarding/products",
    response_model=ProductOnboardingResult,
    dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))],
)
async def onboard_product_endpoint(payload: ProductOnboardingRequest, session: AsyncSession = Depends(get_db_session)) -> dict:
    return await onboard_product(session, payload)


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


@router.get("/telegram-prices/status", response_model=TelegramPriceStatusRead)
async def get_telegram_prices_status(
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
) -> dict:
    return await telegram_prices_status(session)


@router.get("/telegram-prices/sources", response_model=list[TelegramPriceSourceRead])
async def list_telegram_price_sources(
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
) -> list[TelegramPriceSource]:
    return list(
        await session.scalars(
            select(TelegramPriceSource).order_by(TelegramPriceSource.last_received_at.desc().nullslast()).limit(min(limit, 500))
        )
    )


@router.post("/telegram-prices/sources/{price_source_id}/map", response_model=TelegramPriceSourceRead)
async def map_telegram_price_source_endpoint(
    price_source_id: uuid.UUID,
    payload: TelegramPriceSourceMapRequest,
    session: AsyncSession = Depends(get_db_session),
    auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR)),
) -> TelegramPriceSource:
    try:
        return await map_telegram_price_source(session, price_source_id, payload.supplier_id, actor_id=auth.user.id)
    except ValueError as exc:
        if str(exc) == "TELEGRAM_SOURCE_ALREADY_MAPPED":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/telegram-prices/ingestions", response_model=list[TelegramPriceBatchRead])
async def list_telegram_price_ingestions(
    status_filter: str | None = None,
    source_id: uuid.UUID | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
) -> list[TelegramPriceBatch]:
    statement = select(TelegramPriceBatch).order_by(TelegramPriceBatch.received_at.desc()).limit(min(limit, 500))
    if status_filter is not None:
        statement = statement.where(TelegramPriceBatch.status == status_filter)
    if source_id is not None:
        statement = statement.where(TelegramPriceBatch.source_id == source_id)
    return list(await session.scalars(statement))


@router.get("/telegram-prices/ingestions/{batch_id}", response_model=TelegramPriceBatchRead)
async def get_telegram_price_ingestion(
    batch_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
) -> TelegramPriceBatch:
    batch = await session.get(TelegramPriceBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TelegramPriceBatch not found")
    return batch


@router.get("/telegram-prices/ingestions/{batch_id}/messages", response_model=list[TelegramPriceMessageRead])
async def list_telegram_price_messages(
    batch_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
) -> list[TelegramPriceMessage]:
    return list(
        await session.scalars(
            select(TelegramPriceMessage)
            .where(TelegramPriceMessage.batch_id == batch_id)
            .order_by(TelegramPriceMessage.message_date, TelegramPriceMessage.message_id)
        )
    )


@router.post("/telegram-prices/ingestions/{batch_id}/reprocess", response_model=TelegramPriceBatchRead)
async def reprocess_telegram_price_ingestion(
    batch_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR)),
) -> TelegramPriceBatch:
    try:
        return await reprocess_telegram_price_batch(session, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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


@router.post(
    "/match-reviews/{review_id}/accept",
    response_model=MatchReviewRead,
    dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))],
)
async def accept_match_review_endpoint(
    review_id: uuid.UUID,
    payload: MatchReviewAcceptRequest,
    session: AsyncSession = Depends(get_db_session),
) -> MatchReview:
    return await accept_match_review(
        session,
        review_id,
        variant_id=payload.variant_id,
        alias=payload.alias,
        actor=payload.actor,
    )


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


@router.get("/operator/dashboard", response_model=DashboardRead)
async def operator_dashboard(
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await dashboard(session)


@router.get("/operator/products", response_model=Page)
async def operator_products(
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await product_list(session, search=search, limit=min(limit, 100), offset=offset)


@router.get("/operator/products/{variant_id}")
async def operator_variant_detail(
    variant_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    try:
        return await variant_detail(session, variant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/operator/pricing", response_model=Page)
async def operator_pricing(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await pricing_list(session, limit=min(limit, 100), offset=offset)


@router.get("/operator/inventory", response_model=Page)
async def operator_inventory(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await inventory_list(session, limit=min(limit, 100), offset=offset)


@router.get("/operator/suppliers", response_model=Page)
async def operator_suppliers(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await supplier_list(session, limit=min(limit, 100), offset=offset)


@router.post("/operator/suppliers", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
async def operator_create_supplier(
    payload: OperatorSupplierCreate,
    session: AsyncSession = Depends(get_db_session),
    auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR)),
) -> Supplier:
    try:
        return await create_operator_supplier(session, name=payload.name, is_active=payload.is_active, actor_id=auth.user.id)
    except ValueError as exc:
        detail = str(exc)
        if detail in {"SUPPLIER_NAME_REQUIRED", "SUPPLIER_NAME_TOO_LONG"}:
            raise HTTPException(status_code=422, detail=detail) from exc
        if detail == "SUPPLIER_NAME_EXISTS":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc
        raise


@router.get("/operator/sources", response_model=Page)
async def operator_sources(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await source_health(session, limit=min(limit, 100), offset=offset)


@router.get("/operator/publication/jobs", response_model=Page)
async def operator_publication_jobs(
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await publication_jobs(session, limit=min(limit, 100), offset=offset, status_filter=status_filter)


@router.get("/operator/publication/jobs/{job_id}")
async def operator_publication_job_detail(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    try:
        return await publication_job_detail(session, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/operator/alerts", response_model=Page)
async def operator_alerts(
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await alert_page(session, limit=min(limit, 100), offset=offset, status_filter=status_filter)


@router.post("/operator/alerts/{alert_id}/acknowledge", response_model=OperationalAlertRead)
async def operator_acknowledge_alert(
    alert_id: uuid.UUID,
    _payload: AlertActionRequest,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR)),
):
    try:
        return await update_alert_status(session, alert_id, OperationalAlertStatus.ACKNOWLEDGED)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/operator/alerts/{alert_id}/resolve", response_model=OperationalAlertRead)
async def operator_resolve_alert(
    alert_id: uuid.UUID,
    _payload: AlertActionRequest,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR)),
):
    try:
        return await update_alert_status(session, alert_id, OperationalAlertStatus.RESOLVED)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/operator/audit", response_model=Page)
async def operator_audit(
    action: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await audit_page(session, limit=min(limit, 100), offset=offset, action=action, entity_type=entity_type)


@router.get("/operator/settings", response_model=SettingsRead)
async def operator_settings(
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await settings_read()


@router.get("/operator/system/health", response_model=SystemHealthRead)
async def operator_system_health(
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER)),
):
    return await system_health(session)


@router.post("/operator/backups/smoke", response_model=BackupSmokeRead)
async def operator_backup_smoke(
    session: AsyncSession = Depends(get_db_session),
    _auth: AuthenticatedOperator = Depends(require_role(OperatorRole.ADMIN)),
):
    return await backup_smoke(session)


@router.get("/control/overview", response_model=ControlOverviewRead, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))])
async def control_overview_endpoint(session: AsyncSession = Depends(get_db_session)):
    return await control_overview(session)


@router.get("/control/review-queue", dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))])
async def control_review_queue(limit: int = 20, session: AsyncSession = Depends(get_db_session)):
    return await review_queue(session, limit=limit)


@router.get("/control/listings", response_model=list[GenericListingDraftRead], dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))])
async def control_listings(
    generic_readiness: GenericReadinessStatus | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
):
    return await list_variant_listings(session, status_filter=generic_readiness, limit=limit)


@router.get("/control/listings/{listing_id}", response_model=GenericListingDraftRead, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))])
async def control_listing_detail(listing_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    listing = await session.get(GenericListingDraft, listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GenericListingDraft not found")
    return listing


@router.post("/control/listings/{listing_id}/approve", response_model=GenericListingDraftRead, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))])
async def control_approve_listing(listing_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return await approve_listing(session, listing_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/control/listings/{listing_id}/reject", response_model=GenericListingDraftRead, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))])
async def control_reject_listing(listing_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    listing = await session.get(GenericListingDraft, listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GenericListingDraft not found")
    listing.status = GenericListingStatus.REJECTED
    await session.commit()
    await session.refresh(listing)
    return listing


@router.post("/control/listings/{listing_id}/publication-intents", response_model=PublicationIntentRead, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))])
async def create_publication_intent_endpoint(
    listing_id: uuid.UUID,
    payload: PublicationIntentCreate,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        intent, _job, _created = await create_publication_intent(
            session,
            listing_id,
            marketplace=payload.marketplace,
            intent_type=payload.intent_type,
            requested_by=payload.requested_by,
            reason=payload.reason,
            dry_run=payload.dry_run,
        )
        return intent
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/control/listings/{listing_id}/dry-run", response_model=PublicationJobRead, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))])
async def dry_run_publication_endpoint(
    listing_id: uuid.UUID,
    payload: PublicationIntentCreate,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        _intent, job, _created = await create_publication_intent(
            session,
            listing_id,
            marketplace=payload.marketplace,
            intent_type=payload.intent_type,
            requested_by=payload.requested_by,
            reason=payload.reason,
            dry_run=True,
        )
        return await process_publication_job(session, job.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/control/listings/{listing_id}/dry-run-validation",
    dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))],
)
async def dry_run_validation_endpoint(listing_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> dict:
    return await listing_dry_run_validation(session, listing_id)


@router.get(
    "/operator/pilot-readiness",
    response_model=PilotReadinessReport,
    dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))],
)
async def pilot_readiness_endpoint(session: AsyncSession = Depends(get_db_session)) -> dict:
    return await pilot_readiness(session)


@router.get("/control/publication-intents", response_model=list[PublicationIntentRead], dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))])
async def list_publication_intents(
    marketplace: Marketplace | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
):
    statement = select(PublicationIntent).order_by(PublicationIntent.created_at.desc()).limit(min(limit, 500))
    if marketplace is not None:
        statement = statement.where(PublicationIntent.marketplace == marketplace)
    return list(await session.scalars(statement))


@router.get("/control/publication-intents/{intent_id}", response_model=PublicationIntentRead, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))])
async def get_publication_intent(intent_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    intent = await session.get(PublicationIntent, intent_id)
    if intent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PublicationIntent not found")
    return intent


@router.get("/control/publication-jobs", response_model=list[PublicationJobRead], dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))])
async def list_publication_jobs(
    status_filter: PublicationJobStatus | None = None,
    marketplace: Marketplace | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
):
    statement = select(PublicationJob).order_by(PublicationJob.created_at.desc()).limit(min(limit, 500))
    if status_filter is not None:
        statement = statement.where(PublicationJob.status == status_filter)
    if marketplace is not None:
        statement = statement.where(PublicationJob.marketplace == marketplace)
    return list(await session.scalars(statement))


@router.get("/control/publication-jobs/{job_id}", response_model=PublicationJobRead, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))])
async def get_publication_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)):
    job = await session.get(PublicationJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PublicationJob not found")
    return job


@router.post("/control/publication-jobs/{job_id}/retry", response_model=PublicationJobRead, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))])
async def retry_publication_job_endpoint(
    job_id: uuid.UUID,
    payload: RetryCancelRequest,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await retry_publication_job(session, job_id, requested_by=payload.requested_by)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/control/publication-jobs/{job_id}/cancel", response_model=PublicationJobRead, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))])
async def cancel_publication_job_endpoint(
    job_id: uuid.UUID,
    payload: RetryCancelRequest,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await cancel_publication_job(session, job_id, requested_by=payload.requested_by)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/control/reconcile", dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))])
async def reconcile_endpoint(payload: ReconcileRequest, session: AsyncSession = Depends(get_db_session)):
    try:
        return await reconcile_listing(session, payload.listing_id, marketplace=payload.marketplace)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/control/recalculate", response_model=BulkContentResult, dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))])
async def control_recalculate_endpoint(session: AsyncSession = Depends(get_db_session)):
    return await recalculate_listing_readiness_bulk(session)


@router.get("/control/bindings", response_model=list[MarketplaceListingBindingRead], dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))])
async def list_marketplace_bindings(limit: int = 100, session: AsyncSession = Depends(get_db_session)):
    return list(await session.scalars(select(MarketplaceListingBinding).order_by(MarketplaceListingBinding.created_at.desc()).limit(min(limit, 500))))


@router.get("/control/alerts", response_model=list[OperationalAlertRead], dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR, OperatorRole.VIEWER))])
async def list_operational_alerts(limit: int = 100, session: AsyncSession = Depends(get_db_session)):
    return list(await session.scalars(select(OperationalAlert).order_by(OperationalAlert.created_at.desc()).limit(min(limit, 500))))


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


@router.post(
    "/conflicts/{conflict_id}/resolve",
    response_model=DataConflictRead,
    dependencies=[Depends(require_role(OperatorRole.ADMIN, OperatorRole.OPERATOR))],
)
async def resolve_conflict_endpoint(
    conflict_id: uuid.UUID,
    payload: ConflictResolveRequest,
    session: AsyncSession = Depends(get_db_session),
) -> DataConflict:
    return await resolve_conflict(session, conflict_id, actor=payload.actor, resolution=payload.resolution)
