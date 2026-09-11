"""add source collection jobs and scheduling fields

Revision ID: 202609110007
Revises: 202609110006
Create Date: 2026-09-11 00:07:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110007"
down_revision: str | None = "202609110006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

job_status = postgresql.ENUM(
    "PENDING", "QUEUED", "RUNNING", "SUCCEEDED", "RETRY_WAIT", "FAILED", "CANCELLED", "SKIPPED",
    name="source_collection_job_status",
    create_type=False,
)
job_type = postgresql.ENUM(
    "SCHEDULED_INCREMENTAL", "MANUAL_INCREMENTAL", "MANUAL_BACKFILL", "RETRY",
    name="source_collection_job_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    job_status.create(bind, checkfirst=True)
    job_type.create(bind, checkfirst=True)

    op.add_column("sources", sa.Column("collection_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("sources", sa.Column("collection_interval_seconds", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("next_collection_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("last_scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False))
    op.add_column("sources", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "source_collection_jobs",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("status", job_status, server_default="PENDING", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["collection_run_id"], ["telegram_collection_runs.id"], name="fk_source_collection_jobs_run"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_source_collection_jobs_source", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_collection_jobs")),
        sa.UniqueConstraint("idempotency_key", name="uq_source_collection_jobs_idempotency_key"),
    )
    op.create_index("ix_source_collection_jobs_source_id", "source_collection_jobs", ["source_id"])
    op.create_index("ix_source_collection_jobs_status", "source_collection_jobs", ["status"])
    op.create_index("ix_source_collection_jobs_scheduled_for", "source_collection_jobs", ["scheduled_for"])


def downgrade() -> None:
    op.drop_index("ix_source_collection_jobs_scheduled_for", table_name="source_collection_jobs")
    op.drop_index("ix_source_collection_jobs_status", table_name="source_collection_jobs")
    op.drop_index("ix_source_collection_jobs_source_id", table_name="source_collection_jobs")
    op.drop_table("source_collection_jobs")
    op.drop_column("sources", "last_success_at")
    op.drop_column("sources", "consecutive_failures")
    op.drop_column("sources", "last_scheduled_at")
    op.drop_column("sources", "next_collection_at")
    op.drop_column("sources", "collection_interval_seconds")
    op.drop_column("sources", "collection_enabled")

    bind = op.get_bind()
    job_type.drop(bind, checkfirst=True)
    job_status.drop(bind, checkfirst=True)
