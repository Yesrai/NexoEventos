#!/usr/bin/env bash
# Apagado automático de seguridad de la VM de monitoreo: al vencer la ventana EJECUTA `az vm deallocate` (libera el cómputo; apagar Ubuntu no basta:
# una VM «Stopped» sigue facturando) y VERIFICA que el estado sea PowerState/deallocated, reintentando. No crea recursos en Azure ni requiere permisos
# nuevos: usa la sesión de Azure CLI del operador (rol Owner). Limitación honesta: depende de que esta estación esté encendida y con sesión de az
# (con `caffeinate` evita la suspensión por inactividad; si el Mac duerme, actúa al despertar porque compara con la hora real).
# Uso:  scripts/observability/azure-vm-watchdog.sh --check                 # prueba de solo lectura (cuenta, VM, permisos); no apaga nada
#       nohup caffeinate -i -s scripts/observability/azure-vm-watchdog.sh --minutes 240 >/dev/null 2>&1 &     # arma el apagado a las 4 h
#       touch work/operacion/azure-watchdog.stop                          # cancela (p. ej. tras desasignar a mano)
# Pruebas: AZ_BIN, NEXO_WATCHDOG_TEST_SECONDS (sustituye --minutes), NEXO_WATCHDOG_NO_NOTIFY=1.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RG="rg-nexoeventos-observabilidad"; VM="vm-nexoeventos-obs"; MIN=240; POLL=30; CHECK=0; AZ="${AZ_BIN:-az}"
OPS="$ROOT/work/operacion"; LOG="$OPS/azure-watchdog.log"; STOP="$OPS/azure-watchdog.stop"
while [[ $# -gt 0 ]]; do case "$1" in --minutes) MIN="$2"; shift 2;; --poll-seconds) POLL="$2"; shift 2;; --check) CHECK=1; shift;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
[[ "$MIN" =~ ^[0-9]+$ ]] && (( MIN >= 1 && MIN <= 480 )) || { echo "--minutes debe estar entre 1 y 480 (tope de seguridad de 8 h)." >&2; exit 2; }
mkdir -p "$OPS"; umask 077
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }
notify() { [[ "${NEXO_WATCHDOG_NO_NOTIFY:-0}" == 1 ]] || osascript -e "display notification \"$1\" with title \"NexoEventos Azure\"" >/dev/null 2>&1 || true; }
power() { "$AZ" vm get-instance-view -g "$RG" -n "$VM" --query "instanceView.statuses[?starts_with(code,'PowerState/')].code | [0]" -o tsv 2>/dev/null; }

st="$("$AZ" account show --query state -o tsv 2>/dev/null || true)"
[[ "$st" == "Enabled" ]] || { log "ERROR: sesión de Azure CLI ausente o suscripción no habilitada (estado='${st:-?}'). Ejecute az login y reintente."; exit 1; }
ps="$(power || true)"
if [[ -z "$ps" ]]; then
  if (( CHECK )); then log "COMPROBACIÓN: la VM $VM aún no existe o no se puede leer (esperado ANTES del apply)."; exit 0; fi
  log "ERROR: no se puede leer la VM (¿no existe todavía?). Arme el apagado DESPUÉS de crearla."; exit 1
fi
roles="$("$AZ" role assignment list --all --assignee "$("$AZ" ad signed-in-user show --query id -o tsv 2>/dev/null)" --query "[].roleDefinitionName" -o tsv 2>/dev/null | sort -u | tr '\n' ' ')"
if (( CHECK )); then
  log "COMPROBACIÓN: sesión OK; VM visible en estado ${ps#PowerState/}; roles del operador: ${roles:-no legibles}. No se apagó nada."
  [[ " $roles " == *" Owner "* || " $roles " == *" Contributor "* || " $roles " == *" Virtual Machine Contributor "* ]] || { log "AVISO: no se ve un rol con permiso de desasignar (Owner/Contributor)."; exit 1; }
  exit 0
fi

secs=$(( ${NEXO_WATCHDOG_TEST_SECONDS:-$((MIN*60))} )); start=$(date +%s); deadline=$((start+secs)); rm -f "$STOP"
log "ARMADO: se desasignará $VM a las $(date -u -r "$deadline" +%H:%M:%SZ) (en ${secs}s). Cancelar: touch ${STOP#$ROOT/}"
warned30=0; warned10=0
while :; do
  now=$(date +%s); left=$((deadline-now))
  [[ -e "$STOP" ]] && { log "CANCELADO por archivo de parada; no se desasigna."; exit 0; }
  (( left <= 0 )) && break
  (( left <= 1800 && warned30 == 0 && secs > 1800 )) && { warned30=1; log "AVISO: faltan ~30 min para desasignar la VM."; notify "Faltan 30 min para desasignar la VM"; }
  (( left <= 600 && warned10 == 0 && secs > 600 )) && { warned10=1; log "AVISO: faltan ~10 min para desasignar la VM."; notify "Faltan 10 min: guarde evidencias"; }
  s=$POLL; (( left < s )) && s=$left; sleep "$s"
done

log "VENCIDA la ventana: iniciando desasignación."
for attempt in 1 2 3 4 5; do
  ps="$(power || true)"
  case "$ps" in
    PowerState/deallocated) log "VERIFICADO: la VM ya está desasignada (sin cobro de cómputo). Siguen facturando disco e IP estática."; notify "VM desasignada (verificado)"; exit 0;;
    "") log "La VM no existe o no es legible; nada que desasignar."; exit 0;;
  esac
  log "Intento $attempt/5: estado ${ps#PowerState/}; ejecutando az vm deallocate."
  "$AZ" vm deallocate -g "$RG" -n "$VM" >/dev/null 2>&1 || log "az vm deallocate devolvió error (se reintentará y se verificará el estado real)."
  sleep "${NEXO_WATCHDOG_RETRY_SLEEP:-20}"
done
ps="$(power || true)"
[[ "$ps" == "PowerState/deallocated" || -z "$ps" ]] && { log "VERIFICADO: la VM quedó desasignada."; notify "VM desasignada (verificado)"; exit 0; }
log "FALLO: tras 5 intentos la VM sigue en ${ps#PowerState/}. INTERVENGA YA: az vm deallocate -g $RG -n $VM"; notify "FALLO al desasignar la VM: intervenga ya"; printf '\a'; exit 2
