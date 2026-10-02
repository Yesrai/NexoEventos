#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MIGRATION_DATABASE_URL="${MIGRATION_DATABASE_URL:-postgresql+psycopg:///nexoeventos}"

cd "$PROJECT_ROOT/backend"
.venv/bin/alembic upgrade head
