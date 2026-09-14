"""add real data onboarding batches

Revision ID: 202609110013
Revises: 202609110012
Create Date: 2026-09-14 00:13:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110013"
down_revision: str | None = "202609110012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "manual_import_batches",
        sa.Column("import_type", sa.String(length=32), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PREVIEWED", nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("preview", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("raw_source_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("one_c_import_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["one_c_import_run_id"], ["one_c_import_runs.id"], name=op.f("fk_manual_import_batches_one_c_import_run_id_one_c_import_runs")),
        sa.ForeignKeyConstraint(["raw_source_record_id"], ["raw_source_records.id"], name=op.f("fk_manual_import_batches_raw_source_record_id_raw_source_records")),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_manual_import_batches_source_id_sources")),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name=op.f("fk_manual_import_batches_supplier_id_suppliers")),
        sa.ForeignKeyConstraint(["supplier_snapshot_id"], ["supplier_snapshots.id"], name=op.f("fk_manual_import_batches_supplier_snapshot_id_supplier_snapshots")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_manual_import_batches")),
        sa.UniqueConstraint("import_type", "scope_key", "content_hash", "mode", name="uq_manual_import_batch_identity"),
    )
    op.create_index("ix_manual_import_batches_created_at", "manual_import_batches", ["created_at"])
    op.create_index("ix_manual_import_batches_status", "manual_import_batches", ["status"])


def downgrade() -> None:
    op.drop_index("ix_manual_import_batches_status", table_name="manual_import_batches")
    op.drop_index("ix_manual_import_batches_created_at", table_name="manual_import_batches")
    op.drop_table("manual_import_batches")
