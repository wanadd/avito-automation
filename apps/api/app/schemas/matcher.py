import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import MatchStatus, MatchStrategy, ReviewStatus
from app.schemas.common import ORMModel


class MatchCandidate(BaseModel):
    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    score: Decimal
    reasons: list[str]


class MatchResult(BaseModel):
    parsed_item_id: uuid.UUID
    status: MatchStatus
    matched_product_id: uuid.UUID | None = None
    matched_variant_id: uuid.UUID | None = None
    confidence: Decimal
    strategy: MatchStrategy
    reasons: list[str]
    candidate_count: int
    candidates: list[MatchCandidate]
    created_product: bool = False
    created_variant: bool = False
    offer_created: bool = False
    offer_updated: bool = False


class MatchRawRecordSummary(BaseModel):
    raw_record_id: uuid.UUID
    exact_match: int
    auto_created: int
    review: int
    rejected: int
    conflict_blocked: int
    offers_created: int
    offers_updated: int
    results: list[MatchResult]


class MatchReviewRead(ORMModel):
    id: uuid.UUID
    parsed_item_id: uuid.UUID | None
    source_record_id: uuid.UUID | None
    supplier_offer_id: uuid.UUID | None
    candidate_variant_id: uuid.UUID | None
    confidence: Decimal
    status: ReviewStatus
    reason: str | None
    strategy: str | None
    candidate_details: dict | None
