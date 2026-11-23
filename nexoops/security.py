"""Primitivas de seguridad: Argon2id, OTP criptográfico (verificador HMAC), tokens de sesión (solo se guarda su SHA-256)."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)       # Argon2id (valor por defecto de argon2-cffi)
_DUMMY = _ph.hash("nexoops-dummy-password")


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(stored: str | None, pw: str) -> bool:
    """Siempre cuesta un Argon2: un usuario inexistente no se distingue por tiempo."""
    try:
        return _ph.verify(stored or _DUMMY, pw) and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_otp() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def otp_verifier(secret: bytes, challenge_id: str, code: str) -> str:
    return hmac.new(secret, f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def new_token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def ct_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
