import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import OneCImportMode, SupplierSnapshotType
from app.schemas.common import ORMModel
from app.schemas.product import ProductCreate, ProductVariantCreate, ProductRead, ProductVariantRead


class TelegramManualPreviewRequest(BaseModel):
    source_id: uuid.UUID
    raw_text: str = Field(min_length=1)
    snapshot_type: SupplierSnapshotType = SupplierSnapshotType.FULL
    captured_at: datetime | None = None
    actor: str | None = None


class OneCManualPreviewRequest(BaseModel):
    filename: str = "one_c_export.json"
    content: str = Field(min_length=1)
    mode: OneCImportMode = OneCImportMode.PARTIAL
    actor: str | None = None


class ConfirmImportRequest(BaseModel):
    actor: str | None = None


class ManualImportBatchRead(ORMModel):
    id: uuid.UUID
    import_type: str
    scope_key: str
    source_id: uuid.UUID | None
    supplier_id: uuid.UUID | None
    mode: str
    status: str
    filename: str | None
    content_hash: str
    preview: dict
    result: dict
    raw_source_record_id: uuid.UUID | None
    supplier_snapshot_id: uuid.UUID | None
    one_c_import_run_id: uuid.UUID | None
    actor: str | None
    created_at: datetime
    confirmed_at: datetime | None


class ProductAliasInput(BaseModel):
    alias: str
    source_id: uuid.UUID | None = None


class ProductOnboardingRequest(BaseModel):
    product: ProductCreate
    variant: ProductVariantCreate
    aliases: list[ProductAliasInput] = []
    one_c_item_id: uuid.UUID | None = None
    actor: str | None = None


class ProductOnboardingResult(BaseModel):
    product: ProductRead
    variant: ProductVariantRead
    aliases_created: int
    one_c_item_id: uuid.UUID | None = None


class PilotReadinessReport(BaseModel):
    status: str
    checks: dict


class MatchReviewAcceptRequest(BaseModel):
    variant_id: uuid.UUID
    alias: str | None = None
    actor: str = "operator"


class ConflictResolveRequest(BaseModel):
    actor: str = "operator"
    resolution: str | None = None
