#!/usr/bin/env python3
"""Administración CONTROLADA del vallado en la base (pg_fence) para la prueba híbrida. NUNCA se ejecuta sola: `precheck`, `attest` y `status` solo leen (el precheck hace sus intentos dentro de UNA
transacción que se DESHACE); `install` y `uninstall` modifican la base y exigen NEXO_ALLOW_DB_CHANGE=YES y la frase de confirmación exacta. Las credenciales van en ARCHIVOS 0600 (DSN en formato
de conexión de libpq), nunca en argumentos ni en variables.
Seguridad ante fallos parciales: install y uninstall van en UNA transacción (BEGIN…COMMIT) con lock_timeout y statement_timeout cortos; si algo falla —o la conexión muere a medias— PostgreSQL deshace TODO.
`--state-file` guarda la huella del catálogo ANTES de instalar y `uninstall` la compara DESPUÉS de revertir (debe ser idéntica): esa es la prueba de reversión, no el snapshot del RDS.
Uso: fence_admin.py precheck   --admin-dsn-file F --app-role R [--schema public]
     fence_admin.py snapshot   --admin-dsn-file F [--schema public] [--roles a,b]
     fence_admin.py create-role|drop-role --admin-dsn-file F --keeper-role K [--keeper-password-file P] --confirm "CREAR ROL GUARDIAN"|"ELIMINAR ROL GUARDIAN"
     fence_admin.py lab-create|lab-drop --admin-dsn-file F --lab-db nexo_fence_lab --confirm "CREAR BASE DE LABORATORIO"|"ELIMINAR BASE DE LABORATORIO"
     fence_admin.py install    --admin-dsn-file F --app-role R --keeper-role K [--no-event-trigger] --confirm "INSTALAR VALLADO EN LA BASE"
     fence_admin.py attest     --keeper-dsn-file F --app-role R
     fence_admin.py uninstall  --admin-dsn-file F [--keeper-role K --drop-role] --confirm "REVERTIR VALLADO EN LA BASE"
Códigos: 0 correcto · 1 precheck/atestación negativos · 2 uso o credenciales · 3 confirmación ausente."""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "scripts/multicloud/failover"))
from app.failover.pg_fence import PgFence, catalog_snapshot, install_sql, precheck, precheck_readonly, uninstall_sql  # noqa: E402
from pg_standby import PsycopgExecutor  # noqa: E402

CONFIRM_INSTALL, CONFIRM_UNINSTALL = "INSTALAR VALLADO EN LA BASE", "REVERTIR VALLADO EN LA BASE"
CONFIRMS = {"install": CONFIRM_INSTALL, "uninstall": CONFIRM_UNINSTALL, "create-role": "CREAR ROL GUARDIAN", "drop-role": "ELIMINAR ROL GUARDIAN", "lab-create": "CREAR BASE DE LABORATORIO", "lab-drop": "ELIMINAR BASE DE LABORATORIO"}
import re  # noqa: E402
IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def executor(dsn_file: str) -> PsycopgExecutor:
    p = Path(dsn_file)
    if not p.is_file() or stat.S_IMODE(p.stat().st_mode) & 0o077:
        raise PermissionError("el archivo de credenciales debe existir con permisos 0600")
    dsn = p.read_text().strip()
    if not dsn or "\n" in dsn:
        raise ValueError("DSN vacío o con varias líneas")
    return PsycopgExecutor(conninfo=dsn)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["precheck", "install", "attest", "uninstall", "status", "snapshot", "create-role", "drop-role", "lab-create", "lab-drop"])
    ap.add_argument("--state-file"); ap.add_argument("--read-only", action="store_true", help="precheck puro de lectura (B2): sin DDL de prueba"); ap.add_argument("--roles", default=""); ap.add_argument("--keeper-password-file"); ap.add_argument("--lab-db", default="nexo_fence_lab")
    ap.add_argument("--lock-timeout", default="5s"); ap.add_argument("--statement-timeout", default="120s")
    ap.add_argument("--admin-dsn-file"); ap.add_argument("--keeper-dsn-file"); ap.add_argument("--app-role", default="nexoeventos_app"); ap.add_argument("--keeper-role", default="nexo_fence_keeper")
    ap.add_argument("--schema", default="public"); ap.add_argument("--no-event-trigger", action="store_true"); ap.add_argument("--drop-role", action="store_true"); ap.add_argument("--confirm", default="")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "precheck" and a.read_only:
            r = precheck_readonly(executor(a.admin_dsn_file), app_role=a.app_role, schema=a.schema)
            print(json.dumps({k: v for k, v in r.items() if k != "current_user"}, indent=1, default=str, ensure_ascii=False)); return 0 if not r["blockers"] else 1
        if a.cmd == "precheck":
            r = precheck(executor(a.admin_dsn_file), app_role=a.app_role, schema=a.schema, local_now=datetime.now(timezone.utc))
            print(json.dumps({k: v for k, v in r.items() if k != "current_user"}, indent=1, default=str, ensure_ascii=False)); return 0 if r["ok_to_install"] else 1
        if a.cmd in ("attest", "status"):
            f = PgFence(executor(a.keeper_dsn_file), app_role=a.app_role)
            out = f.attest() if a.cmd == "attest" else f.status()
            print(json.dumps(out, indent=1, default=str, ensure_ascii=False)); return 0 if (a.cmd == "status" or out.get("ok")) else 1
        if a.cmd == "snapshot":
            print(json.dumps(catalog_snapshot(executor(a.admin_dsn_file), schema=a.schema, roles=tuple(r for r in a.roles.split(",") if r)))); return 0
        # --- cambios: doble llave
        if os.environ.get("NEXO_ALLOW_DB_CHANGE") != "YES" or a.confirm != CONFIRMS[a.cmd]:
            print("RECHAZADO: falta NEXO_ALLOW_DB_CHANGE=YES y la frase de confirmación exacta.", file=sys.stderr); return 3
        ex = executor(a.admin_dsn_file)
        guard = f"SET LOCAL lock_timeout = '{a.lock_timeout}'; SET LOCAL statement_timeout = '{a.statement_timeout}';"
        roles = tuple(r for r in (a.keeper_role, a.app_role) if r)
        if a.cmd in ("lab-create", "lab-drop"):
            if not IDENT.match(a.lab_db) or a.lab_db in ("postgres", "template0", "template1") or "nexoeventos" in a.lab_db:
                print("ERROR: nombre de base de laboratorio no permitido (no puede ser la de producción ni una del sistema)", file=sys.stderr); return 2
            ex(f'CREATE DATABASE "{a.lab_db}"' if a.cmd == "lab-create" else f'DROP DATABASE "{a.lab_db}"')
            print(f"OK    base de laboratorio {'creada' if a.cmd == 'lab-create' else 'eliminada'}: {a.lab_db}"); return 0
        if a.cmd in ("create-role", "drop-role"):
            if not IDENT.match(a.keeper_role):
                print("ERROR: nombre de rol no válido", file=sys.stderr); return 2
            if a.cmd == "create-role":
                pw = Path(a.keeper_password_file).read_text().strip() if a.keeper_password_file else None
                if not pw or len(pw) < 24:
                    print("ERROR: --keeper-password-file con una contraseña de al menos 24 caracteres (archivo 0600)", file=sys.stderr); return 2
                ex(f"CREATE ROLE \"{a.keeper_role}\" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '{pw.replace(chr(39), chr(39) * 2)}'")
                print(f"OK    rol guardián creado: {a.keeper_role}"); return 0
            ex(f'DROP ROLE IF EXISTS "{a.keeper_role}"'); print(f"OK    rol guardián eliminado: {a.keeper_role}"); return 0
        if a.cmd in ("install", "uninstall"):
            from psycopg.conninfo import conninfo_to_dict
            dbname = conninfo_to_dict(Path(a.admin_dsn_file).read_text().strip()).get("dbname", "")
            if not dbname.startswith("nexo_fence_lab") and os.environ.get("NEXO_ALLOW_BUSINESS_DB") != "YES":
                print("RECHAZADO: el vallado solo se instala/revierte en una base de LABORATORIO (nombre nexo_fence_lab*), nunca en la base de negocio (triggers en las tablas reales). "
                      "Excepción deliberada: NEXO_ALLOW_BUSINESS_DB=YES (no forma parte de la prueba híbrida).", file=sys.stderr); return 3
        if a.cmd == "install":
            r = precheck(ex, app_role=a.app_role, schema=a.schema)
            if not r["ok_to_install"]:
                print(json.dumps({"bloqueos": r["blockers"]}, ensure_ascii=False, indent=1)); return 1
            snap = catalog_snapshot(ex, schema=a.schema, roles=roles)
            if a.state_file:
                fd = os.open(a.state_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)       # no se sobrescribe la huella de un estado previo
                with os.fdopen(fd, "w") as f: json.dump({"antes": snap, "roles": list(roles), "schema": a.schema}, f)
            ex("BEGIN;\n" + guard + "\n" + install_sql(app_role=a.app_role, keeper_role=a.keeper_role, schema=a.schema, event_trigger=(r["install_mode"] == "event_trigger" and not a.no_event_trigger)) + "\nCOMMIT;")
            print(f"OK    vallado instalado (modo {r['install_mode']}); verifique con «attest» antes de usarlo"); return 0
        ex("BEGIN;\n" + guard + "\n" + uninstall_sql(schema=a.schema, keeper_role=a.keeper_role, drop_role=a.drop_role) + "\nCOMMIT;")
        left = ex("SELECT (SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'nexo_fence_%'), (SELECT count(*) FROM pg_namespace WHERE nspname = 'nexo_fence')")[0]
        msg = f"OK    vallado revertido (triggers restantes: {left[0]}, esquema nexo_fence: {left[1]})"
        if a.state_file and Path(a.state_file).is_file():
            st = json.loads(Path(a.state_file).read_text()); after = catalog_snapshot(ex, schema=st["schema"], roles=tuple(st["roles"]))
            same = after == st["antes"]
            msg += f"; huella del catálogo {'IDÉNTICA a la previa' if same else 'DISTINTA de la previa'}"
            if not same:
                print(msg); return 1
        print(msg); return 0 if tuple(left) == (0, 0) else 1
    except (PermissionError, ValueError, OSError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())
