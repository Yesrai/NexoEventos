#!/usr/bin/env bash
# v2-down — APAGA las EC2 de V2: pone mínima=0 y deseada=0 en el ASG (no lo destruye) y espera a que no queden instancias.
# NO toca V1, la RDS ni el ALB (estos siguen facturando). Para volver a encender: ./v2-up.sh
# Uso: ./v2-down.sh [--dry-run] [--timeout SEGUNDOS]      (por defecto 600 s)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
DRY=0; TIMEOUT=600
while [[ $# -gt 0 ]]; do case "$1" in --dry-run) DRY=1;; --timeout) TIMEOUT="${2:?}"; shift;; *) die "Opción desconocida: $1";; esac; shift; done
need_tools; check_identity; find_asg; load_asg; load_alb
print_status; v1_before="$(v1_state)"
if (( ASG_MIN == 0 && ASG_DES == 0 && ASG_TOTAL == 0 )); then verdict; echo "Ya estaba apagada: no hago nada."; exit 0; fi
echo; echo "PLAN: poner mínima=0 y deseada=0 en $ASG_NAME (se terminarán $ASG_TOTAL instancia(s)). El grupo, el ALB, la RDS y V1 no se tocan."
echo "AVISO: mientras V2 esté en 0 el ALB responde 503."
if (( DRY )); then echo "(--dry-run) No se ejecuta nada."; exit 0; fi
confirm_phrase "APAGAR V2"
set_capacity 0 0
start=$SECONDS
while :; do
  load_asg
  elapsed=$(( SECONDS - start ))
  echo "  [${elapsed}s] instancias en el grupo=$ASG_TOTAL"
  (( ASG_TOTAL == 0 )) && break
  if (( elapsed >= TIMEOUT )); then
    print_status; die "Tiempo máximo (${TIMEOUT}s) agotado: aún quedan $ASG_TOTAL instancia(s) terminando. La capacidad ya está en 0; vuelve a ejecutar ./v2-status.sh en unos minutos."
  fi
  sleep "$POLL_INTERVAL"
done
load_alb; echo; print_status
v1_after="$(v1_state)"
[[ "$v1_before" == "$v1_after" ]] && info "EC2 de V1 sin cambios ($v1_after)." || echo "ATENCIÓN: el estado de V1 cambió ($v1_before → $v1_after) por causa ajena a este script."
ok "V2 APAGADA en $(( SECONDS - start )) s. Siguen facturando el ALB y la RDS. Para volver a encender: ./v2-up.sh"
