"""add telegram price bot ingestion state

Revision ID: 202609110014
Revises: 202609110013
Create Date: 2026-09-15 00:14:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110014"
down_revision: str | None = "202609110013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_price_bot_states",
        sa.Column("bot_key", sa.String(length=64), nullable=False),
        sa.Column("last_update_id", sa.BigInteger(), nullable=True),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_api_error", sa.String(length=512), nullable=True),
        sa.Column("last_successful_price_ingestion_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_price_bot_states")),
        sa.UniqueConstraint("bot_key", name="uq_telegram_price_bot_states_bot_key"),
    )
    op.create_table(
        "telegram_price_sources",
        sa.Column("telegram_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_type", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_telegram_price_sources_source_id_sources"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_price_sources")),
        sa.UniqueConstraint("telegram_channel_id", name="uq_telegram_price_sources_channel_id"),
    )
    op.create_index("ix_telegram_price_sources_source_id", "telegram_price_sources", ["source_id"])
    op.create_table(
        "telegram_price_batches",
        sa.Column("telegram_price_source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_source_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_source_record_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("destination_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=64), server_default="RECEIVED", nullable=False),
        sa.Column("duplicate", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("parsed_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("accepted_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("review_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_source_record_id"], ["raw_source_records.id"], name=op.f("fk_telegram_price_batches_raw_source_record_id_raw_source_records"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_source_record_revision_id"], ["raw_source_record_revisions.id"], name=op.f("fk_telegram_price_batches_raw_source_record_revision_id_raw_source_record_revisions"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_telegram_price_batches_source_id_sources"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supplier_snapshot_id"], ["supplier_snapshots.id"], name=op.f("fk_telegram_price_batches_supplier_snapshot_id_supplier_snapshots"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["telegram_price_source_id"], ["telegram_price_sources.id"], name=op.f("fk_telegram_price_batches_telegram_price_source_id_telegram_price_sources"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_price_batches")),
    )
    op.create_index("ix_telegram_price_batches_source", "telegram_price_batches", ["telegram_price_source_id"])
    op.create_index("ix_telegram_price_batches_status", "telegram_price_batches", ["status"])
    op.create_table(
        "telegram_price_messages",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("telegram_price_source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("sender_user_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("message_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("forward_origin", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["telegram_price_batches.id"], name=op.f("fk_telegram_price_messages_batch_id_telegram_price_batches"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["telegram_price_source_id"], ["telegram_price_sources.id"], name=op.f("fk_telegram_price_messages_telegram_price_source_id_telegram_price_sources"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_price_messages")),
        sa.UniqueConstraint("update_id", name="uq_telegram_price_messages_update_id"),
    )
    op.create_index("ix_telegram_price_messages_batch", "telegram_price_messages", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_price_messages_batch", table_name="telegram_price_messages")
    op.drop_table("telegram_price_messages")
    op.drop_index("ix_telegram_price_batches_status", table_name="telegram_price_batches")
    op.drop_index("ix_telegram_price_batches_source", table_name="telegram_price_batches")
    op.drop_table("telegram_price_batches")
    op.drop_index("ix_telegram_price_sources_source_id", table_name="telegram_price_sources")
    op.drop_table("telegram_price_sources")
    op.drop_table("telegram_price_bot_states")
