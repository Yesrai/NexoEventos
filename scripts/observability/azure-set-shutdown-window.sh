#!/usr/bin/env bash
# Fija la hora del apagado automático (DevTest Labs auto-shutdown: UNA hora fija DIARIA, en UTC) = ahora + duración de la ventana (por defecto 4 h, redondeada
# hacia abajo al minuto, nunca más de la ventana), la guarda en work/terraform-envs/azure-shutdown.tfvars (0600, ignorado por Git) y regenera el plan guardado.
# Ejecutar JUSTO ANTES del apply (el plan caduca para este fin a las 30 min: azure-window-preflight.sh lo comprueba). No aplica nada.
# Uso: scripts/observability/azure-set-shutdown-window.sh [--hours 4] [--no-plan]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; HOURS=4; PLAN=1
OUTV="$ROOT/work/terraform-envs/azure-shutdown.tfvars"; PLANF="$ROOT/work/terraform-plans/azure-vm-incremental.tfplan"
while [[ $# -gt 0 ]]; do case "$1" in --hours) HOURS="$2"; shift 2;; --no-plan) PLAN=0; shift;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
[[ "$HOURS" =~ ^[1-8]$ ]] || { echo "--hours debe ser un entero entre 1 y 8." >&2; exit 2; }
target=$(( $(date -u +%s) / 60 * 60 + HOURS * 3600 ))
hhmm="$(date -u -r "$target" +%H%M)"; umask 077
printf '# Generado por azure-set-shutdown-window.sh (no versionar)\nshutdown_time_utc = "%s"\n' "$hhmm" > "$OUTV"; chmod 600 "$OUTV"
echo "Apagado automático fijado a las $(date -u -r "$target" +%H:%M) UTC (= $(date -r "$target" '+%H:%M %Z' ) hora local de esta estación) para una ventana de ${HOURS} h. Se repite cada día a esa hora."
if (( PLAN )); then
  cd "$ROOT/infra/azure"
  terraform plan -var-file=../../work/terraform-envs/azure-vm.tfvars -var-file=../../work/terraform-envs/azure-shutdown.tfvars -out="$PLANF" -no-color > "$ROOT/work/terraform-plans/azure-vm-incremental.txt" 2>&1 || { echo "ERROR: terraform plan falló (ver work/terraform-plans/azure-vm-incremental.txt)" >&2; exit 1; }
  chmod 600 "$PLANF"; grep -E '^Plan:' "$ROOT/work/terraform-plans/azure-vm-incremental.txt"
fi
