import hashlib
import secrets

from cryptography.fernet import Fernet

from app.config import ticket_encryption_key


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_fingerprint(token: str) -> str:
    return token_hash(token)[:16]


def create_ticket_secret() -> tuple[str, str, str]:
    token = f"nexo_{secrets.token_urlsafe(32)}"
    ciphertext = Fernet(ticket_encryption_key().encode("ascii")).encrypt(token.encode("utf-8")).decode("ascii")
    return token, token_hash(token), ciphertext


def reveal_ticket_secret(ciphertext: str) -> str:
    return Fernet(ticket_encryption_key().encode("ascii")).decrypt(ciphertext.encode("ascii")).decode("utf-8")
