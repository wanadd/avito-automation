"""make product variant condition nullable

Revision ID: 202609110004
Revises: 202609110003
Create Date: 2026-09-11 00:04:00
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110004"
down_revision: str | None = "202609110003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    product_condition = postgresql.ENUM("NEW", "USED", "REFURBISHED", name="product_condition", create_type=False)
    op.alter_column("product_variants", "condition", existing_type=product_condition, nullable=True)


def downgrade() -> None:
    product_condition = postgresql.ENUM("NEW", "USED", "REFURBISHED", name="product_condition", create_type=False)
    op.alter_column("product_variants", "condition", existing_type=product_condition, nullable=False)
