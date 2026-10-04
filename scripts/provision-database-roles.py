#!/usr/bin/env python3
"""Create isolated NexoEventos owner, migration, and application roles."""
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
    migration_password = os.getenv("NEXO_MIGRATION_DATABASE_PASSWORD") or getpass.getpass(
        "Contraseña nueva para nexoeventos_migrator (no se mostrará): "
    )
    app_password = os.getenv("NEXO_APP_DATABASE_PASSWORD") or getpass.getpass(
        "Contraseña nueva para nexoeventos_app (no se mostrará): "
    )
    if len(migration_password) < 20 or len(app_password) < 20:
        raise SystemExit("Las contraseñas de migración y aplicación deben tener al menos 20 caracteres.")
    if migration_password == app_password:
        raise SystemExit("Las identidades de migración y aplicación deben usar contraseñas distintas.")

    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            database, administrative_user = cursor.execute(
                "SELECT current_database(), current_user"
            ).fetchone()
            if database != args.database_name:
                raise SystemExit(f"Base rechazada: {database}; se esperaba {args.database_name}.")
            if administrative_user in {"nexoeventos_app", "nexoeventos_migrator"}:
                raise SystemExit("La preparación de roles requiere la identidad administrativa de RDS.")

            for role, login in (
                ("nexoeventos_owner", False),
                ("nexoeventos_migrator", True),
                ("nexoeventos_app", True),
            ):
                exists = cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
                if not exists:
                    cursor.execute(
                        # PostgreSQL defaults new roles to NOSUPERUSER, NOCREATEDB,
                        # NOCREATEROLE, NOREPLICATION and NOBYPASSRLS.  Do not
                        # spell those attributes out: an RDS administrative role
                        # is intentionally unable to change some of them.
                        sql.SQL("CREATE ROLE {} {}").format(
                            sql.Identifier(role), sql.SQL("LOGIN" if login else "NOLOGIN")
                        )
                    )

            role_rows = cursor.execute(
                """
                SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                       rolreplication, rolbypassrls
                  FROM pg_roles
                 WHERE rolname = ANY(%s)
                """,
                (["nexoeventos_owner", "nexoeventos_migrator", "nexoeventos_app"],),
            ).fetchall()
            roles = {row[0]: row[1:] for row in role_rows}
            expected_login = {
                "nexoeventos_owner": False,
                "nexoeventos_migrator": True,
                "nexoeventos_app": True,
            }
            for role, should_login in expected_login.items():
                attributes = roles.get(role)
                if attributes is None:
                    raise SystemExit(f"No se pudo preparar el rol requerido: {role}.")
                (
                    can_login,
                    is_superuser,
                    can_create_db,
                    can_create_role,
                    can_replicate,
                    bypasses_rls,
                ) = attributes
                if can_login != should_login:
                    raise SystemExit(f"El atributo LOGIN preexistente no es el esperado para {role}.")
                if any((is_superuser, can_create_db, can_create_role, can_replicate, bypasses_rls)):
                    raise SystemExit(
                        f"El rol preexistente {role} tiene atributos elevados; se rechaza modificarlo automáticamente."
                    )

            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier("nexoeventos_migrator"), sql.Literal(migration_password)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier("nexoeventos_app"), sql.Literal(app_password)
                )
            )
            cursor.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier("nexoeventos_owner"), sql.Identifier("nexoeventos_migrator")
                )
            )
            cursor.execute("ALTER SCHEMA public OWNER TO nexoeventos_owner")
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute("GRANT USAGE ON SCHEMA public TO nexoeventos_app")
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO nexoeventos_app").format(sql.Identifier(database))
            )

            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO nexoeventos_migrator").format(
                    sql.Identifier(database)
                )
            )

    print(
        "Roles owner/migrator/app preparados y comprobados sin atributos elevados; "
        "no se mostró ninguna contraseña."
    )


if __name__ == "__main__":
    main()
