import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    ContentDraftStatus,
    ContentValidationStatus,
    GenericCategory,
    GenericListingStatus,
    GenericReadinessStatus,
    ImageAssetSourceType,
    ImageAssetStatus,
    ImageSetStatus,
    MarketplaceReadinessStatus,
    ProductCondition,
)
from app.schemas.common import ORMModel


class ProductContentFactsRead(ORMModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    brand: str | None
    model: str | None
    model_code: str | None
    ram: str | None
    storage: str | None
    color: str | None
    region: str | None
    condition: ProductCondition | None
    canonical_product_name: str | None
    canonical_variant_name: str | None
    known_attributes: dict
    warranty_status: str
    warranty_text: str | None
    package_contents_status: str
    package_contents: list
    additional_facts: dict
    fact_sources: list
    fact_hash: str
    completeness_score: int
    has_conflicts: bool
    requires_review: bool
    created_at: datetime
    updated_at: datetime


class ManualFactOverrideRequest(BaseModel):
    field: str
    value: str
    operator: str = "manual"
    reason: str | None = None


class ProductFactOverrideRead(ORMModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    field: str
    value: str
    operator: str
    reason: str | None
    created_at: datetime
    updated_at: datetime


class ProductContentDraftRead(ORMModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    facts_id: uuid.UUID
    status: ContentDraftStatus
    title: str
    description: str
    title_generation_mode: str
    description_generation_mode: str
    generator: str
    generator_version: str
    prompt_version: str
    input_fact_hash: str
    content_hash: str
    validation_status: ContentValidationStatus
    validation_errors: list
    validation_warnings: list
    requires_review: bool
    created_by: str | None
    approved_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class RejectContentRequest(BaseModel):
    reason: str | None = None


class ImageAssetCreate(BaseModel):
    source_type: ImageAssetSourceType = ImageAssetSourceType.MANUAL_UPLOAD
    source_reference: str | None = None
    storage_path: str | None = None
    original_filename: str | None = None
    mime_type: str
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    sort_order: int = 0


class ProductImageAssetRead(ORMModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    source_type: ImageAssetSourceType
    source_reference: str | None
    storage_path: str | None
    original_filename: str | None
    mime_type: str
    width: int | None
    height: int | None
    size_bytes: int
    sha256: str
    sort_order: int
    status: ImageAssetStatus
    created_at: datetime


class ImageSetCreate(BaseModel):
    image_asset_ids: list[uuid.UUID]
    cover_image_id: uuid.UUID | None = None


class ProductImageSetRead(ORMModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    status: ImageSetStatus
    version: int
    cover_image_id: uuid.UUID | None
    content_hash: str
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GenericListingDraftRead(ORMModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    content_draft_id: uuid.UUID | None
    image_set_id: uuid.UUID | None
    pricing_state_id: uuid.UUID | None
    status: GenericListingStatus
    generic_category: GenericCategory
    generic_attributes: dict
    title: str | None
    description: str | None
    price_minor: int | None
    stock_decision: str | None
    fulfillment_source: str | None
    generic_readiness: GenericReadinessStatus
    avito_readiness: MarketplaceReadinessStatus
    readiness_reasons: list
    content_hash: str
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BulkContentResult(BaseModel):
    processed: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    review_required: int = 0
    failed: int = 0
    skipped: int = 0
