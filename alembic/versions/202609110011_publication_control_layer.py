"""add publication control layer

Revision ID: 202609110011
Revises: 202609110010
Create Date: 2026-09-11 00:11:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110011"
down_revision: str | None = "202609110010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

marketplace = postgresql.ENUM("AVITO", name="marketplace", create_type=False)
binding_status = postgresql.ENUM("UNBOUND", "PREPARED", "BLOCKED", "ACTIVE_EXTERNAL", "PAUSED_EXTERNAL", "STALE", "ERROR", "ARCHIVED", name="marketplace_binding_status", create_type=False)
intent_type = postgresql.ENUM("CREATE", "UPDATE_CONTENT", "UPDATE_PRICE", "UPDATE_STOCK", "PAUSE", "RESUME", "DEACTIVATE", "FULL_SYNC", name="publication_intent_type", create_type=False)
intent_status = postgresql.ENUM("PENDING", "STALE", "JOB_CREATED", "CANCELLED", name="publication_intent_status", create_type=False)
job_status = postgresql.ENUM("PENDING", "QUEUED", "RUNNING", "PREPARED", "DRY_RUN_SUCCESS", "BLOCKED", "RETRY_WAIT", "FAILED", "CANCELLED", "SUCCEEDED", name="publication_job_status", create_type=False)
sync_state = postgresql.ENUM("NOT_PREPARED", "READY_FOR_INTENT", "INTENT_PENDING", "QUEUED", "PREPARED", "DRY_RUN_OK", "BLOCKED_EXTERNAL", "STALE", "ERROR", "SYNCED", name="listing_sync_state", create_type=False)
alert_status = postgresql.ENUM("OPEN", "ACKNOWLEDGED", "RESOLVED", name="operational_alert_status", create_type=False)
alert_severity = postgresql.ENUM("INFO", "WARNING", "ERROR", "CRITICAL", name="operational_alert_severity", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (marketplace, binding_status, intent_type, intent_status, job_status, sync_state, alert_status, alert_severity):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "marketplace_listing_bindings",
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generic_listing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketplace", marketplace, nullable=False),
        sa.Column("external_listing_id", sa.String(length=255), nullable=True),
        sa.Column("status", binding_status, nullable=False),
        sa.Column("sync_state", sync_state, nullable=False),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=120), nullable=True),
        sa.Column("last_known_price_minor", sa.Integer(), nullable=True),
        sa.Column("last_known_stock_state", sa.String(length=64), nullable=True),
        sa.Column("last_content_hash", sa.String(length=64), nullable=True),
        sa.Column("last_image_set_hash", sa.String(length=64), nullable=True),
        sa.Column("last_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["generic_listing_id"], ["generic_listing_drafts.id"], name="fk_marketplace_bindings_listing", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], name="fk_marketplace_bindings_variant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketplace_listing_bindings")),
        sa.UniqueConstraint("marketplace", "generic_listing_id", name="uq_marketplace_binding_listing"),
    )
    for column in ("variant_id", "generic_listing_id", "marketplace", "status", "sync_state", "last_error_code"):
        op.create_index(op.f(f"ix_marketplace_listing_bindings_{column}"), "marketplace_listing_bindings", [column])

    op.create_table(
        "publication_intents",
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("binding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("marketplace", marketplace, nullable=False),
        sa.Column("intent_type", intent_type, nullable=False),
        sa.Column("status", intent_status, nullable=False),
        sa.Column("requested_by", sa.String(length=120), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("approved_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("listing_hash", sa.String(length=64), nullable=False),
        sa.Column("pricing_hash", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("image_set_hash", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["marketplace_listing_bindings.id"], name="fk_publication_intents_binding", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["listing_id"], ["generic_listing_drafts.id"], name="fk_publication_intents_listing", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_intents")),
        sa.UniqueConstraint("idempotency_key", name="uq_publication_intents_idempotency_key"),
    )
    for column in ("listing_id", "binding_id", "marketplace", "intent_type", "status", "idempotency_key"):
        op.create_index(op.f(f"ix_publication_intents_{column}"), "publication_intents", [column])

    op.create_table(
        "publication_jobs",
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketplace", marketplace, nullable=False),
        sa.Column("job_type", intent_type, nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="1", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("prepared_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dry_run", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["intent_id"], ["publication_intents.id"], name="fk_publication_jobs_intent", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_jobs")),
        sa.UniqueConstraint("idempotency_key", name="uq_publication_jobs_idempotency_key"),
    )
    for column in ("intent_id", "marketplace", "job_type", "status", "next_attempt_at", "error_code", "idempotency_key"):
        op.create_index(op.f(f"ix_publication_jobs_{column}"), "publication_jobs", [column])

    op.create_table(
        "publication_attempts",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", job_status, nullable=False),
        sa.Column("adapter", sa.String(length=120), nullable=False),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("request_summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("response_summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["publication_jobs.id"], name="fk_publication_attempts_job", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_attempts")),
    )
    op.create_index(op.f("ix_publication_attempts_job_id"), "publication_attempts", ["job_id"])
    op.create_index(op.f("ix_publication_attempts_status"), "publication_attempts", ["status"])

    op.create_table(
        "publication_state_history",
        sa.Column("entity_type", sa.String(length=120), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("old_status", sa.String(length=120), nullable=True),
        sa.Column("new_status", sa.String(length=120), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_state_history")),
    )
    for column in ("entity_type", "entity_id", "event_type", "created_at"):
        op.create_index(op.f(f"ix_publication_state_history_{column}"), "publication_state_history", [column])

    op.create_table(
        "operational_alerts",
        sa.Column("type", sa.String(length=120), nullable=False),
        sa.Column("severity", alert_severity, nullable=False),
        sa.Column("entity_type", sa.String(length=120), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", alert_status, nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operational_alerts")),
        sa.UniqueConstraint("dedupe_key", "status", name="uq_operational_alert_dedupe_status"),
    )
    for column in ("type", "severity", "entity_type", "entity_id", "status", "dedupe_key"):
        op.create_index(op.f(f"ix_operational_alerts_{column}"), "operational_alerts", [column])


def downgrade() -> None:
    op.drop_table("operational_alerts")
    op.drop_table("publication_state_history")
    op.drop_table("publication_attempts")
    op.drop_table("publication_jobs")
    op.drop_table("publication_intents")
    op.drop_table("marketplace_listing_bindings")
    bind = op.get_bind()
    for enum_type in (alert_severity, alert_status, sync_state, job_status, intent_status, intent_type, binding_status, marketplace):
        enum_type.drop(bind, checkfirst=True)
