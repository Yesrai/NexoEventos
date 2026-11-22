#!/usr/bin/env bash
# Laboratorio local de failover. Uso: lab.sh {up|down|status}
# `down` solo elimina los contenedores y el volumen de ESTE laboratorio (proyecto nexo-failover-lab); no toca nada más.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
KEYFILE="../../work/failover-lab/key.env"   # work/ está en .gitignore
dc() { docker compose -p nexo-failover-lab -f compose.yml "$@"; }
load_key() {
  mkdir -p "$(dirname "$KEYFILE")"
  [ -f "$KEYFILE" ] || { printf 'TICKET_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32 | tr '+/' '-_')" > "$KEYFILE"; chmod 600 "$KEYFILE"; }
  set -a; . "$KEYFILE"; set +a
}
case "${1:-status}" in
  up)
    load_key
    dc up -d db
    dc --profile tools run --rm migrate
    dc up -d app-aws app-oci haproxy
    echo "Entrada HAProxy: http://127.0.0.1:18080 · stats: http://127.0.0.1:18404 · PostgreSQL lab: 127.0.0.1:55433"
    ;;
  down) load_key; dc down -v ;;
  status) load_key; dc ps ;;
  *) echo "Uso: $0 {up|down|status}" >&2; exit 2 ;;
esac
