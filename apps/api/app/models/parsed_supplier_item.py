import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CHAR, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import ParseStatus, ProductCondition


class ParsedSupplierItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "parsed_supplier_items"
    __table_args__ = (
        Index("ix_parsed_supplier_items_raw_line", "raw_source_record_id", "line_number"),
        Index("ix_parsed_supplier_items_identity", "raw_source_record_id", "parsed_identity_key"),
    )

    raw_source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_source_records.id", ondelete="CASCADE")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"))
    line_number: Mapped[int] = mapped_column(Integer)
    raw_line: Mapped[str] = mapped_column(Text)
    section_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_normalized: Mapped[str | None] = mapped_column(String(120), nullable=True)
    brand_raw: Mapped[str | None] = mapped_column(String(120), nullable=True)
    brand_normalized: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer_model_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ram_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    color_raw: Mapped[str | None] = mapped_column(String(120), nullable=True)
    color_normalized: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region_raw: Mapped[str | None] = mapped_column(String(32), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    condition: Mapped[ProductCondition | None] = mapped_column(Enum(ProductCondition, name="product_condition"), nullable=True)
    price_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), default="RUB", server_default="RUB")
    parse_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    parse_status: Mapped[ParseStatus] = mapped_column(Enum(ParseStatus, name="parse_status"))
    parse_flags: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    parsed_payload: Mapped[dict] = mapped_column(JSONB)
    parsed_identity_key: Mapped[str | None] = mapped_column(String(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
