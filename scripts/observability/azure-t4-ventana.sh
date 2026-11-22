#!/usr/bin/env bash
# T4 — ventana de la VM de Azure ya existente (NO crea recursos). Modos:
#   --check            solo lectura: estado de la VM, horario de apagado automático y reglas de entrada del NSG (guarda el estado original en work/t4/ventana-original.json, 0600)
#   --iniciar H        enciende la VM (az vm start) y mueve el apagado automático a ahora + H horas (1–8). Requiere --aplicar "INICIAR VENTANA T4"
#   --cerrar           desasigna la VM (az vm deallocate, verifica «deallocated») y RESTAURA el horario original de apagado automático. Requiere --aplicar "CERRAR VENTANA T4"
# Sin --aplicar solo imprime lo que haría. Pruebas: AZ_BIN (sustituye a `az`), T4_DIR (carpeta de estado).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; AZ="${AZ_BIN:-az}"; D="${T4_DIR:-$ROOT/work/t4}"; RG="rg-nexoeventos-observabilidad"; VM="vm-nexoeventos-obs"; SCH="shutdown-computevm-vm-nexoeventos-obs"
MODE=""; HOURS=""; FRASE=""
while [[ $# -gt 0 ]]; do case "$1" in --check) MODE=check; shift;; --iniciar) MODE=iniciar; HOURS="$2"; shift 2;; --cerrar) MODE=cerrar; shift;; --aplicar) FRASE="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
[[ -n "$MODE" ]] || { echo "Uso: --check | --iniciar H | --cerrar [--aplicar frase]" >&2; exit 2; }
umask 077; mkdir -p "$D"; ORIG="$D/ventana-original.json"
power() { "$AZ" vm get-instance-view -g "$RG" -n "$VM" --query "instanceView.statuses[?starts_with(code,'PowerState/')].code|[0]" -o tsv; }
sched_time() { "$AZ" resource show -g "$RG" -n "$SCH" --resource-type Microsoft.DevTestLab/schedules --query properties.dailyRecurrence.time -o tsv; }
# Programación COMPLETA (estado, hora, zona, notificaciones) normalizada: se guarda tal cual al principio y se compara entera al restaurar.
sched_full() { "$AZ" resource show -g "$RG" -n "$SCH" --resource-type Microsoft.DevTestLab/schedules --query "properties.{status:status,time:dailyRecurrence.time,tz:timeZoneId,notif:notificationSettings.status,notifMin:notificationSettings.timeInMinutes,target:targetResourceId}" -o json | python3 -c "import json,sys;print(json.dumps(json.load(sys.stdin),sort_keys=True))"; }
nsg_in() { "$AZ" network nsg rule list -g "$RG" --nsg-name nsg-nexoeventos-obs --query "sort_by([?direction=='Inbound'],&name)[].[name,access,destinationPortRange,sourceAddressPrefix]" -o json | python3 -c "import json,sys,hashlib;d=json.load(sys.stdin);print(hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()[:16], len(d))"; }
case "$MODE" in
check)
  P="$(power)"; T="$(sched_time)"; N="$(nsg_in)"
  if [[ ! -s "$ORIG" ]]; then python3 - "$ORIG" "$P" "$T" "$N" "$(sched_full)" <<'PY'
import json, sys
json.dump({"power": sys.argv[2], "apagado_utc": sys.argv[3], "nsg_entrada": sys.argv[4], "programacion": json.loads(sys.argv[5])}, open(sys.argv[1], "w"), indent=1)
PY
  fi
  echo "VM=$P apagado_automatico=$T UTC nsg_entrada(huella,n)=$N  original guardado en $ORIG";;
iniciar)
  [[ "$HOURS" =~ ^[1-8]$ ]] || { echo "H debe ser 1–8" >&2; exit 2; }
  [[ -s "$ORIG" ]] || { echo "Ejecute antes --check (guarda el estado original)" >&2; exit 2; }
  target=$(( $(date -u +%s) / 60 * 60 + HOURS * 3600 )); hhmm="$(date -u -r "$target" +%H%M)"
  echo "Plan: az vm start; apagado automático → $hhmm UTC (ahora + ${HOURS} h). VM actual: $(power)"
  [[ "$FRASE" == "INICIAR VENTANA T4" ]] || { echo "Modo plan: no se cambió nada."; exit 0; }
  "$AZ" resource update -g "$RG" -n "$SCH" --resource-type Microsoft.DevTestLab/schedules --set properties.dailyRecurrence.time="$hhmm" >/dev/null
  "$AZ" vm start -g "$RG" -n "$VM" >/dev/null; echo "VM=$(power) apagado=$hhmm UTC";;
cerrar)
  [[ -s "$ORIG" ]] || { echo "No hay estado original guardado: no se puede restaurar" >&2; exit 2; }
  OT="$(python3 -c "import json;print(json.load(open('$ORIG'))['apagado_utc'])")"
  echo "Plan: az vm deallocate (verificar deallocated); apagado automático → $OT UTC (original). VM actual: $(power)"
  [[ "$FRASE" == "CERRAR VENTANA T4" ]] || { echo "Modo plan: no se cambió nada."; exit 0; }
  "$AZ" vm deallocate -g "$RG" -n "$VM" >/dev/null
  for _ in 1 2 3 4 5 6; do [[ "$(power)" == "PowerState/deallocated" ]] && break; sleep 10; done
  "$AZ" resource update -g "$RG" -n "$SCH" --resource-type Microsoft.DevTestLab/schedules --set properties.dailyRecurrence.time="$OT" >/dev/null
  ORIG_FULL="$(python3 -c "import json;print(json.dumps(json.load(open('$ORIG'))['programacion'],sort_keys=True))")"
  [[ "$(power)" == "PowerState/deallocated" && "$(sched_time)" == "$OT" && "$(sched_full)" == "$ORIG_FULL" ]] && echo "OK    VM desasignada y programación de apagado restaurada EXACTAMENTE ($OT UTC; estado, zona y notificaciones iguales)" || { echo "FALLA: estado final inesperado (VM o programación distinta de la original)" >&2; exit 3; };;
esac
