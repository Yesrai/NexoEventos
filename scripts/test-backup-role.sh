#!/usr/bin/env bash
# Prueba LOCAL (sin nube) del rol de volcado de mínimo privilegio: PostgreSQL temporal, esquema real (alembic), deploy/backup/backup-role.sql y comprobación de
# qué puede y qué NO puede hacer. No toca ninguna base existente ni la nube. Uso: scripts/test-backup-role.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; PY="$ROOT/backend/.venv/bin/python"
T="$(mktemp -d /private/tmp/bkprole.XXXXXX)"; PORT=55434; DB=nexo_bkp
cleanup() { pg_ctl -D "$T/data" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$T"; }; trap cleanup EXIT
cd "$T"; initdb -D data -U postgres -E UTF8 --locale=C -A trust >/dev/null
printf "port = $PORT\nlisten_addresses = ''\nunix_socket_directories = '$T'\n" >> data/postgresql.conf
printf 'local all postgres trust\nlocal all all scram-sha-256\n' > data/pg_hba.conf
pg_ctl -D data -l log -w start >/dev/null
PGHOST="$T"; PGPORT="$PORT"; export PGHOST PGPORT
psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q <<SQL
CREATE ROLE nexoeventos_owner NOLOGIN; CREATE ROLE nexoeventos_app LOGIN PASSWORD 'solo-prueba-local';
CREATE DATABASE $DB OWNER nexoeventos_owner; REVOKE ALL ON DATABASE $DB FROM PUBLIC; GRANT CONNECT ON DATABASE $DB TO nexoeventos_app;
SQL
( cd "$ROOT/backend" && MIGRATION_DATABASE_URL="postgresql+psycopg://postgres@/$DB?host=$T&port=$PORT" "$PY" -m alembic upgrade head >/dev/null 2>"$T/alembic.err" ) || { echo "FALLÓ alembic:"; tail -12 "$T/alembic.err"; exit 1; }
BKPW="$(openssl rand -base64 24)"; export NEXO_BACKUP_PASSWORD="$BKPW"
psql -U postgres -d "$DB" -At -f "$ROOT/deploy/backup/c04-db-snapshot.sql" > "$T/snap-antes.txt"
psql -U postgres -d "$DB" -v ON_ERROR_STOP=1 -q -f "$ROOT/deploy/backup/backup-role.sql" >/dev/null
psql -U postgres -d "$DB" -v ON_ERROR_STOP=1 -q -f "$ROOT/deploy/backup/backup-role.sql" >/dev/null   # idempotente: la segunda ejecución no falla
unset NEXO_BACKUP_PASSWORD
psql -U postgres -d "$DB" -At -f "$ROOT/deploy/backup/c04-db-snapshot.sql" > "$T/snap-despues.txt"
fail=0; ok() { echo "OK    $1"; }; bad() { echo "FALLÓ $1"; fail=1; }
B() { PGPASSWORD="$BKPW" psql -U nexoeventos_backup -d "$DB" -At -v ON_ERROR_STOP=1 "$@"; }
# --- qué PUEDE ---
B -c "select count(*) from users" >/dev/null && ok "lee tablas (SELECT sobre users)" || bad "no puede leer"
PGPASSWORD="$BKPW" pg_dump -U nexoeventos_backup -d "$DB" -Fc --no-owner --no-acl -f "$T/dump.pgdump" && [[ "$(head -c 5 "$T/dump.pgdump")" == PGDMP ]] && pg_restore --list "$T/dump.pgdump" >/dev/null && ok "pg_dump -Fc genera un volcado PGDMP válido (pg_restore --list)" || bad "pg_dump falló"
B -f "$ROOT/scripts/multicloud/fingerprint.sql" >/dev/null && ok "ejecuta fingerprint.sql (huella de datos) con el rol de solo lectura" || bad "fingerprint.sql falló"
# --- qué NO puede ---
deny() { local nombre="$1"; shift; if B -c "$*" >/dev/null 2>&1; then bad "NO debería poder: $nombre"; else ok "no puede: $nombre"; fi; }
deny "insertar/modificar datos" "update users set display_name = 'x'"
deny "borrar datos" "delete from users"
deny "truncar tablas" "truncate users"
deny "crear tablas" "create table intruso(id int)"
deny "borrar tablas" "drop table users"
deny "crear roles" "create role intruso login"
deny "cambiar su propio rol" "alter role nexoeventos_backup superuser"
deny "crear bases de datos" "create database intruso"
deny "escribir en una transacción explícita de lectura-escritura" "begin read write; update users set display_name = 'x'; commit"
ATTR="$(psql -U postgres -d "$DB" -At -c "select rolsuper::int::text||rolcreatedb::int::text||rolcreaterole::int::text||rolreplication::int::text||rolbypassrls::int::text||rolconnlimit::text from pg_roles where rolname='nexoeventos_backup'")"
[[ "$ATTR" == "000002" ]] && ok "atributos: sin superusuario, createdb, createrole, replicación ni bypassrls; máximo 2 conexiones" || bad "atributos inesperados: $ATTR"
[[ "$(B -c "show default_transaction_read_only")" == on ]] && ok "la sesión es de solo lectura por defecto" || bad "default_transaction_read_only no está en on"
[[ "$(psql -U postgres -d "$DB" -At -c "select count(*) from pg_auth_members m join pg_roles r on r.oid=m.roleid join pg_roles u on u.oid=m.member where u.rolname='nexoeventos_backup'")" == 1 ]] && ok "única membresía: pg_read_all_data" || bad "membresías de rol inesperadas"
# --- la creación del rol NO cambia a los demás roles ni a los objetos existentes (instantánea antes/después) ---
DIFF="$(diff <(grep -vE '^(rol_backup_existe|conexiones)\|' "$T/snap-antes.txt") <(grep -vE '^(rol_backup_existe|conexiones)\|' "$T/snap-despues.txt") || true)"
[[ -z "$DIFF" ]] && ok "instantánea antes/después idéntica (roles, membresías, ACL de tablas/esquemas/base y ACL por defecto de los demás roles)" || bad "la creación del rol cambió algo más: $DIFF"
[[ "$(grep '^rol_backup_existe' "$T/snap-antes.txt")" == "rol_backup_existe|0" && "$(grep '^rol_backup_existe' "$T/snap-despues.txt")" == "rol_backup_existe|1" ]] && ok "el rol no existía antes y existe después" || bad "estado inesperado del rol"
# --- verificación y reversión (solo ese rol) ---
VER="$(psql -U postgres -d "$DB" -At -f "$ROOT/deploy/backup/backup-role-verify.sql" | tr '\n' ' ')"
[[ "$VER" == *"f|f|f|f|f|2"* && "$VER" == *pg_read_all_data* && "$VER" == *default_transaction_read_only=on* && "$VER" == *" 0 "* ]] && ok "backup-role-verify.sql muestra los atributos esperados" || bad "verify inesperado: $VER"
APP_BEFORE="$(psql -U postgres -d "$DB" -At -c "select has_table_privilege('nexoeventos_app','users','SELECT'), has_database_privilege('nexoeventos_app','$DB','CONNECT'), (select count(*) from pg_roles)")"
psql -U postgres -d "$DB" -v ON_ERROR_STOP=1 -q -f "$ROOT/deploy/backup/backup-role-revert.sql" >/dev/null
[[ "$(psql -U postgres -d "$DB" -At -c "select count(*) from pg_roles where rolname='nexoeventos_backup'")" == 0 ]] && ok "backup-role-revert.sql elimina el rol de volcado" || bad "el rol sigue existiendo tras revertir"
APP_AFTER="$(psql -U postgres -d "$DB" -At -c "select has_table_privilege('nexoeventos_app','users','SELECT'), has_database_privilege('nexoeventos_app','$DB','CONNECT'), (select count(*) from pg_roles)")"
EXPECT_AFTER="${APP_BEFORE%|*}|$(( ${APP_BEFORE##*|} - 1 ))"
[[ "$APP_AFTER" == "$EXPECT_AFTER" ]] && ok "la reversión no cambió permisos de otros roles (solo desaparece 1 rol)" || bad "cambios inesperados: antes=$APP_BEFORE después=$APP_AFTER"
# --- sin contraseña no crea nada ---
env -u NEXO_BACKUP_PASSWORD psql -U postgres -d "$DB" -q -f "$ROOT/deploy/backup/backup-role.sql" >/dev/null 2>&1 || true
[[ "$(psql -U postgres -d "$DB" -At -c "select count(*) from pg_roles where rolname='nexoeventos_backup'")" == 0 ]] && ok "sin NEXO_BACKUP_PASSWORD no se crea el rol" || bad "creó el rol sin contraseña"
((fail)) && { echo "Hay fallos."; exit 1; } || echo "Rol de volcado de mínimo privilegio: todo OK"
