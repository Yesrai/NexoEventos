#!/usr/bin/env bash
set -euo pipefail

NODE24_BIN="/opt/homebrew/opt/node@24/bin"
export PATH="$NODE24_BIN:$PATH"

echo "Node efectivo: $(node --version)"
test "$(node --version)" = "v24.21.0"

terraform fmt -check -recursive infra
for directory in infra/aws infra/azure infra/gcp; do
  terraform -chdir="$directory" validate
done

(
  cd backend
  MIGRATION_DATABASE_URL="postgresql+psycopg:///nexoeventos_test" .venv/bin/alembic upgrade head
  DATABASE_URL="postgresql+psycopg://nexoeventos_app@/nexoeventos_test" .venv/bin/python -m pytest
)

(
  cd frontend
  npm test
  npm run build
)
