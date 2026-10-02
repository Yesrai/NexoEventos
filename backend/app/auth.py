import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from typing import Annotated, Callable

from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ALLOWED_ORIGINS, COOKIE_SECURE, CSRF_COOKIE, SESSION_COOKIE, SESSION_HOURS
from app.database import get_session
from app.models import AuthSession, User

password_hash = PasswordHash.recommended()
_dummy_hash = password_hash.hash(secrets.token_urlsafe(32))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def verify_login(session: Session, email: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.email == normalize_email(email)))
    valid = verify_password(password, user.password_hash if user else _dummy_hash)
    return user if user and user.is_active and valid else None


def issue_session(session: Session, user: User) -> tuple[str, str, datetime]:
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    session.add(AuthSession(
        token_hash=digest(raw_token),
        user_id=user.id,
        csrf_hash=digest(csrf_token),
        expires_at=expires_at,
    ))
    return raw_token, csrf_token, expires_at


def set_session_cookies(response: Response, raw_token: str, csrf_token: str) -> None:
    max_age = SESSION_HOURS * 60 * 60
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=max_age,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax", secure=COOKIE_SECURE, httponly=True)
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="lax", secure=COOKIE_SECURE, httponly=False)


@dataclass(frozen=True)
class AuthContext:
    user: User
    auth_session: AuthSession


def get_auth_context(
    session: Session = Depends(get_session),
    raw_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> AuthContext:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión requerida")
    if not raw_token:
        raise unauthorized
    auth_session = session.get(AuthSession, digest(raw_token))
    if auth_session is None:
        raise unauthorized
    if auth_session.expires_at <= datetime.now(timezone.utc):
        session.delete(auth_session)
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión expirada")
    user = session.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return AuthContext(user=user, auth_session=auth_session)


def require_role(*roles: str) -> Callable[..., AuthContext]:
    def dependency(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if context.user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permiso insuficiente")
        return context

    return dependency


def require_csrf(
    request: Request,
    context: AuthContext = Depends(get_auth_context),
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext:
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Origen no permitido")
    if not csrf_token or not compare_digest(digest(csrf_token), context.auth_session.csrf_hash):
        raise HTTPException(status_code=403, detail="Token CSRF inválido")
    return context


def require_csrf_role(*roles: str) -> Callable[..., AuthContext]:
    def dependency(context: AuthContext = Depends(require_csrf)) -> AuthContext:
        if context.user.role not in roles:
            raise HTTPException(status_code=403, detail="Permiso insuficiente")
        return context

    return dependency


def verify_public_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Origen no permitido")
