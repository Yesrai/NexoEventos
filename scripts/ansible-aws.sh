#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-}"
PROFILE="${NEXO_AWS_PROFILE:-nexoeventos-lab}"
TFVARS="$ROOT/work/terraform-envs/academy.tfvars"
RUNTIME="$ROOT/work/ansible/runtime.yml"
export ANSIBLE_CONFIG="$ROOT/ansible/ansible.cfg"

case "$ACTION" in preflight|deploy|rollback) ;; *)
  echo "Uso: $0 {preflight|deploy|rollback}" >&2; exit 2 ;;
esac
for command_name in aws ansible-playbook session-manager-plugin; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Falta el requisito local: $command_name" >&2; exit 1;
  }
done
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
RELEASE_ID="$(git -C "$ROOT" rev-parse HEAD)"
ARTIFACT="$ROOT/work/releases/nexoeventos-${RELEASE_ID}.tar.gz"
{
  printf '%s\n' '---'
  printf 'aws_profile: %s\n' "$PROFILE"
  printf 'ssm_bucket_name: %s\n' "$BUCKET"
  printf 'release_id: %s\n' "$RELEASE_ID"
  printf 'release_artifact: %s\n' "$ARTIFACT"
} >"$RUNTIME"
chmod 600 "$RUNTIME"
echo "Preflight correcto: identidad, región, EC2, SSM y bucket verificados (identificadores ocultos)."

[[ "$ACTION" == preflight ]] && exit 0
[[ "${NEXO_ALLOW_CLOUD_CHANGES:-}" == YES ]] || {
  echo "Cambio bloqueado: requiere la autorización vigente y NEXO_ALLOW_CLOUD_CHANGES=YES." >&2; exit 1;
}
if [[ "$ACTION" == deploy ]]; then
  "$ROOT/scripts/build-release.sh"
  ansible-playbook "$ROOT/ansible/playbooks/deploy.yml" --limit "$INSTANCE_ID"
else
  ansible-playbook "$ROOT/ansible/playbooks/rollback.yml" --limit "$INSTANCE_ID"
fi
