import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.audit_log import AuditLog
from app.models.enums import OperatorRole
from app.models.operator import LoginFailure, OperatorSession, OperatorUser

SESSION_COOKIE = "avito_operator_session"
CSRF_COOKIE = "avito_operator_csrf"
CSRF_HEADER = "x-csrf-token"

_password_hasher = PasswordHasher()


@dataclass(frozen=True)
class AuthenticatedOperator:
    user: OperatorUser
    session: OperatorSession


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _hash_secret(value: str) -> str:
    secret = get_settings().session_secret.encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", maxsplit=1)[0].strip()
    return request.client.host if request.client else "unknown"


def _set_auth_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.session_ttl_seconds,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


async def create_operator_user(session: AsyncSession, username: str, password: str, role: OperatorRole) -> OperatorUser:
    existing = await session.scalar(select(OperatorUser).where(OperatorUser.username == username))
    if existing is not None:
        raise ValueError("OPERATOR_USERNAME_EXISTS")
    user = OperatorUser(username=username, password_hash=hash_password(password), role=role, is_active=True)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate_operator(
    session: AsyncSession,
    response: Response,
    request: Request,
    *,
    username: str,
    password: str,
) -> tuple[OperatorUser, str, datetime]:
    await enforce_login_rate_limit(session, username, _client_ip(request))
    user = await session.scalar(select(OperatorUser).where(OperatorUser.username == username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        await record_login_failure(session, username, _client_ip(request))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    await session.execute(delete(LoginFailure).where(LoginFailure.identity_key == login_identity_key(username, _client_ip(request))))
    session_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(seconds=get_settings().session_ttl_seconds)
    operator_session = OperatorSession(
        user_id=user.id,
        token_hash=_hash_secret(session_token),
        csrf_token_hash=_hash_secret(csrf_token),
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
        expires_at=expires_at,
        last_seen_at=_now(),
    )
    user.last_login_at = _now()
    session.add(operator_session)
    session.add(AuditLog(entity_type="OperatorUser", entity_id=user.id, action="OPERATOR_LOGIN", old_value=None, new_value={"role": user.role.value}, actor_type="WEB_OPERATOR", actor_id=str(user.id)))
    await session.commit()
    await session.refresh(user)
    _set_auth_cookies(response, session_token, csrf_token)
    return user, csrf_token, expires_at


def login_identity_key(username: str, ip_address: str) -> str:
    return hashlib.sha256(f"{username.lower()}:{ip_address}".encode("utf-8")).hexdigest()


async def enforce_login_rate_limit(session: AsyncSession, username: str, ip_address: str) -> None:
    settings = get_settings()
    since = _now() - timedelta(seconds=settings.login_rate_limit_window_seconds)
    key = login_identity_key(username, ip_address)
    count = await session.scalar(select(func.count()).select_from(LoginFailure).where(LoginFailure.identity_key == key, LoginFailure.failed_at >= since))
    if count >= settings.login_rate_limit_failures:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")


async def record_login_failure(session: AsyncSession, username: str, ip_address: str) -> None:
    session.add(LoginFailure(identity_key=login_identity_key(username, ip_address), username=username, ip_address=ip_address))
    await session.commit()


async def get_authenticated_operator(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> AuthenticatedOperator:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    operator_session = await session.scalar(
        select(OperatorSession).where(
            OperatorSession.token_hash == _hash_secret(token),
            OperatorSession.revoked_at.is_(None),
            OperatorSession.expires_at > _now(),
        )
    )
    if operator_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    user = await session.get(OperatorUser, operator_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    operator_session.last_seen_at = _now()
    await session.commit()
    return AuthenticatedOperator(user=user, session=operator_session)


async def require_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias=CSRF_HEADER),
    auth: AuthenticatedOperator = Depends(get_authenticated_operator),
) -> AuthenticatedOperator:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return auth
    cookie_token = request.cookies.get(CSRF_COOKIE)
    if not cookie_token or not x_csrf_token or cookie_token != x_csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")
    if auth.session.csrf_token_hash != _hash_secret(x_csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")
    return auth


def require_role(*roles: OperatorRole):
    async def dependency(auth: AuthenticatedOperator = Depends(require_csrf)) -> AuthenticatedOperator:
        if auth.user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return auth

    return dependency


async def revoke_current_session(
    response: Response,
    auth: AuthenticatedOperator,
    session: AsyncSession,
) -> None:
    auth.session.revoked_at = _now()
    session.add(AuditLog(entity_type="OperatorSession", entity_id=auth.session.id, action="OPERATOR_LOGOUT", old_value=None, new_value=None, actor_type="WEB_OPERATOR", actor_id=str(auth.user.id)))
    await session.commit()
    clear_auth_cookies(response)


async def get_operator_by_id(session: AsyncSession, user_id: uuid.UUID) -> OperatorUser | None:
    return await session.get(OperatorUser, user_id)
