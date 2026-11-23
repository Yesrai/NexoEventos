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

# Respaldo periódico cifrado y frescura (B-14/B-20): solo biblioteca estándar, openssl y un servidor HTTP falso en 127.0.0.1.
# No usa credenciales cloud, Internet ni datos persistentes (todo en directorios temporales).
backend/.venv/bin/python scripts/multicloud/test_backup_cycle.py
# Claves CMS protegidas con contraseña (S-01): claves desechables y psql/pg_restore falsos; no toca claves ni bases reales.
backend/.venv/bin/python scripts/multicloud/test_cms_key_passin.py
# Restauración real (local) del último respaldo para el orquestador de failover: cifrado/manifiestos reales, psql/pg_restore falsos.
backend/.venv/bin/python -m unittest discover -s scripts/multicloud/tests -p test_backup_source.py
# Lectura de OCI (servidor HTTP falso, firma de procedencia) integrada con el orquestador, y lease/compuerta sobre un almacén HTTP condicional falso.
backend/.venv/bin/python -m unittest discover -s scripts/multicloud/tests -p test_oci_source.py
backend/.venv/bin/python -m unittest discover -s scripts/multicloud/tests -p test_lease_http.py
# Failover local de extremo a extremo (orquestador + sondas, DNS con dns_switch.py, restauración desde un OCI falso, lease, standby con vallado de datos, registro de promoción).
backend/.venv/bin/python -m unittest discover -s scripts/multicloud/tests -p test_failover_e2e.py

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
