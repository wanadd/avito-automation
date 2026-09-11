from enum import StrEnum


class SourceType(StrEnum):
    TELEGRAM = "TELEGRAM"
    WEBSITE = "WEBSITE"
    MANUAL = "MANUAL"
    IMPORT = "IMPORT"


class ProcessingStatus(StrEnum):
    NEW = "NEW"
    PARSED = "PARSED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ProductCondition(StrEnum):
    NEW = "NEW"
    USED = "USED"
    REFURBISHED = "REFURBISHED"


class Availability(StrEnum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"
    SUSPECT_MISSING = "SUSPECT_MISSING"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ConflictStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class ParseStatus(StrEnum):
    PARSED = "PARSED"
    PARTIAL = "PARTIAL"
    REVIEW = "REVIEW"
    CONFLICT = "CONFLICT"
    IGNORED = "IGNORED"
