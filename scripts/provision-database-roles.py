#!/usr/bin/env python3
"""Create NexoEventos database roles without embedding their password."""
from __future__ import annotations

import argparse
import getpass
import os

import psycopg
from psycopg import sql


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepara roles exclusivos de NexoEventos antes de Alembic.")
    parser.add_argument("--database-name", default="nexoeventos")
    args = parser.parse_args()

    url = os.getenv("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("Define MIGRATION_DATABASE_URL con la identidad administrativa de migraciones.")
    url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    app_password = os.getenv("NEXO_APP_DATABASE_PASSWORD") or getpass.getpass(
        "Contraseña nueva para nexoeventos_app (no se mostrará): "
    )
    if len(app_password) < 16:
        raise SystemExit("La contraseña de aplicación debe tener al menos 16 caracteres.")

    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            database, migration_user = cursor.execute(
                "SELECT current_database(), current_user"
            ).fetchone()
            if database != args.database_name:
                raise SystemExit(f"Base rechazada: {database}; se esperaba {args.database_name}.")

            for role, login in (("nexoeventos_owner", False), ("nexoeventos_app", True)):
                exists = cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
                if not exists:
                    cursor.execute(
                        sql.SQL("CREATE ROLE {} {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION").format(
                            sql.Identifier(role), sql.SQL("LOGIN" if login else "NOLOGIN")
                        )
                    )

            cursor.execute(
                sql.SQL(
                    "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
                ).format(sql.Identifier("nexoeventos_app"), sql.Literal(app_password))
            )
            cursor.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier("nexoeventos_owner"), sql.Identifier(migration_user)
                )
            )
            cursor.execute("ALTER SCHEMA public OWNER TO nexoeventos_owner")
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute("GRANT USAGE ON SCHEMA public TO nexoeventos_app")
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO nexoeventos_app").format(sql.Identifier(database))
            )

    print("Roles de migración/aplicación preparados; no se mostró ni guardó la contraseña.")


if __name__ == "__main__":
    main()
