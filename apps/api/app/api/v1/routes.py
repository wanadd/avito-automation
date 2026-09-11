import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.conflict import DataConflict
from app.models.product import Product, ProductVariant
from app.models.parsed_supplier_item import ParsedSupplierItem
from app.models.raw_source_record import RawSourceRecord
from app.models.source import Source
from app.models.supplier import Supplier
from app.models.supplier_offer import SupplierOffer
from app.schemas.conflict import DataConflictRead
from app.schemas.product import ProductCreate, ProductRead, ProductVariantCreate, ProductVariantRead
from app.schemas.parsed_supplier_item import ParsedSupplierItemRead, ParseSummary
from app.schemas.raw_source_record import RawSourceRecordCreate, RawSourceRecordRead
from app.schemas.source import SourceCreate, SourceRead
from app.schemas.supplier import SupplierCreate, SupplierRead
from app.schemas.supplier_offer import SupplierOfferCreate, SupplierOfferRead
from app.services.offers import upsert_supplier_offer
from app.services.parser.pipeline import parse_raw_record, summarize
from app.services.products import create_variant
from app.services.raw_records import create_raw_record

router = APIRouter(prefix="/api/v1")


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
