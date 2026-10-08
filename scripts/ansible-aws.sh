#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-}"
PROFILE="${NEXO_AWS_PROFILE:-nexoeventos-lab}"
TFVARS="$ROOT/work/terraform-envs/academy.tfvars"
RUNTIME="$ROOT/work/ansible/runtime.yml"
INVENTORY="$ROOT/work/ansible/inventory.yml"
export ANSIBLE_CONFIG="$ROOT/ansible/ansible.cfg"

case "$ACTION" in preflight|deploy|rollback) ;; *)
  echo "Uso: $0 {preflight|deploy|rollback}" >&2; exit 2 ;;
esac
for command_name in aws ansible-playbook session-manager-plugin; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Falta el requisito local: $command_name" >&2; exit 1;
  }
done
GIT_BIN=""
for git_candidate in "$(command -v git 2>/dev/null || true)" /usr/bin/git; do
  if [[ -x "$git_candidate" ]] && "$git_candidate" --version >/dev/null 2>&1; then
    GIT_BIN="$git_candidate"
    break
  fi
done
[[ -n "$GIT_BIN" ]] || { echo "No se encontró un Git ejecutable." >&2; exit 1; }
[[ -f "$TFVARS" ]] || { echo "Falta academy.tfvars protegido." >&2; exit 1; }

EXPECTED_ACCOUNT="$(awk -F= '$1 ~ /^[[:space:]]*expected_account_id[[:space:]]*$/ {gsub(/[[:space:]\"]/, "", $2); print $2; exit}' "$TFVARS")"
REGION="$(awk -F= '$1 ~ /^[[:space:]]*aws_region[[:space:]]*$/ {gsub(/[[:space:]\"]/, "", $2); print $2; exit}' "$TFVARS")"
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN AWS_DEFAULT_PROFILE
export AWS_PROFILE="$PROFILE" AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
ACTIVE_ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" || {
  echo "STS no respondió; renueva una sola vez el bloque completo del Learner Lab." >&2; exit 1;
}
[[ "$ACTIVE_ACCOUNT" == "$EXPECTED_ACCOUNT" ]] || {
  echo "La cuenta activa no coincide con el entorno; no se ejecutó Ansible." >&2; exit 1;
}

INSTANCE_ID="$(aws ec2 describe-instances \
  --filters Name=tag:Name,Values=nexoeventos-academy-app Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].InstanceId' --output text)"
[[ "$(awk '{print NF}' <<<"$INSTANCE_ID")" == 1 ]] || {
  echo "Se requiere exactamente una EC2 NexoEventos en ejecución." >&2; exit 1;
}
PING="$(aws ssm describe-instance-information \
  --filters Key=InstanceIds,Values="$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text)"
[[ "$PING" == Online ]] || { echo "La EC2 no aparece Online en Session Manager." >&2; exit 1; }
BUCKET="nexoeventos-academy-${EXPECTED_ACCOUNT}-${REGION}"
aws s3api head-bucket --bucket "$BUCKET" >/dev/null

mkdir -p "$(dirname "$RUNTIME")"
umask 077
RELEASE_ID="$($GIT_BIN -C "$ROOT" rev-parse HEAD)"
ARTIFACT="$ROOT/work/releases/nexoeventos-${RELEASE_ID}.tar.gz"
{
  printf '%s\n' '---'
  printf 'aws_profile: %s\n' "$PROFILE"
  printf 'ssm_bucket_name: %s\n' "$BUCKET"
  printf 'release_id: %s\n' "$RELEASE_ID"
  printf 'release_artifact: %s\n' "$ARTIFACT"
} >"$RUNTIME"
chmod 600 "$RUNTIME"
{
  printf '%s\n' '---' 'all:' '  children:' '    nexoeventos_app:' '      hosts:' '        nexoeventos-academy-app:'
  printf '          ansible_host: %s\n' "$INSTANCE_ID"
  printf '          ansible_aws_ssm_instance_id: %s\n' "$INSTANCE_ID"
  printf '%s\n' "          ansible_connection: amazon.aws.aws_ssm" "          ansible_aws_ssm_region: $REGION"
} >"$INVENTORY"
chmod 600 "$INVENTORY"
echo "Preflight correcto: identidad, región, EC2, SSM y bucket verificados (identificadores ocultos)."

[[ "$ACTION" == preflight ]] && exit 0
[[ "${NEXO_ALLOW_CLOUD_CHANGES:-}" == YES ]] || {
  echo "Cambio bloqueado: requiere la autorización vigente y NEXO_ALLOW_CLOUD_CHANGES=YES." >&2; exit 1;
}
if [[ "$ACTION" == deploy ]]; then
  RECEIPT="${NEXO_MIGRATION_BACKUP_RECEIPT:-}"
  [[ "$RECEIPT" =~ ^/var/lib/nexoeventos/backups/[A-Za-z0-9._-]+\.receipt$ ]] || {
    echo "Falta NEXO_MIGRATION_BACKUP_RECEIPT con el recibo remoto 0600 del respaldo previo." >&2
    exit 1
  }
  printf 'migration_backup_receipt: %s\n' "$RECEIPT" >>"$RUNTIME"
  "$ROOT/scripts/build-release.sh"
  ansible-playbook -i "$INVENTORY" "$ROOT/ansible/playbooks/deploy.yml" --limit nexoeventos-academy-app
else
  ansible-playbook -i "$INVENTORY" "$ROOT/ansible/playbooks/rollback.yml" --limit nexoeventos-academy-app
fi
