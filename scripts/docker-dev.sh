#!/usr/bin/env bash
# Entorno Docker local: backend FastAPI + PostgreSQL 18 aislado. No usa AWS ni credenciales reales.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

case "${1:-up}" in
  up)
    if [ ! -f .env ]; then
      # Clave Fernet local (32 bytes en base64 URL-safe); .env está en .gitignore.
      printf 'TICKET_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32 | tr '+/' '-_')" > .env
      chmod 600 .env
      echo "Se creó .env con una clave local de desarrollo (no se sube a Git)."
    fi
    docker compose up -d --build db
    docker compose --profile tools run --rm --build migrate
    docker compose up -d --build backend
    echo "Backend: http://127.0.0.1:8001/health  ·  PostgreSQL local: 127.0.0.1:55432"
    ;;
  down) shift; docker compose down "$@" ;;
  logs) shift; docker compose logs "$@" ;;
  *) echo "Uso: $0 {up|down [-v]|logs}" >&2; exit 2 ;;
esac
