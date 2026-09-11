"""add telegram collector state and raw revisions

Revision ID: 202609110006
Revises: 202609110005
Create Date: 2026-09-11 00:06:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110006"
down_revision: str | None = "202609110005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

snapshot_type = postgresql.ENUM("FULL", "PARTIAL", name="supplier_snapshot_type", create_type=False)
collection_mode = postgresql.ENUM("BACKFILL", "INCREMENTAL", name="telegram_collection_mode", create_type=False)
collection_status = postgresql.ENUM(
    "RUNNING", "COMPLETED", "PARTIAL", "FAILED", name="telegram_collection_run_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    collection_mode.create(bind, checkfirst=True)
    collection_status.create(bind, checkfirst=True)

    op.add_column("sources", sa.Column("external_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("sources", sa.Column("username", sa.String(length=255), nullable=True))
    op.add_column("sources", sa.Column("title", sa.String(length=255), nullable=True))
    op.add_column("sources", sa.Column("telegram_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("sources", sa.Column("snapshot_type", snapshot_type, server_default="FULL", nullable=False))
    op.add_column("sources", sa.Column("last_collected_message_id", sa.BigInteger(), nullable=True))
    op.add_column("sources", sa.Column("last_collection_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("last_collection_status", collection_status, nullable=True))
    op.add_column("sources", sa.Column("last_collection_error", sa.String(length=512), nullable=True))
    op.create_index("ix_sources_external_chat_id", "sources", ["external_chat_id"])

    op.create_table(
        "raw_source_record_revisions",
        sa.Column("raw_source_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("external_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["raw_source_record_id"],
            ["raw_source_records.id"],
            name=op.f("fk_raw_source_record_revisions_raw_source_record_id_raw_source_records"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_source_record_revisions")),
    )
    op.create_index(
        "uq_raw_source_record_revisions_record_revision",
        "raw_source_record_revisions",
        ["raw_source_record_id", "revision_no"],
        unique=True,
    )
    op.create_index(
        "uq_raw_source_record_revisions_record_hash",
        "raw_source_record_revisions",
        ["raw_source_record_id", "content_hash"],
        unique=True,
    )

    op.add_column("supplier_snapshots", sa.Column("raw_source_record_revision_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.drop_constraint("uq_supplier_snapshots_raw_identity", "supplier_snapshots", type_="unique")
    op.create_foreign_key(
        op.f("fk_supplier_snapshots_raw_source_record_revision_id_raw_source_record_revisions"),
        "supplier_snapshots",
        "raw_source_record_revisions",
        ["raw_source_record_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_supplier_snapshots_raw_revision_identity",
        "supplier_snapshots",
        ["supplier_id", "source_id", "raw_source_record_id", "raw_source_record_revision_id"],
    )

    op.create_table(
        "telegram_collection_runs",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", collection_status, server_default="RUNNING", nullable=False),
        sa.Column("mode", collection_mode, nullable=False),
        sa.Column("fetched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("new_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("edited_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ignored_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("snapshots_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("snapshots_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("start_message_id", sa.BigInteger(), nullable=True),
        sa.Column("end_message_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_telegram_collection_runs_source_id_sources"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_collection_runs")),
    )
    op.create_index("ix_telegram_collection_runs_source_id", "telegram_collection_runs", ["source_id"])
    op.create_index("ix_telegram_collection_runs_status", "telegram_collection_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_telegram_collection_runs_status", table_name="telegram_collection_runs")
    op.drop_index("ix_telegram_collection_runs_source_id", table_name="telegram_collection_runs")
    op.drop_table("telegram_collection_runs")
    op.drop_constraint("uq_supplier_snapshots_raw_revision_identity", "supplier_snapshots", type_="unique")
    op.drop_constraint(
        op.f("fk_supplier_snapshots_raw_source_record_revision_id_raw_source_record_revisions"),
        "supplier_snapshots",
        type_="foreignkey",
    )
    op.drop_column("supplier_snapshots", "raw_source_record_revision_id")
    op.create_unique_constraint(
        "uq_supplier_snapshots_raw_identity",
        "supplier_snapshots",
        ["supplier_id", "source_id", "raw_source_record_id"],
    )
    op.drop_index("uq_raw_source_record_revisions_record_hash", table_name="raw_source_record_revisions")
    op.drop_index("uq_raw_source_record_revisions_record_revision", table_name="raw_source_record_revisions")
    op.drop_table("raw_source_record_revisions")
    op.drop_index("ix_sources_external_chat_id", table_name="sources")
    op.drop_column("sources", "last_collection_error")
    op.drop_column("sources", "last_collection_status")
    op.drop_column("sources", "last_collection_at")
    op.drop_column("sources", "last_collected_message_id")
    op.drop_column("sources", "snapshot_type")
    op.drop_column("sources", "telegram_enabled")
    op.drop_column("sources", "title")
    op.drop_column("sources", "username")
    op.drop_column("sources", "external_chat_id")

    bind = op.get_bind()
    collection_status.drop(bind, checkfirst=True)
    collection_mode.drop(bind, checkfirst=True)
