#!/usr/bin/env bash
# Laboratorio local de replicación. Uso: lab.sh {up|status|down}
# `down` elimina SOLO el proyecto nexo-repl-lab (contenedores, red y volúmenes de este laboratorio). Las evidencias están en docs/ y work/, fuera de Docker.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
KEYFILE="../../work/repl-lab/key.env"
load_key() {
  mkdir -p "$(dirname "$KEYFILE")"
  [ -f "$KEYFILE" ] || { printf 'TICKET_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32 | tr '+/' '-_')" > "$KEYFILE"; chmod 600 "$KEYFILE"; }
  set -a; . "$KEYFILE"; set +a
}
case "${1:-status}" in
  up) load_key; docker build -q --pull=false --network=none -f Dockerfile.current -t nexo-repl-lab-backend:current ../../backend >/dev/null; python3 build_compose.py; python3 labctl.py setup ;;
  status) load_key; python3 labctl.py status ;;
  down) load_key; docker compose -p nexo-repl-lab -f compose.yml --profile tools --profile fault --profile stale down -v --remove-orphans ;;
  *) echo "Uso: $0 {up|status|down}" >&2; exit 2 ;;
esac
