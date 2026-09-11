"""add product matcher review fields

Revision ID: 202609110003
Revises: 202609110002
Create Date: 2026-09-11 00:03:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110003"
down_revision: str | None = "202609110002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_products_brand_canonical_name", "products", ["brand", "canonical_name"])
    op.add_column("match_reviews", sa.Column("parsed_item_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("match_reviews", sa.Column("strategy", sa.String(length=120), nullable=True))
    op.add_column("match_reviews", sa.Column("candidate_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_foreign_key(
        op.f("fk_match_reviews_parsed_item_id_parsed_supplier_items"),
        "match_reviews",
        "parsed_supplier_items",
        ["parsed_item_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint("uq_match_reviews_parsed_item_status", "match_reviews", ["parsed_item_id", "status"])


def downgrade() -> None:
    op.drop_constraint("uq_match_reviews_parsed_item_status", "match_reviews", type_="unique")
    op.drop_constraint(op.f("fk_match_reviews_parsed_item_id_parsed_supplier_items"), "match_reviews", type_="foreignkey")
    op.drop_column("match_reviews", "candidate_details")
    op.drop_column("match_reviews", "strategy")
    op.drop_column("match_reviews", "parsed_item_id")
    op.drop_constraint("uq_products_brand_canonical_name", "products", type_="unique")
