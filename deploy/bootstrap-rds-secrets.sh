#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Ejecuta como root en la instancia de aplicación." >&2
  exit 1
fi
if [[ $# -ne 3 ]]; then
  echo "Uso: $0 <identificador-rds> <region> <dominio-duckdns-completo>" >&2
  exit 2
fi

DB_IDENTIFIER="$1"
AWS_REGION="$2"
DOMAIN="$3"
PROJECT_ROOT="/opt/nexoeventos"

if [[ "$DOMAIN" =~ ^[a-z0-9-]+\.duckdns\.org$ ]]; then
  USES_DUCKDNS=YES
elif [[ "$DOMAIN" =~ ^nexoeventos-recovery-[0-9-]+\.sslip\.io$ ]]; then
  USES_DUCKDNS=NO
else
  USES_DUCKDNS=INVALID
fi
if [[ ! "$DB_IDENTIFIER" =~ ^[a-z][a-z0-9-]{0,62}$ ]] || \
   [[ ! "$AWS_REGION" =~ ^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$ ]] || \
   [[ "$USES_DUCKDNS" == INVALID ]]; then
  echo "Identificador, región o dominio inválido." >&2
  exit 1
fi

umask 077
install -d -o root -g root -m 0700 /etc/nexoeventos
secret_json="$(mktemp /run/nexoeventos-rds-secret.XXXXXX)"
cleanup() {
  unset MASTER_PASSWORD APP_PASSWORD MIGRATION_PASSWORD TICKET_KEY HASH_KEY DUCKDNS_TOKEN
  unset DATABASE_URL MIGRATION_DATABASE_URL FRONTEND_ORIGINS DUCKDNS_DOMAIN
  unset TICKET_ENCRYPTION_KEY SECURITY_HASH_KEY
  rm -f -- "$secret_json"
}
trap cleanup EXIT

DB_INFO="$(aws rds describe-db-instances --region "$AWS_REGION" \
  --db-instance-identifier "$DB_IDENTIFIER" \
  --query 'DBInstances[0].[Endpoint.Address,MasterUsername,MasterUserSecret.SecretArn]' \
  --output text)"
read -r DB_ENDPOINT MASTER_USER MASTER_SECRET_ARN <<<"$DB_INFO"
if [[ -z "$DB_ENDPOINT" || "$DB_ENDPOINT" == "None" ]]; then
  echo "No se pudo obtener el endpoint de RDS." >&2
  exit 1
fi

if [[ -n "$MASTER_SECRET_ARN" && "$MASTER_SECRET_ARN" != "None" ]] && \
   aws secretsmanager get-secret-value --region "$AWS_REGION" --secret-id "$MASTER_SECRET_ARN" \
     --query SecretString --output text >"$secret_json" 2>/dev/null; then
  MASTER_USER="$(jq -er .username "$secret_json")"
  MASTER_PASSWORD="$(jq -er .password "$secret_json")"
  echo "Acceso de lectura al secreto maestro administrado por RDS: comprobado."
else
  echo "No se pudo leer el secreto maestro con el rol actual. No se ampliaron permisos."
  read -rp "Usuario administrador RDS (entrada manual autorizada): " MASTER_USER
  read -rsp "Contraseña administrador RDS (no se mostrará): " MASTER_PASSWORD
  echo
fi

protected_files=(
  /etc/nexoeventos/backend.env
  /etc/nexoeventos/migration.env
)
if [[ "$USES_DUCKDNS" == YES ]]; then
  protected_files+=(/etc/nexoeventos/duckdns.env)
fi
existing_files=0
for protected_file in "${protected_files[@]}"; do
  [[ -f "$protected_file" ]] && ((existing_files += 1))
done

if [[ "$existing_files" -gt 0 && "$existing_files" -lt "${#protected_files[@]}" ]]; then
  echo "Hay un conjunto incompleto de archivos protegidos; se rechaza mezclar secretos." >&2
  exit 1
elif [[ "$existing_files" -eq "${#protected_files[@]}" ]]; then
  for protected_file in "${protected_files[@]}"; do
    if [[ "$(stat -c '%U:%G:%a' "$protected_file")" != "root:root:600" ]]; then
      echo "Permisos o propietario inesperados en $protected_file." >&2
      exit 1
    fi
  done
  set -a
  # Estos archivos fueron creados por este script, pertenecen a root y no son
  # escribibles por otros usuarios.
  source /etc/nexoeventos/backend.env
  source /etc/nexoeventos/migration.env
  if [[ "$USES_DUCKDNS" == YES ]]; then
    source /etc/nexoeventos/duckdns.env
  fi
  set +a
  APP_PASSWORD="$(printf %s "$DATABASE_URL" | python3.11 -c \
    'import sys, urllib.parse; print(urllib.parse.unquote(urllib.parse.urlsplit(sys.stdin.read()).password or ""), end="")')"
  MIGRATION_PASSWORD="$(printf %s "$MIGRATION_DATABASE_URL" | python3.11 -c \
    'import sys, urllib.parse; print(urllib.parse.unquote(urllib.parse.urlsplit(sys.stdin.read()).password or ""), end="")')"
  TICKET_KEY="${TICKET_ENCRYPTION_KEY:-}"
  HASH_KEY="${SECURITY_HASH_KEY:-}"
  DUCKDNS_TOKEN="${DUCKDNS_TOKEN:-}"
  if [[ "${FRONTEND_ORIGINS:-}" != "https://${DOMAIN}" ]] || \
     { [[ "$USES_DUCKDNS" == YES ]] && [[ "${DUCKDNS_DOMAIN:-}" != "${DOMAIN%.duckdns.org}" ]]; }; then
    echo "Los archivos existentes pertenecen a otro dominio; no se reutilizaron." >&2
    exit 1
  fi
  echo "Se reutilizarán los secretos protegidos existentes; no se regeneraron."
elif [[ "${NEXO_GENERATE_APPLICATION_SECRETS:-NO}" == "YES" ]]; then
  mapfile -t GENERATED_SECRETS < <(
    "$PROJECT_ROOT/backend/.venv/bin/python" - <<'PY'
import secrets
from cryptography.fernet import Fernet

print(secrets.token_urlsafe(32))
print(secrets.token_urlsafe(32))
print(Fernet.generate_key().decode("ascii"))
print(secrets.token_urlsafe(48))
PY
  )
  MIGRATION_PASSWORD="${GENERATED_SECRETS[0]}"
  APP_PASSWORD="${GENERATED_SECRETS[1]}"
  TICKET_KEY="${GENERATED_SECRETS[2]}"
  HASH_KEY="${GENERATED_SECRETS[3]}"
  unset GENERATED_SECRETS
  echo "Contraseñas de base y claves de aplicación generadas localmente en la EC2."
else
  read -rsp "Contraseña nueva de migración (mínimo 20 caracteres): " MIGRATION_PASSWORD
  echo
  read -rsp "Contraseña nueva de aplicación (mínimo 20 caracteres y distinta): " APP_PASSWORD
  echo
  read -rsp "TICKET_ENCRYPTION_KEY respaldada por separado: " TICKET_KEY
  echo
  read -rsp "SECURITY_HASH_KEY independiente: " HASH_KEY
  echo
fi
if [[ "$existing_files" -eq 0 && "$USES_DUCKDNS" == YES ]]; then
  read -rsp "Token DuckDNS (no se mostrará): " DUCKDNS_TOKEN
  echo
fi

if [[ ${#MIGRATION_PASSWORD} -lt 20 || ${#APP_PASSWORD} -lt 20 || \
      "$MIGRATION_PASSWORD" == "$APP_PASSWORD" || ! "$HASH_KEY" =~ ^[A-Za-z0-9_-]{43,}$ ]] || \
   { [[ "$USES_DUCKDNS" == YES ]] && [[ ${#DUCKDNS_TOKEN} -lt 20 ]]; }; then
  echo "Algún secreto no satisface la longitud/separación requerida." >&2
  exit 1
fi
printf '%s' "$TICKET_KEY" | "$PROJECT_ROOT/backend/.venv/bin/python" -c \
  'import sys; from cryptography.fernet import Fernet; Fernet(sys.stdin.read().encode("ascii"))'

urlencode() {
  python3.11 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=""), end="")'
}
MASTER_USER_ESC="$(printf %s "$MASTER_USER" | urlencode)"
MASTER_PASSWORD_ESC="$(printf %s "$MASTER_PASSWORD" | urlencode)"
MIGRATION_PASSWORD_ESC="$(printf %s "$MIGRATION_PASSWORD" | urlencode)"
APP_PASSWORD_ESC="$(printf %s "$APP_PASSWORD" | urlencode)"

ADMIN_URL="postgresql+psycopg://${MASTER_USER_ESC}:${MASTER_PASSWORD_ESC}@${DB_ENDPOINT}/nexoeventos?sslmode=require"
MIGRATION_DATABASE_URL="$ADMIN_URL" \
NEXO_MIGRATION_DATABASE_PASSWORD="$MIGRATION_PASSWORD" \
NEXO_APP_DATABASE_PASSWORD="$APP_PASSWORD" \
  "$PROJECT_ROOT/backend/.venv/bin/python" "$PROJECT_ROOT/scripts/provision-database-roles.py"

backend_tmp="$(mktemp /etc/nexoeventos/backend.env.XXXXXX)"
migration_tmp="$(mktemp /etc/nexoeventos/migration.env.XXXXXX)"
duckdns_tmp=""
cat >"$backend_tmp" <<EOF
APP_ENV=production
DATABASE_URL=postgresql+psycopg://nexoeventos_app:${APP_PASSWORD_ESC}@${DB_ENDPOINT}/nexoeventos?sslmode=require
FRONTEND_ORIGINS=https://${DOMAIN}
SESSION_COOKIE_SECURE=true
SESSION_HOURS=8
LOGIN_MAX_FAILURES=5
LOGIN_WINDOW_MINUTES=15
LOGIN_BLOCK_MINUTES=15
TICKET_ENCRYPTION_KEY=${TICKET_KEY}
SECURITY_HASH_KEY=${HASH_KEY}
EOF
cat >"$migration_tmp" <<EOF
MIGRATION_DATABASE_URL=postgresql+psycopg://nexoeventos_migrator:${MIGRATION_PASSWORD_ESC}@${DB_ENDPOINT}/nexoeventos?sslmode=require
EOF
if [[ "$USES_DUCKDNS" == YES ]]; then
  duckdns_tmp="$(mktemp /etc/nexoeventos/duckdns.env.XXXXXX)"
  cat >"$duckdns_tmp" <<EOF
DUCKDNS_DOMAIN=${DOMAIN%.duckdns.org}
DUCKDNS_TOKEN=${DUCKDNS_TOKEN}
EOF
fi
chown root:root "$backend_tmp" "$migration_tmp"
chmod 0600 "$backend_tmp" "$migration_tmp"
mv -f "$backend_tmp" /etc/nexoeventos/backend.env
mv -f "$migration_tmp" /etc/nexoeventos/migration.env
if [[ "$USES_DUCKDNS" == YES ]]; then
  chown root:root "$duckdns_tmp"
  chmod 0600 "$duckdns_tmp"
  mv -f "$duckdns_tmp" /etc/nexoeventos/duckdns.env
fi

unset MASTER_PASSWORD ADMIN_URL MASTER_USER_ESC MASTER_PASSWORD_ESC APP_PASSWORD MIGRATION_PASSWORD TICKET_KEY HASH_KEY DUCKDNS_TOKEN
echo "Archivos protegidos instalados. La identidad maestra no se guardó."
echo "Antes de iniciar: respalda la clave QR por un canal separado y ejecuta Alembic con migration.env."
