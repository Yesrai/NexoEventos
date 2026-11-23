#!/usr/bin/env bash
# Suite completa del backend contra un PostgreSQL DESECHABLE (initdb nuevo en /tmp, socket Unix propio, sin red, sin tocar ningún clúster ni dato existente).
# Replica los pasos del CI: roles, base, `alembic upgrade head`, `pytest -q`. Se detiene y se borra al terminar (también con Ctrl-C). No usa la nube.
set -euo pipefail
export LC_ALL="${LC_ALL:-en_US.UTF-8}" LANG="${LANG:-en_US.UTF-8}"   # PostgreSQL 18 en macOS aborta con «postmaster became multithreaded» sin un locale válido
PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@18/bin}"; export PATH="$PGBIN:/opt/homebrew/bin:/usr/bin:/bin"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; PY="${PY:-$ROOT/backend/.venv/bin/python}"
BASE="$(mktemp -d /tmp/npgsuite.XXXXXX)"; PORT="$("$PY" -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')"
cleanup(){ pg_ctl -D "$BASE/data" -m immediate -w stop >/dev/null 2>&1 || true; rm -rf "$BASE"; echo "clúster desechable eliminado"; }; trap cleanup EXIT INT TERM
initdb -D "$BASE/data" -U postgres -A trust -N --no-locale -E UTF8 >/dev/null
pg_ctl -D "$BASE/data" -o "-p $PORT -k $BASE -c listen_addresses='' -c fsync=off -c max_connections=100" -w -l "$BASE/log" start >/dev/null
export PGHOST="$BASE" PGPORT="$PORT" PGUSER=postgres
psql -v ON_ERROR_STOP=1 -q postgres <<'SQL'
CREATE ROLE nexoeventos_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE nexoeventos_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE DATABASE nexoeventos_test OWNER nexoeventos_owner;
REVOKE ALL ON DATABASE nexoeventos_test FROM PUBLIC;
GRANT CONNECT ON DATABASE nexoeventos_test TO nexoeventos_app;
SQL
echo "PostgreSQL $(psql -Atq -c 'show server_version' postgres) desechable en socket privado (puerto $PORT)"
cd "$ROOT/backend"
MIGRATION_DATABASE_URL="postgresql+psycopg://postgres@/nexoeventos_test?host=$BASE&port=$PORT" "$PY" -m alembic upgrade head
"$PY" -m pytest -q "$@"
