#!/usr/bin/env bash
# Ensayo LOCAL y desechable de la actualización 0005 -> 0008 (nada de AWS ni de datos reales).
#   - PostgreSQL efímero en 127.0.0.1:55433 (contenedor nexo-rehearsal) con los mismos roles que producción;
#   - código antiguo (OLD_REV, por defecto el desplegado en cloud) en un worktree temporal;
#   - comprueba: upgrade con reservas existentes, código antiguo sobre esquema nuevo, 2 workers (sesiones, fila, disputa de asiento),
#     rollback puro y rollback con tráfico posterior, y reintento del upgrade.
# Uso: scripts/rehearsal/run.sh [OLD_REV]       Limpieza automática al terminar (éxito o fallo).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
ROOT="$PWD"; OLD_REV="${1:-7955e7e}"; PY="$ROOT/backend/.venv/bin/python"; ALEMBIC="$ROOT/backend/.venv/bin/alembic"
WORK="$(mktemp -d)"; C=nexo-rehearsal; ADMIN="postgresql+psycopg://postgres:rehearsal-only@127.0.0.1:55433"
export PATH=/usr/bin:/opt/homebrew/bin:$PATH
cleanup() { pkill -f "uvicorn app.main:app --host 127.0.0.1 --port 810[12]" 2>/dev/null || true; docker rm -f "$C" >/dev/null 2>&1 || true
  git worktree remove --force "$WORK/old" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT
step() { printf '\n== %s\n' "$*"; }
psqlc() { docker exec "$C" psql -U postgres -d "${2:-nexoeventos}" -Atc "$1"; }
app() { # app <dir_backend> <puerto> <workers>
  (cd "$1" && DATABASE_URL=postgresql+psycopg://nexoeventos_app:rehearsal-app@127.0.0.1:55433/nexoeventos TICKET_ENCRYPTION_KEY="$KEY" \
    SECURITY_HASH_KEY=rehearsal-hash-key-0123456789abcdef FRONTEND_ORIGINS=http://localhost:5173 APP_ENV=development \
    nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$2" --workers "$3" >"$WORK/app-$2.log" 2>&1 &)
  for _ in $(seq 40); do curl -sf "http://127.0.0.1:$2/ready" >/dev/null && return; sleep 0.5; done; echo "la API no arrancó"; tail -5 "$WORK/app-$2.log"; exit 1; }
stop_apps() { pkill -f "uvicorn app.main:app --host 127.0.0.1 --port 810[12]" || true; sleep 1; }
KEY="$("$PY" -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"

step "Base desechable y código antiguo ($OLD_REV)"
docker rm -f "$C" >/dev/null 2>&1 || true
docker run -d --rm --name "$C" -e POSTGRES_PASSWORD=rehearsal-only -p 127.0.0.1:55433:5432 postgres:18@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336 >/dev/null
for _ in $(seq 60); do docker logs "$C" 2>&1 | grep -q "PostgreSQL init process complete" && docker exec "$C" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
docker exec -i "$C" psql -U postgres -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE ROLE nexoeventos_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE nexoeventos_app LOGIN PASSWORD 'rehearsal-app' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE DATABASE nexoeventos OWNER nexoeventos_owner;
REVOKE ALL ON DATABASE nexoeventos FROM PUBLIC;
GRANT CONNECT ON DATABASE nexoeventos TO nexoeventos_app;
SQL
git worktree add --detach "$WORK/old" "$OLD_REV" >/dev/null 2>&1
export MIGRATION_DATABASE_URL="$ADMIN/nexoeventos"
(cd "$WORK/old/backend" && "$ALEMBIC" upgrade head >/dev/null 2>&1 && psqlc "select 'esquema antiguo en '||version_num from alembic_version")
(cd "$WORK/old/scripts" && "$PY" seed-demo-catalog.py --database-url "$MIGRATION_DATABASE_URL" | tail -1)
app "$WORK/old/backend" 8101 1; "$PY" scripts/rehearsal/phase.py seed http://127.0.0.1:8101 "$WORK/state.json"; stop_apps
docker exec "$C" pg_dump -U postgres -Fc nexoeventos >"$WORK/pre.dump"
docker exec "$C" createdb -U postgres -O nexoeventos_owner pre; docker exec -i "$C" pg_restore -U postgres -d pre <"$WORK/pre.dump" 2>/dev/null || true
REHEARSAL_DB=pre scripts/rehearsal/fingerprint.sh >"$WORK/fp0005"

step "Upgrade 0005 -> 0008 con código nuevo; las reservas existentes no cambian"
(cd backend && "$ALEMBIC" upgrade head 2>&1 | grep -c "Running upgrade" | sed 's/^/migraciones aplicadas: /')
(cd scripts && "$PY" seed-demo-catalog.py --database-url "$MIGRATION_DATABASE_URL" | tail -1)
scripts/rehearsal/fingerprint.sh >"$WORK/fp0008"
diff <(grep -vE '^(alembic|event_seats)' "$WORK/fp0005") <(grep -vE '^(alembic|event_seats)' "$WORK/fp0008") && echo "reservas, entradas, usuarios e inventario con ventas: huella idéntica"

step "Compatibilidad: código ANTIGUO sobre esquema 0008"
app "$WORK/old/backend" 8101 1; "$PY" scripts/rehearsal/phase.py verify http://127.0.0.1:8101 "$WORK/state.json"; stop_apps

step "Código NUEVO con 2 workers: sesiones, fila virtual y disputa de asiento"
app "$ROOT/backend" 8102 2; "$PY" scripts/rehearsal/phase.py verify http://127.0.0.1:8102 "$WORK/state.json"
echo "procesos worker: $(pgrep -f 'multiprocessing.spawn' | wc -l | tr -d ' ')"
"$PY" scripts/rehearsal/workers.py http://127.0.0.1:8102 1028; stop_apps

step "Rollback A (puro): respaldo -> upgrade -> downgrade 0005"
docker exec "$C" createdb -U postgres -O nexoeventos_owner rb; docker exec -i "$C" pg_restore -U postgres -d rb <"$WORK/pre.dump" 2>/dev/null || true
(cd backend && MIGRATION_DATABASE_URL="$ADMIN/rb" "$ALEMBIC" upgrade head >/dev/null 2>&1 && echo "rb en $(psqlc 'select version_num from alembic_version' rb)"
  MIGRATION_DATABASE_URL="$ADMIN/rb" "$ALEMBIC" downgrade 0005 >/dev/null 2>&1 && echo "rb en $(psqlc 'select version_num from alembic_version' rb)")
REHEARSAL_DB=rb scripts/rehearsal/fingerprint.sh | diff "$WORK/fp0005" - && echo "huella idéntica a la de antes de migrar"

step "Rollback B (con reservas y fila posteriores): downgrade 0005 y código antiguo"
before="$(psqlc 'select count(*) from reservations')|$(psqlc 'select count(*) from tickets')|$(psqlc 'select count(*) from users')"
(cd backend && "$ALEMBIC" downgrade 0005 2>&1 | grep -c "Running downgrade" | sed 's/^/downgrades aplicados: /')
after="$(psqlc 'select count(*) from reservations')|$(psqlc 'select count(*) from tickets')|$(psqlc 'select count(*) from users')"
[[ "$before" == "$after" ]] && echo "reservas|entradas|usuarios sin pérdida: $after"
app "$WORK/old/backend" 8101 1; "$PY" scripts/rehearsal/phase.py verify http://127.0.0.1:8101 "$WORK/state.json"; stop_apps

step "Reintento del upgrade tras el rollback"
(cd backend && "$ALEMBIC" upgrade head 2>&1 | grep -c "Running upgrade" | sed 's/^/migraciones reaplicadas: /')
echo; echo "ENSAYO COMPLETO: todos los pasos pasaron"
