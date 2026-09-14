import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import OperatorRole


class OperatorUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operator_users"
    __table_args__ = (UniqueConstraint("username", name="uq_operator_users_username"),)

    username: Mapped[str] = mapped_column(String(120), index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[OperatorRole] = mapped_column(Enum(OperatorRole, name="operator_role"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sessions = relationship("OperatorSession", back_populates="user")


class OperatorSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "operator_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("operator_users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("OperatorUser", back_populates="sessions")


class LoginFailure(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "login_failures"

    identity_key: Mapped[str] = mapped_column(String(255), index=True)
    username: Mapped[str] = mapped_column(String(120), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(120), nullable=True)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
