from decimal import Decimal

from app.models.enums import ParseStatus
from app.services.parser.constants import PARSED_THRESHOLD, PARTIAL_THRESHOLD
from app.services.parser.types import ParsedLine


def score_confidence(item: ParsedLine) -> Decimal:
    score = Decimal("0.00")
    if item.brand_normalized:
        score += Decimal("0.18")
    if item.model_normalized:
        score += Decimal("0.25")
    if item.price_minor is not None:
        score += Decimal("0.22")
    if item.storage_gb is not None:
        score += Decimal("0.12")
    if item.manufacturer_model_code:
        score += Decimal("0.08")
    if item.color_normalized:
        score += Decimal("0.07")
    if item.region_code:
        score += Decimal("0.08")

    penalty_flags = {
        "UNKNOWN_SECTION",
        "UNKNOWN_REGION",
        "UNKNOWN_COLOR",
        "MISSING_PRICE",
        "INVALID_PRICE",
        "MISSING_MODEL",
        "AMBIGUOUS_MODEL",
        "AMBIGUOUS_MEMORY",
        "POSSIBLE_MODEL_CODE",
        "DUPLICATE_LINE",
    }
    score -= Decimal("0.04") * len(penalty_flags.intersection(item.parse_flags))
    score = max(Decimal("0.0000"), min(Decimal("1.0000"), score))
    return score.quantize(Decimal("0.0001"))


def status_from_confidence(item: ParsedLine) -> ParseStatus:
    if "PRICE_CONFLICT" in item.parse_flags:
        return ParseStatus.CONFLICT
    if item.parse_status == ParseStatus.IGNORED:
        return ParseStatus.IGNORED
    if "INVALID_PRICE" in item.parse_flags:
        return ParseStatus.REVIEW
    if item.parse_confidence >= PARSED_THRESHOLD and not item.parse_flags:
        return ParseStatus.PARSED
    if item.parse_confidence >= PARTIAL_THRESHOLD:
        return ParseStatus.PARTIAL
    return ParseStatus.REVIEW

