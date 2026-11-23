#!/usr/bin/env python3
"""PROCEDIMIENTO (solo texto: NO ejecuta nada) para instalar el vallado en las TABLAS DE NEGOCIO de la RDS real SIN cambiar sus propietarios. Reproduce los roles de scripts/provision-database-roles.py:
`nexoeventos_owner` (NOLOGIN, posee las tablas y el esquema public), `nexoeventos_migrator` (LOGIN, miembro del propietario: ya existe y su credencial ya está en la EC2), `nexoeventos_app` (solo DML) y el administrador
`nexoeventos_admin` (rds_superuser; NO propietario). Roles nuevos: `nexo_fence_owner` (NOLOGIN; dueño del esquema nexo_fence; recibe TRIGGER, no la propiedad) y `nexo_fence_guardian` (LOGIN; solo EXECUTE).
Comprobaciones previas de SOLO LECTURA (la fase 0 depende de quién posea la base). Cada fase la ejecuta una identidad distinta; esto está probado en local sobre las 14 tablas reales (test_business_install.py).
  plan [--database nexoeventos]            imprime fases, ejecutor y SQL            |   preguntas   imprime las consultas de solo lectura que decide qué variante aplica"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.failover.pg_fence import db_grants_sql, db_revoke_sql, install_sql, owner_grants_sql, owner_revoke_sql, uninstall_sql, uninstall_triggers_sql  # noqa: E402

OWNER, APP, FO, KP = "nexoeventos_owner", "nexoeventos_app", "nexo_fence_owner", "nexo_fence_guardian"

PREGUNTAS = [
    "SELECT datname, pg_get_userbyid(datdba) AS propietario_de_la_base FROM pg_database WHERE datname = 'nexoeventos';          -- ¿quién puede conceder CREATE/CONNECT sobre la base? (fase 0)",
    "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname IN ('nexoeventos_owner','nexoeventos_migrator','nexoeventos_app','nexo_fence_owner','nexo_fence_guardian');",
    "SELECT pg_get_userbyid(roleid) AS rol, pg_get_userbyid(member) AS miembro, admin_option, inherit_option, set_option FROM pg_auth_members WHERE roleid = 'nexoeventos_owner'::regrole;   -- ¿el migrador es miembro y puede SET ROLE?",
    "SELECT nspname, pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'public';          -- debe ser nexoeventos_owner",
    "SELECT count(*), bool_and(pg_get_userbyid(relowner) = 'nexoeventos_owner') FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r';",
]


def plan(database: str = "nexoeventos") -> list[dict]:
    admin_owns = f"-- (si la base la posee el ADMINISTRADOR) fase 0, ejecutada por nexoeventos_admin:\n{db_grants_sql(fence_owner=FO, keeper_role=KP, database=database)}"
    return [
        {"fase": "0 · roles nuevos (administrador)", "ejecuta": "nexoeventos_admin (credencial administrativa; se lee en la EC2 y no se imprime)",
         "sql": f"CREATE ROLE {FO} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;\nGRANT {FO} TO nexoeventos_admin WITH INHERIT FALSE, SET TRUE;\nCREATE ROLE {KP} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '<generada en la EC2, 0600, no se imprime>';\n{admin_owns}"},
        {"fase": "1 · concesiones del PROPIETARIO (sin cambiar propiedad)", "ejecuta": "nexoeventos_migrator (miembro del propietario; SET ROLE nexoeventos_owner)",
         "sql": owner_grants_sql(owner_role=OWNER, fence_owner=FO, app_role=APP, database=database, keeper_role=KP, include_db_grants=False) + "-- (si la base la posee el propietario: usar include_db_grants=True en lugar de la fase 0 del administrador)"},
        {"fase": "2 · precheck con DDL y atestación previa", "ejecuta": "nexoeventos_admin actuando como nexo_fence_owner (SET ROLE)", "sql": "-- pg_fence.precheck(..., acting_role='nexo_fence_owner') debe dar ok_to_install=true (modo keeper_attach: sin event triggers)"},
        {"fase": "3 · instalación", "ejecuta": "nexoeventos_admin (SET ROLE nexo_fence_owner dentro de una transacción con lock_timeout)", "sql": "BEGIN;\n" + install_sql(app_role=APP, keeper_role=KP, event_trigger=False, fence_owner=FO)[:420] + "\n-- … (install_sql completo)\nCOMMIT;"},
        {"fase": "R-A · reversión: triggers", "ejecuta": "nexoeventos_migrator (propietario)", "sql": uninstall_triggers_sql(owner_role=OWNER)},
        {"fase": "R-B · reversión: objetos del vallado", "ejecuta": "nexoeventos_admin como nexo_fence_owner", "sql": uninstall_sql(keeper_role=KP, fence_owner=FO, drop_triggers=False)[:300] + "\n-- … (RESTRICT: si algo ajeno depende, falla entero)"},
        {"fase": "R-C · reversión: concesiones", "ejecuta": "nexoeventos_migrator (propietario) [+ administrador para las de base]", "sql": owner_revoke_sql(owner_role=OWNER, fence_owner=FO, app_role=APP, database=database, keeper_role=KP, include_db_grants=False) + db_revoke_sql(fence_owner=FO, keeper_role=KP, database=database)},
        {"fase": "R-D · reversión: roles", "ejecuta": "nexoeventos_admin", "sql": f"DROP ROLE {KP};\nDROP ROLE {FO};"},
    ]


NOTAS = [
    "Las MIGRACIONES de Alembic ESCRIBEN en alembic_version: con el vallado instalado exigen autoridad vigente y la época declarada (PGOPTIONS='-c nexo.writer_epoch=<época>'): se ejecutan en ventana de mantenimiento con el guardián concediendo autoridad.",
    "Una tabla nueva creada por el propietario recibe TRIGGER para nexo_fence_owner por los privilegios por defecto; el guardián la engancha con attach_all() (sin event trigger) y mientras no esté cubierta NO se concede autoridad.",
    "BLOQUEO si: el migrador no es miembro del propietario o no puede SET ROLE; la base la posee un rol del que no se dispone; el administrador no puede crear roles. Entonces se requiere una autorización adicional con el procedimiento exacto.",
    "RIESGO QUE NO DESAPARECE: el administrador (rds_superuser) puede fijar session_replication_role y saltarse los triggers; un administrador comprometido elude cualquier protección basada solo en triggers.",
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["plan", "preguntas"]); ap.add_argument("--database", default="nexoeventos"); a = ap.parse_args(argv)
    if a.cmd == "preguntas":
        print("\n".join(PREGUNTAS)); return 0
    for f in plan(a.database): print(f"=== {f['fase']}\n    ejecuta: {f['ejecuta']}\n{f['sql']}\n")
    print("NOTAS:\n- " + "\n- ".join(NOTAS)); return 0


if __name__ == "__main__":
    sys.exit(main())
