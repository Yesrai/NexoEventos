import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
SESSION_COOKIE = "nexoeventos_session"
CSRF_COOKIE = "nexoeventos_csrf"
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "8"))
COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_WINDOW_MINUTES = int(os.getenv("LOGIN_WINDOW_MINUTES", "15"))
LOGIN_BLOCK_MINUTES = int(os.getenv("LOGIN_BLOCK_MINUTES", "15"))


def _origins() -> frozenset[str]:
    configured = os.getenv("FRONTEND_ORIGINS")
    if configured:
        return frozenset(value.strip().rstrip("/") for value in configured.split(",") if value.strip())
    return frozenset({"http://localhost:5173", "http://127.0.0.1:5173", "http://testserver"})


ALLOWED_ORIGINS = _origins()


def ticket_encryption_key() -> str:
    value = os.getenv("TICKET_ENCRYPTION_KEY")
    if not value:
        raise RuntimeError("Falta TICKET_ENCRYPTION_KEY. Ejecuta scripts/dev-bootstrap.py antes de iniciar el backend.")
    return value


def security_hash_key() -> str:
    value = os.getenv("SECURITY_HASH_KEY")
    if value:
        return value
    if APP_ENV == "development" or APP_ENV == "test":
        return ticket_encryption_key()
    raise RuntimeError("Falta SECURITY_HASH_KEY para derivar identificadores de seguridad.")


def validate_production_config() -> None:
    if APP_ENV != "production":
        return
    if not COOKIE_SECURE:
        raise RuntimeError("SESSION_COOKIE_SECURE debe ser true en producción.")
    if not ALLOWED_ORIGINS or any(not origin.startswith("https://") for origin in ALLOWED_ORIGINS):
        raise RuntimeError("FRONTEND_ORIGINS debe contener únicamente orígenes HTTPS explícitos en producción.")
    ticket_encryption_key()
    security_hash_key()
