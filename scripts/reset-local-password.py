#!/usr/bin/env python3
"""Restablece la contraseña de UNA cuenta en la base LOCAL de desarrollo.

La demo no tiene recuperación de contraseña. Esta herramienta es solo para tu Mac: pide la
contraseña por teclado (no se imprime ni queda en el historial), conserva la cuenta y sus
reservas, cierra sus sesiones y limpia los bloqueos por intentos fallidos.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import create_engine, text  # noqa: E402

from app.auth import hash_password  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("--database-url", default="postgresql+psycopg:///nexoeventos")
    args = parser.parse_args()
    if "rds.amazonaws.com" in args.database_url or "azure" in args.database_url:
        raise SystemExit("Solo para la base local; se rechaza una base en la nube.")
    password = getpass.getpass("Nueva contraseña (12–128 caracteres): ")
    if not 12 <= len(password) <= 128 or password != getpass.getpass("Repite la contraseña: "):
        raise SystemExit("La contraseña debe tener entre 12 y 128 caracteres y coincidir en ambas entradas.")
    email = args.email.strip().lower()
    engine = create_engine(args.database_url)
    with engine.begin() as connection:
        user_id = connection.scalar(text("SELECT id FROM users WHERE email = :email"), {"email": email})
        if user_id is None:
            raise SystemExit("No existe una cuenta con ese correo.")
        connection.execute(text("UPDATE users SET password_hash = :hash WHERE id = :id"), {"hash": hash_password(password), "id": user_id})
        connection.execute(text("DELETE FROM auth_sessions WHERE user_id = :id"), {"id": user_id})
        connection.execute(text("DELETE FROM auth_rate_limits"))
    print("Contraseña actualizada. Ya puedes iniciar sesión con ese correo.")


if __name__ == "__main__":
    main()
