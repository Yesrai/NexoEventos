#!/usr/bin/env bash
# Auditoría visual en Chrome real sobre una base AISLADA (nexoeventos_journey); no toca la base de desarrollo.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/opt/node@24/bin:$PATH"
DB=nexoeventos_journey
API_PORT=8013
WEB_PORT=5185
WORK="$(mktemp -d)"
free_ports() { for port in $API_PORT $WEB_PORT; do lsof -ti tcp:$port -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true; done; }
trap 'free_ports; rm -rf "$WORK"' EXIT
free_ports; sleep 1
PY="$ROOT/backend/.venv/bin/python"

psql postgres -q -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" -c "CREATE DATABASE $DB OWNER nexoeventos_owner" -c "GRANT CONNECT ON DATABASE $DB TO nexoeventos_app"
(cd "$ROOT/backend" && MIGRATION_DATABASE_URL="postgresql+psycopg:///$DB" .venv/bin/alembic upgrade head >/dev/null 2>&1)
"$PY" "$ROOT/scripts/seed-demo-catalog.py" --database-url "postgresql+psycopg:///$DB" >/dev/null

# HIDDEN_EVENT=1: añade un evento ficticio OCULTO (publicado, is_demo=false) copiando la estructura del 1028 y lo abre por enlace directo.
if [[ "${HIDDEN_EVENT:-0}" == 1 ]]; then
  psql "$DB" -q -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO events (id, name, event_date, event_time, venue, city, category, description, price, capacity, reserved_count, image_path, ticket_mode, is_demo, status, venue_id, layout_id)
SELECT 90101, '[ENSAYO] Evento oculto', event_date, event_time, venue, city, category, 'Evento ficticio de ensayo.', price, capacity, 0, image_path, ticket_mode, false, 'published', venue_id, layout_id FROM events WHERE id = 1028;
INSERT INTO event_zones (event_id, name, price, capacity, reserved_count) SELECT 90101, name, price, capacity, 0 FROM event_zones WHERE event_id = 1028;
INSERT INTO event_seats (event_id, zone_id, row_label, seat_number)
SELECT 90101, nz.id, s.row_label, s.seat_number FROM event_seats s JOIN event_zones oz ON oz.id = s.zone_id JOIN event_zones nz ON nz.event_id = 90101 AND nz.name = oz.name WHERE s.event_id = 1028;
SQL
  export E2E_EVENT_ID=90101 E2E_EVENT_NAME='[ENSAYO] Evento oculto'
fi

export E2E_ORGANIZER_PASSWORD="$(openssl rand -base64 24)" E2E_OPERATOR_PASSWORD="$(openssl rand -base64 24)" E2E_CLIENT_PASSWORD="$(openssl rand -base64 24)"
export E2E_DB="$DB" PYTHONPATH="$ROOT/backend"
"$PY" - <<'PY'
import os
from sqlalchemy import create_engine, text
from app.auth import hash_password
engine = create_engine(f"postgresql+psycopg:///{os.environ['E2E_DB']}")
with engine.begin() as connection:
    for email, name, role, secret in (("e2e-organizador@example.com", "Organizadora E2E", "organizer", "E2E_ORGANIZER_PASSWORD"), ("e2e-operador@example.com", "Operador E2E", "operator", "E2E_OPERATOR_PASSWORD")):
        connection.execute(text("INSERT INTO users (id, email, display_name, password_hash, role) VALUES (gen_random_uuid(), :e, :n, :h, :r)"), {"e": email, "n": name, "h": hash_password(os.environ[secret]), "r": role})
PY

KEY="$("$PY" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
(cd "$ROOT/backend" && DATABASE_URL="postgresql+psycopg://nexoeventos_app@/$DB" TICKET_ENCRYPTION_KEY="$KEY" FRONTEND_ORIGINS="http://127.0.0.1:$WEB_PORT" .venv/bin/uvicorn app.main:app --port $API_PORT >"$WORK/api.log" 2>&1) &
API_PID=$!
# Compilación aislada: el recorrido no depende de ediciones del código mientras corre.
(cd "$ROOT/frontend" && VITE_API_URL="http://127.0.0.1:$API_PORT" npx vite build --outDir "$WORK/dist" --emptyOutDir >"$WORK/build.log" 2>&1)
(cd "$ROOT/frontend" && npx vite preview --outDir "$WORK/dist" --host 127.0.0.1 --port $WEB_PORT --strictPort >"$WORK/web.log" 2>&1) &
WEB_PID=$!
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null && curl -sf "http://127.0.0.1:$WEB_PORT/" >/dev/null && break; sleep 0.5; done

E2E_BASE="http://127.0.0.1:$WEB_PORT" E2E_API="http://127.0.0.1:$API_PORT" node "$ROOT/scripts/journey-buyer.mjs" "${1:-$ROOT/docs/evidencias/ui/recorrido-comprador}"
