#!/usr/bin/env bash
# v2-up — ENCIENDE V2: pide 2 instancias al ASG (mín=2, deseada=2) y espera a que estén InService/Healthy en 2 zonas.
# Uso: ./v2-up.sh [--dry-run] [--timeout SEGUNDOS]      (por defecto 600 s)
# Requiere: la RDS en 'available' (si no, no hace nada) y confirmación escrita.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
DRY=0; TIMEOUT=600
while [[ $# -gt 0 ]]; do case "$1" in --dry-run) DRY=1;; --timeout) TIMEOUT="${2:?}"; shift;; *) die "Opción desconocida: $1";; esac; shift; done
need_tools; check_identity; find_asg; load_asg; load_alb
print_status
db="$(rds_state)"
[[ "$db" == "available" ]] || die "La RDS ($V2_RDS_ID) está '$db', no 'available'. V2 necesita la base: inicia la RDS primero. No cambié nada."
(( ASG_MAX >= 2 )) || die "La capacidad máxima del grupo es $ASG_MAX (<2); no puedo pedir 2 instancias."
if (( ASG_MIN == 2 && ASG_DES >= 2 && ASG_READY >= 2 )); then verdict; echo "Ya estaba encendida: no hago nada."; exit 0; fi
echo; echo "PLAN: poner mínima=2 y deseada=2 en $ASG_NAME (máxima sigue en $ASG_MAX). No se crean ni borran otros recursos."
if (( DRY )); then echo "(--dry-run) No se ejecuta nada."; exit 0; fi
confirm_phrase "ENCENDER V2"
set_capacity 2 2
start=$SECONDS
while :; do
  load_asg; load_alb
  elapsed=$(( SECONDS - start ))
  echo "  [${elapsed}s] listas=$ASG_READY/2 zonas=$ASG_ZONES destinos healthy=$TG_HEALTHY"
  if (( ASG_READY >= 2 && ASG_ZONES >= 2 && TG_HEALTHY >= 2 )); then break; fi
  if (( elapsed >= TIMEOUT )); then
    echo; print_status; echo "Últimas actividades del grupo:"; recent_activities
    die "Tiempo máximo (${TIMEOUT}s) agotado: V2 no quedó completa. El grupo sigue con deseada=2; revisa las actividades y, si hace falta, ejecuta ./v2-down.sh para revertir."
  fi
  sleep "$POLL_INTERVAL"
done
echo; print_status
# Comprobación HTTPS por el ALB sin tocar DNS: se resuelve la IP del ALB en este momento (no hay IP fija).
if [[ "${V2_SKIP_HTTP:-0}" != "1" && -n "$ALB_DNS" ]] && command -v dig >/dev/null && command -v curl >/dev/null; then
  ip="$(dig +short "$ALB_DNS" | grep -E '^[0-9.]+$' | head -1)"
  code="$(curl -s -o /dev/null -m 15 -w '%{http_code}' --resolve "$V2_DOMAIN:443:$ip" "https://$V2_DOMAIN/livez" || true)"
  info "HTTPS $V2_DOMAIN/livez vía ALB ($ip, resuelta ahora): HTTP $code"
  [[ "$code" == "200" ]] || die "El ALB no respondió 200 en /livez (código $code)."
fi
ok "V2 ENCENDIDA en $(( SECONDS - start )) s. Para apagarla: ./v2-down.sh"
