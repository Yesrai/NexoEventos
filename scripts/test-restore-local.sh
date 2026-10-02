#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DB="${SOURCE_DB:-nexoeventos}"
RESTORE_DB="nexoeventos_restore_test"
DUMP_DIR="$PROJECT_ROOT/work/restore"
DUMP_FILE="$DUMP_DIR/nexoeventos.dump"

if [[ "$RESTORE_DB" != "nexoeventos_restore_test" ]]; then
  echo "Nombre de base aislada inesperado; restauración cancelada." >&2
  exit 1
fi

mkdir -p "$DUMP_DIR"

cleanup() {
  dropdb --if-exists "$RESTORE_DB" >/dev/null
  if [[ -f "$DUMP_FILE" ]]; then
    unlink "$DUMP_FILE"
  fi
}
trap cleanup EXIT

dropdb --if-exists "$RESTORE_DB" >/dev/null
pg_dump --format=custom --no-owner --no-acl --file="$DUMP_FILE" "$SOURCE_DB"
createdb "$RESTORE_DB"
pg_restore --exit-on-error --no-owner --no-acl --dbname="$RESTORE_DB" "$DUMP_FILE"

read -r source_events source_reservations source_tickets < <(
  psql -d "$SOURCE_DB" -AtF' ' -c \
    "SELECT (SELECT count(*) FROM events), (SELECT count(*) FROM reservations), (SELECT count(*) FROM tickets)"
)
read -r restored_events restored_reservations restored_tickets < <(
  psql -d "$RESTORE_DB" -AtF' ' -c \
    "SELECT (SELECT count(*) FROM events), (SELECT count(*) FROM reservations), (SELECT count(*) FROM tickets)"
)

test "$source_events" = "$restored_events"
test "$source_reservations" = "$restored_reservations"
test "$source_tickets" = "$restored_tickets"

if [[ "$restored_tickets" -gt 0 ]]; then
  set -a
  # El archivo local está ignorado por Git; no se imprime ninguna variable.
  source "$PROJECT_ROOT/backend/.env"
  set +a
  PYTHONPATH="$PROJECT_ROOT/backend" DATABASE_URL="postgresql+psycopg:///$RESTORE_DB" \
    "$PROJECT_ROOT/backend/.venv/bin/python" - <<'PY'
from sqlalchemy import create_engine, text

from app.ticket_tokens import reveal_ticket_secret, token_hash

engine = create_engine(__import__("os").environ["DATABASE_URL"])
with engine.connect() as connection:
    row = connection.execute(
        text("SELECT token_hash, token_ciphertext FROM tickets ORDER BY created_at LIMIT 1")
    ).one()
token = reveal_ticket_secret(row.token_ciphertext)
assert token_hash(token) == row.token_hash
PY
fi

echo "Restauración aislada verificada: eventos=$restored_events reservas=$restored_reservations entradas=$restored_tickets"
