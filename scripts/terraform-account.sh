#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-}"
ENVIRONMENT="${2:-}"

usage() {
  echo "Uso: $0 {fmt|validate|plan|apply} <entorno>" >&2
  echo "Plan/apply requieren work/terraform-envs/<entorno>.tfvars." >&2
}

if [[ ! "$ACTION" =~ ^(fmt|validate|plan|apply)$ ]] || [[ ! "$ENVIRONMENT" =~ ^[a-z][a-z0-9-]{1,30}$ ]]; then
  usage
  exit 2
fi

TFVARS="$PROJECT_ROOT/work/terraform-envs/$ENVIRONMENT.tfvars"
TF_DIR="$PROJECT_ROOT/infra/aws"
DATA_DIR="$PROJECT_ROOT/work/terraform/$ENVIRONMENT"
# El estado real migrado usa el sufijo -current. Puede sobreescribirse solo de
# forma explícita para otra cuenta; nunca se crea silenciosamente un estado
# paralelo con el nombre corto del entorno.
STATE_NAME="${NEXO_TF_STATE_NAME:-$ENVIRONMENT-current}"
[[ "$STATE_NAME" =~ ^[a-z][a-z0-9-]{1,40}$ ]] || { echo "NEXO_TF_STATE_NAME inválido." >&2; exit 2; }
STATE_FILE="$PROJECT_ROOT/work/terraform-state/$STATE_NAME/terraform.tfstate"
PLAN_FILE="$PROJECT_ROOT/work/terraform-plans/$ENVIRONMENT.tfplan"
PLAN_TMP="$PROJECT_ROOT/work/terraform-plans/.$ENVIRONMENT.tfplan.tmp"
cleanup() { rm -f -- "$PLAN_TMP"; }
trap cleanup EXIT

if [[ "$ACTION" == "fmt" ]]; then
  terraform -chdir="$TF_DIR" fmt -check -recursive
  exit 0
fi

mkdir -p "$DATA_DIR" "$(dirname "$STATE_FILE")" "$(dirname "$PLAN_FILE")"
if [[ ! -f "$STATE_FILE" ]]; then
  echo "No existe el estado protegido esperado: $STATE_FILE" >&2
  echo "Se cancela para no inicializar un estado vacío ni duplicar recursos." >&2
  exit 1
fi
export TF_DATA_DIR="$DATA_DIR"
terraform -chdir="$TF_DIR" init -input=false -reconfigure -backend-config="path=$STATE_FILE" >/dev/null

if [[ "$ACTION" == "validate" ]]; then
  terraform -chdir="$TF_DIR" validate
  exit 0
fi

if [[ ! -f "$TFVARS" ]]; then
  echo "Falta el archivo local protegido: $TFVARS" >&2
  exit 1
fi
EXPECTED_ACCOUNT="$(awk -F= '$1 ~ /^[[:space:]]*expected_account_id[[:space:]]*$/ {gsub(/[[:space:]\"]/, "", $2); print $2; exit}' "$TFVARS")"
REGION="$(awk -F= '$1 ~ /^[[:space:]]*aws_region[[:space:]]*$/ {gsub(/[[:space:]\"]/, "", $2); print $2; exit}' "$TFVARS")"
if [[ ! "$EXPECTED_ACCOUNT" =~ ^[0-9]{12}$ ]] || [[ -z "$REGION" ]]; then
  echo "El tfvars local debe incluir expected_account_id válido y aws_region." >&2
  exit 1
fi

ACTIVE_ACCOUNT="$(aws sts get-caller-identity --query Account --output text --region "$REGION")"
if [[ "$ACTIVE_ACCOUNT" != "$EXPECTED_ACCOUNT" ]]; then
  echo "Identidad AWS distinta de la esperada; no se ejecutó Terraform." >&2
  exit 1
fi
echo "Identidad AWS verificada para el entorno '$ENVIRONMENT' (ID oculto)."

case "$ACTION" in
  plan)
    umask 077
    if [[ -f "$PLAN_FILE" ]]; then
      ARCHIVE_DIR="$PROJECT_ROOT/work/terraform-plans/archive"
      mkdir -p "$ARCHIVE_DIR"
      mv "$PLAN_FILE" "$ARCHIVE_DIR/$ENVIRONMENT-$(date -u +%Y%m%dT%H%M%SZ).tfplan"
      echo "El plan anterior quedó archivado y ya no puede aplicarse como vigente."
    fi
    terraform -chdir="$TF_DIR" plan -input=false -var-file="$TFVARS" -out="$PLAN_TMP"
    mv -f "$PLAN_TMP" "$PLAN_FILE"
    echo "Plan protegido guardado fuera de Git: $PLAN_FILE"
    ;;
  apply)
    if [[ "${NEXO_ALLOW_APPLY:-}" != "YES" ]]; then
      echo "Apply bloqueado: requiere aprobación explícita y NEXO_ALLOW_APPLY=YES." >&2
      exit 1
    fi
    if [[ ! -f "$PLAN_FILE" ]]; then
      echo "No existe el plan revisado del entorno; apply cancelado." >&2
      exit 1
    fi
    terraform -chdir="$TF_DIR" apply -input=false "$PLAN_FILE"
    ;;
esac
