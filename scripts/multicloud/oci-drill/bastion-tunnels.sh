#!/usr/bin/env bash
# Abre/cierra los dos túneles de OCI Bastion (reenvío de puerto) hacia la VM temporal: SSH (127.0.0.1:$LPORT → VM:22) y HTTPS (127.0.0.1:$HPORT → VM:443). La clave SSH debe estar en el agente
# (ssh-add; el script nunca ve la frase). Solo CREA sesiones de Bastion (efímeras, TTL ≤ 1 h) y procesos ssh locales; las sesiones se cierran/caducan solas y `close` mata los túneles.
# Uso: bastion-tunnels.sh open  [--compartment-name nexoeventos] [--lport 2222] [--hport 8443] [--ssh-pub ~/.ssh/nexoeventos_recovery.pub]
#      bastion-tunnels.sh close
set -euo pipefail
export SUPPRESS_LABEL_WARNING=True PYTHONWARNINGS=ignore
O() { oci "$@" --profile "${OCI_PROFILE_ADMIN:-DEFAULT}" --region sa-saopaulo-1 2>/dev/null; }
MODE="${1:?open|close}"; shift || true; LPORT=2222; HPORT=8443; PUB="$HOME/.ssh/nexoeventos_recovery.pub"; CN=nexoeventos; STATE="${BASTION_TUNNEL_STATE:-/tmp/nexo-bastion-tunnels.pids}"
while [[ $# -gt 0 ]]; do case "$1" in --lport) LPORT="$2"; shift 2;; --hport) HPORT="$2"; shift 2;; --ssh-pub) PUB="$2"; shift 2;; --compartment-name) CN="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
if [[ "$MODE" == close ]]; then
  [[ -f "$STATE" ]] && { while read -r pid; do kill "$pid" 2>/dev/null || true; done <"$STATE"; rm -f "$STATE"; echo "túneles cerrados"; } || echo "no hay túneles registrados"; exit 0
fi
TEN="$(grep -E '^tenancy' ~/.oci/config | head -1 | cut -d= -f2 | tr -d ' ')"
CMP="$(O iam compartment list --compartment-id "$TEN" --all --query "data[?name=='$CN'].id|[0]" --raw-output)"
BAS="$(O bastion bastion list --compartment-id "$CMP" --all --bastion-lifecycle-state ACTIVE --query 'data[0].id' --raw-output)"
INS="$(O compute instance list --compartment-id "$CMP" --all --lifecycle-state RUNNING --query 'data[0].id' --raw-output)"
[[ "$BAS" == ocid1.* && "$INS" == ocid1.* ]] || { echo "No hay Bastion ACTIVE o VM RUNNING en el compartimento." >&2; exit 3; }
IP="$(O compute instance list-vnics --instance-id "$INS" --query 'data[0]."private-ip"' --raw-output)"
: >"$STATE"; chmod 600 "$STATE"
for pair in "$LPORT:22" "$HPORT:443"; do
  lp="${pair%%:*}"; tp="${pair##*:}"
  SID="$(O bastion session create-port-forwarding --bastion-id "$BAS" --target-resource-id "$INS" --target-port "$tp" --target-private-ip "$IP" --ssh-public-key-file "$PUB" --session-ttl 3600 --display-name "nexo-recovery-$tp" --wait-for-state SUCCEEDED --query 'data.resources[0].identifier' --raw-output || true)"
  SID="${SID:-}"
  if [[ "$SID" != ocid1.bastionsession.* ]]; then   # con --wait-for-state el identificador viene en la solicitud de trabajo; si no, se busca la sesión ACTIVE más reciente de ese puerto
    SID="$(O bastion session list --bastion-id "$BAS" --session-lifecycle-state ACTIVE --sort-by timeCreated --sort-order DESC --query "data[?\"display-name\"=='nexo-recovery-$tp']|[0].id" --raw-output)"
  fi
  [[ "$SID" == ocid1.bastionsession.* ]] || { echo "No se obtuvo la sesión de Bastion para el puerto $tp." >&2; exit 4; }
  for _ in $(seq 1 30); do [[ "$(O bastion session get --session-id "$SID" --query 'data."lifecycle-state"' --raw-output)" == ACTIVE ]] && break; sleep 3; done
  HOST="host.bastion.sa-saopaulo-1.oci.oraclecloud.com"
  # El Bastion puede rechazar los primeros intentos mientras el agente de la VM y la sesión terminan de activarse (visto el 19-nov): se reintenta unos segundos antes de rendirse.
  up=0; for try in 1 2 3 4 5 6; do
    if ssh -N -f -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes -i "${PUB%.pub}" -o BatchMode=yes \
         -L "127.0.0.1:$lp:$IP:$tp" -p 22 "$SID@$HOST" 2>/dev/null; then up=1; break; fi; sleep 5; done
  [[ "$up" == 1 ]] || { echo "No se pudo abrir el túnel $lp→$tp tras 6 intentos (sesión de Bastion o agente de la VM no activos)." >&2; exit 5; }
  pgrep -f "127.0.0.1:$lp:$IP:$tp" | head -1 >>"$STATE"
  echo "OK    túnel 127.0.0.1:$lp → VM:$tp (sesión de Bastion ACTIVE)"
done
