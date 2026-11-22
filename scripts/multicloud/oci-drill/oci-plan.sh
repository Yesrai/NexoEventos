#!/usr/bin/env bash
# Plan de SOLO LECTURA de la recuperación en OCI con los módulos existentes (infra/oci), validado por plan_guard.py. NO ejecuta apply ni destroy.
# Uso: oci-plan.sh create|teardown [--var-file work/terraform-envs/<archivo>.tfvars]
#   create   → work/terraform-envs/oci-app-demo.tfvars      (VM + Bastion + regla HTTPS temporal)
#   teardown → work/terraform-envs/oci-app-teardown.tfvars  (retira SOLO esos tres recursos y la salida 443)
# Escribe el plan binario en work/terraform-plans/oci-<modo>-<fecha>.tfplan (local) y sale con el código de plan_guard (1 = el plan toca algo fuera de la lista blanca).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"; MODE="${1:?create|teardown}"; shift || true; VF=""
while [[ $# -gt 0 ]]; do case "$1" in --var-file) VF="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
case "$MODE" in create) VF="${VF:-$ROOT/work/terraform-envs/oci-app-demo.tfvars}";; teardown) VF="${VF:-$ROOT/work/terraform-envs/oci-app-teardown.tfvars}";; *) echo "Modo inválido" >&2; exit 2;; esac
[[ -r "$VF" ]] || { echo "No existe $VF" >&2; exit 2; }
VF="$(cd "$(dirname "$VF")" && pwd)/$(basename "$VF")"   # ruta absoluta: el script cambia de directorio
export TF_IN_AUTOMATION=1 SUPPRESS_LABEL_WARNING=True
cd "$ROOT/infra/oci"
terraform init -reconfigure -backend-config="path=$ROOT/work/terraform-state/oci/terraform.tfstate" -input=false >/dev/null
terraform validate >/dev/null
PLAN="$ROOT/work/terraform-plans/oci-$MODE-$(date -u +%Y%m%dT%H%M%SZ).tfplan"
PLANOUT="$(mktemp)"; trap 'rm -f "$PLANOUT" "${J:-}"' EXIT
terraform plan -lock=false -input=false -refresh=true -var-file="$VF" -out="$PLAN" -no-color >"$PLANOUT" 2>&1 || { sed -E 's/ocid1\.[a-z]+\.oc1\.[a-z0-9-]*\.[a-z0-9]+/<ocid>/g' "$PLANOUT" | tail -15 >&2; echo "terraform plan FALLÓ" >&2; exit 2; }
sed -E 's/ocid1\.[a-z]+\.oc1\.[a-z0-9-]*\.[a-z0-9]+/<ocid>/g' "$PLANOUT" | grep -E "^(  # |Plan:|No changes)" || true
J="$(mktemp)"; terraform show -json "$PLAN" > "$J"
python3 "$ROOT/scripts/multicloud/oci-drill/plan_guard.py" --mode "$MODE" --plan-json "$J"
echo "Plan guardado (no aplicado): ${PLAN#$ROOT/}"
