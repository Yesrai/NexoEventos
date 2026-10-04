#!/usr/bin/env bash
# Funciones comunes para operar la V1 AWS de NexoEventos desde el Mac.
# Compatible con bash 3.2 (macOS). No imprime IDs de cuenta, endpoints ni secretos.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NEXO_ENV="${NEXO_ENV:-academy}"
NEXO_NAME_PREFIX="${NEXO_NAME_PREFIX:-nexoeventos-academy}"
NEXO_FQDN="${NEXO_FQDN:-nexoeventos-demo.duckdns.org}"
# Ruta del tfvars real (ignorado por Git). Puede vivir fuera del repositorio: NEXO_TFVARS=/ruta/academy.tfvars
TFVARS="${NEXO_TFVARS:-$PROJECT_ROOT/work/terraform-envs/$NEXO_ENV.tfvars}"
OPS_DIR="$PROJECT_ROOT/work/operacion"
OPS_LOG="$OPS_DIR/sesiones-cloud.log"

EC2_NAME_TAG="$NEXO_NAME_PREFIX-app"
RDS_ID="$NEXO_NAME_PREFIX-postgres"
DB_SG_NAME="$NEXO_NAME_PREFIX-db-sg"
DB_SUBNET_GROUP="$NEXO_NAME_PREFIX-db-subnets"

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

require_cmd() {
  local c
  for c in "$@"; do command -v "$c" >/dev/null 2>&1 || die "Falta el comando '$c'."; done
}

# Lee región y cuenta esperada del tfvars local ignorado por Git (no imprime el ID).
load_env_config() {
  [[ -f "$TFVARS" ]] || die "Falta el tfvars protegido del entorno; define NEXO_TFVARS con su ruta."
  EXPECTED_ACCOUNT="$(awk -F= '$1 ~ /^[[:space:]]*expected_account_id[[:space:]]*$/ {gsub(/[[:space:]\"]/, "", $2); print $2; exit}' "$TFVARS")"
  AWS_REGION="$(awk -F= '$1 ~ /^[[:space:]]*aws_region[[:space:]]*$/ {gsub(/[[:space:]\"]/, "", $2); print $2; exit}' "$TFVARS")"
  EXPECTED_PROJECT="$(awk -F= '$1 ~ /^[[:space:]]*project_slug[[:space:]]*$/ {gsub(/[[:space:]\"]/, "", $2); print $2; exit}' "$TFVARS")"
  EXPECTED_ENV="$(awk -F= '$1 ~ /^[[:space:]]*environment[[:space:]]*$/ {gsub(/[[:space:]\"]/, "", $2); print $2; exit}' "$TFVARS")"
  [[ "$EXPECTED_ACCOUNT" =~ ^[0-9]{12}$ && -n "$AWS_REGION" && -n "$EXPECTED_PROJECT" && -n "$EXPECTED_ENV" ]] \
    || die "El tfvars debe incluir expected_account_id, aws_region, project_slug y environment."
  [[ "$NEXO_ENV" == "$EXPECTED_ENV" ]] || die "NEXO_ENV no coincide con environment del tfvars."
  [[ "$NEXO_NAME_PREFIX" == "$EXPECTED_PROJECT-$EXPECTED_ENV" ]] \
    || die "El prefijo configurado no coincide con project_slug-environment del tfvars."
  export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"
}

verify_identity() {
  require_cmd aws
  load_env_config
  local active
  active="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" || die "STS no respondió; renueva la sesión del laboratorio."
  [[ "$active" == "$EXPECTED_ACCOUNT" ]] || die "Identidad AWS distinta de la esperada; operación cancelada."
  log "Identidad AWS verificada para '$NEXO_ENV' (ID oculto), región $AWS_REGION."
}

require_change_approval() {
  [[ "${NEXO_ALLOW_CLOUD_CHANGES:-}" == "YES" ]] || die "Acción con cambios externos bloqueada: exporta NEXO_ALLOW_CLOUD_CHANGES=YES solo con aprobación explícita."
}

record() {
  mkdir -p "$OPS_DIR"; chmod 700 "$OPS_DIR"
  umask 077
  printf '%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$NEXO_ENV" "$*" >>"$OPS_LOG"
}

# Enmascara valores que no deben aparecer en evidencias.
mask_ip() { awk -F. 'NF==4 {print $1"."$2".x.x"; next} {print "oculta"}' <<<"${1:-}"; }
mask_id() { local v="${1:-}"; [[ -z "$v" || "$v" == "None" ]] && { echo "-"; return; }; echo "${v%%-*}-…${v: -4}"; }

ec2_instance_id() {
  local ids count
  ids="$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$EC2_NAME_TAG" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text)"
  count="$(awk '{print NF}' <<<"$ids")"
  [[ "$count" == "1" ]] || die "Se esperaba exactamente una EC2 con Name=$EC2_NAME_TAG; se encontraron $count."
  printf '%s\n' "$ids"
}
ec2_state() { aws ec2 describe-instances --instance-ids "$1" --query 'Reservations[0].Instances[0].State.Name' --output text; }
ec2_public_ip() { aws ec2 describe-instances --instance-ids "$1" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text; }
rds_status() { aws rds describe-db-instances --db-instance-identifier "$1" --query 'DBInstances[0].DBInstanceStatus' --output text; }

wait_rds_status() {
  local id="$1" want="$2" max="${3:-2400}" waited=0 st
  while :; do
    st="$(rds_status "$id")"
    [[ "$st" == "$want" ]] && { log "RDS $id: $st"; return 0; }
    if (( waited >= max )); then log "ERROR: RDS $id no llegó a '$want' en ${max}s (estado: $st)."; return 1; fi
    sleep 30; waited=$((waited + 30))
    log "RDS $id: $st (esperando '$want', ${waited}s)"
  done
}

wait_ec2_state() {
  local id="$1" want="$2" max="${3:-900}" waited=0 st
  while :; do
    st="$(ec2_state "$id")"
    [[ "$st" == "$want" ]] && { log "EC2: $st"; return 0; }
    if (( waited >= max )); then log "ERROR: EC2 no llegó a '$want' en ${max}s (estado: $st)."; return 1; fi
    sleep 15; waited=$((waited + 15))
    log "EC2: $st (esperando '$want', ${waited}s)"
  done
}

private_bucket() {
  local bucket="$NEXO_NAME_PREFIX-$EXPECTED_ACCOUNT-$AWS_REGION"
  aws s3api head-bucket --bucket "$bucket" >/dev/null 2>&1 || return 1
  printf '%s\n' "$bucket"
}

utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
# Diferencia en segundos entre dos marcas ISO-8601 (BSD/GNU date difieren; se usa Python).
seconds_between() { python3 - "$1" "$2" <<'PY'
import sys
from datetime import datetime
f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
print(int((f(sys.argv[2]) - f(sys.argv[1])).total_seconds()))
PY
}
