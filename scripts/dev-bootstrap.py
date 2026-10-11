#!/usr/bin/env python3
"""Prepare secrets and privileged accounts for an explicitly authorized demo."""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
ENV_FILE = BACKEND / ".env"


def ensure_local_key() -> None:
    existing = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    additions = []
    if existing and not existing.endswith("\n"):
        additions.append("\n")
    if not any(line.startswith("TICKET_ENCRYPTION_KEY=") for line in existing.splitlines()):
        additions.append(f"TICKET_ENCRYPTION_KEY={Fernet.generate_key().decode('ascii')}\n")
    if not any(line.startswith("SECURITY_HASH_KEY=") for line in existing.splitlines()):
        additions.append(f"SECURITY_HASH_KEY={Fernet.generate_key().decode('ascii')}\n")
    if not any(line.startswith("SESSION_COOKIE_SECURE=") for line in existing.splitlines()):
        additions.append("SESSION_COOKIE_SECURE=false\n")
    if not additions:
        return
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ENV_FILE.open("a", encoding="utf-8") as handle:
        handle.writelines(additions)
    ENV_FILE.chmod(0o600)
    print("Se prepararon las claves locales en backend/.env (no se mostraron sus valores).")


def password_from_prompt(label: str, variable: str) -> str:
    value = os.getenv(variable) or getpass.getpass(f"Contraseña temporal para {label} (mínimo 12 caracteres): ")
    if len(value) < 12:
        raise SystemExit("La contraseña debe tener al menos 12 caracteres.")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea cuentas ficticias privilegiadas solo para desarrollo local.")
    parser.add_argument("--database-url", default="postgresql+psycopg:///nexoeventos")
    parser.add_argument("--organizer-email", default="organizador.demo@example.com")
    parser.add_argument("--operator-email", default="operador.demo@example.com")
    parser.add_argument("--organizer-event", type=int, action="append", default=[1, 2])
    parser.add_argument("--operator-event", type=int, action="append", default=[1])
    parser.add_argument(
        "--operator-only",
        action="store_true",
        help="Prepare only the operator without changing event ownership.",
    )
    parser.add_argument(
        "--deployed-demo",
        action="store_true",
        help="Use protected environment files on an authorized non-production demo host.",
    )
    args = parser.parse_args()
    deployed_demo_allowed = (
        args.deployed_demo
        and os.getenv("NEXO_ALLOW_DEPLOYED_DEMO") == "YES"
        and os.getenv("APP_ENV") == "production"
    )
    if not deployed_demo_allowed:
        if args.deployed_demo or os.getenv("APP_ENV", "development") != "development":
            raise SystemExit("Este procedimiento solo admite desarrollo local o una demo desplegada explícita.")
        ensure_local_key()
    sys.path.insert(0, str(BACKEND))
    from app.auth import hash_password, normalize_email

    organizer_password = None if args.operator_only else password_from_prompt("organizador", "NEXO_DEV_ORGANIZER_PASSWORD")
    operator_password = password_from_prompt("operador", "NEXO_DEV_OPERATOR_PASSWORD")
    engine = create_engine(args.database_url)
    with engine.begin() as connection:
        database = connection.scalar(text("SELECT current_database()"))
        if database != "nexoeventos":
            raise SystemExit(f"Base rechazada: {database}. Este script solo prepara nexoeventos local.")
        organizer_id = None
        if not args.operator_only:
            organizer_id = connection.scalar(text("""
                INSERT INTO users (id, email, display_name, password_hash, role)
                VALUES (gen_random_uuid(), :email, 'Organizador demo', :password_hash, 'organizer')
                ON CONFLICT (email) DO UPDATE SET
                  display_name = EXCLUDED.display_name,
                  password_hash = EXCLUDED.password_hash,
                  role = 'organizer',
                  is_active = true
                RETURNING id
            """), {"email": normalize_email(args.organizer_email), "password_hash": hash_password(organizer_password)})
        operator_id = connection.scalar(text("""
            INSERT INTO users (id, email, display_name, password_hash, role)
            VALUES (gen_random_uuid(), :email, 'Operador demo', :password_hash, 'operator')
            ON CONFLICT (email) DO UPDATE SET
              display_name = EXCLUDED.display_name,
              password_hash = EXCLUDED.password_hash,
              role = 'operator',
              is_active = true
            RETURNING id
        """), {"email": normalize_email(args.operator_email), "password_hash": hash_password(operator_password)})
        if organizer_id is not None:
            for event_id in set(args.organizer_event):
                result = connection.execute(text("UPDATE events SET organizer_user_id = :user_id WHERE id = :event_id"), {
                    "user_id": organizer_id, "event_id": event_id,
                })
                if result.rowcount != 1:
                    raise SystemExit(f"No existe el evento {event_id} para asignar al organizador.")
        for event_id in set(args.operator_event):
            connection.execute(text("""
                INSERT INTO operator_event_assignments (operator_user_id, event_id)
                VALUES (:user_id, :event_id) ON CONFLICT DO NOTHING
            """), {"user_id": operator_id, "event_id": event_id})
    engine.dispose()
    print("Cuentas ficticias preparadas. Las contraseñas no se guardaron ni se mostraron.")
    if args.operator_only:
        print(f"Operador: {args.operator_email}; propietarios de eventos sin cambios.")
    else:
        print(f"Organizador: {args.organizer_email}; operador: {args.operator_email}.")


if __name__ == "__main__":
    main()
