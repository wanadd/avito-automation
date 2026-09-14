"""add operator auth and production readiness tables

Revision ID: 202609110012
Revises: 202609110011
Create Date: 2026-09-14 00:12:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110012"
down_revision: str | None = "202609110011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

operator_role = postgresql.ENUM("ADMIN", "OPERATOR", "VIEWER", name="operator_role", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    operator_role.create(bind, checkfirst=True)

    op.create_table(
        "operator_users",
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", operator_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operator_users")),
        sa.UniqueConstraint("username", name="uq_operator_users_username"),
    )
    for column in ("username", "role", "is_active"):
        op.create_index(op.f(f"ix_operator_users_{column}"), "operator_users", [column])

    op.create_table(
        "operator_sessions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", sa.String(length=120), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["operator_users.id"], name="fk_operator_sessions_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operator_sessions")),
        sa.UniqueConstraint("token_hash", name="uq_operator_sessions_token_hash"),
    )
    for column in ("user_id", "token_hash", "csrf_token_hash", "expires_at", "revoked_at"):
        op.create_index(op.f(f"ix_operator_sessions_{column}"), "operator_sessions", [column])

    op.create_table(
        "login_failures",
        sa.Column("identity_key", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("ip_address", sa.String(length=120), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_failures")),
    )
    for column in ("identity_key", "username", "failed_at"):
        op.create_index(op.f(f"ix_login_failures_{column}"), "login_failures", [column])


def downgrade() -> None:
    op.drop_table("login_failures")
    op.drop_table("operator_sessions")
    op.drop_table("operator_users")
    operator_role.drop(op.get_bind(), checkfirst=True)
