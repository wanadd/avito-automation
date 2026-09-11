import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductVariant
from app.schemas.product import ProductVariantCreate
from app.services.canonical_key import build_canonical_key


async def create_variant(session: AsyncSession, product_id: uuid.UUID, payload: ProductVariantCreate) -> ProductVariant:
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    canonical_key = build_canonical_key(
        brand=product.brand,
        canonical_name=product.canonical_name,
        manufacturer_model_code=payload.manufacturer_model_code,
        ram_gb=payload.ram_gb,
        storage_gb=payload.storage_gb,
        color_normalized=payload.color_normalized,
        region_code=payload.region_code,
        condition=payload.condition,
    )
    variant = ProductVariant(product_id=product.id, canonical_key=canonical_key, **payload.model_dump())
    session.add(variant)
    await session.commit()
    await session.refresh(variant)
    return variant

