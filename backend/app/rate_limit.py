import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import LOGIN_BLOCK_MINUTES, LOGIN_MAX_FAILURES, LOGIN_WINDOW_MINUTES, security_hash_key
from app.models import AuthRateLimit


class LoginRateLimitedError(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = max(1, retry_after_seconds)


def login_rate_key(email: str, source_address: str) -> str:
    material = f"{email.strip().lower()}|{source_address}".encode("utf-8")
    return hmac.new(security_hash_key().encode("utf-8"), material, hashlib.sha256).hexdigest()


def check_login_allowed(session: Session, key_hash: str) -> None:
    item = session.get(AuthRateLimit, key_hash)
    now = datetime.now(timezone.utc)
    if item and item.blocked_until and item.blocked_until > now:
        raise LoginRateLimitedError(int((item.blocked_until - now).total_seconds()))


def record_login_failure(session: Session, key_hash: str) -> None:
    now = datetime.now(timezone.utc)
    item = session.scalar(select(AuthRateLimit).where(AuthRateLimit.key_hash == key_hash).with_for_update())
    if item is None:
        item = AuthRateLimit(key_hash=key_hash, failed_count=1, window_started_at=now, updated_at=now)
        session.add(item)
    elif item.window_started_at <= now - timedelta(minutes=LOGIN_WINDOW_MINUTES):
        item.failed_count = 1
        item.window_started_at = now
        item.blocked_until = None
        item.updated_at = now
    else:
        item.failed_count += 1
        item.updated_at = now
    if item.failed_count >= LOGIN_MAX_FAILURES:
        item.blocked_until = now + timedelta(minutes=LOGIN_BLOCK_MINUTES)
    session.commit()
    if item.blocked_until and item.blocked_until > now:
        raise LoginRateLimitedError(int((item.blocked_until - now).total_seconds()))


def clear_login_failures(session: Session, key_hash: str) -> None:
    item = session.get(AuthRateLimit, key_hash)
    if item is not None:
        session.delete(item)
