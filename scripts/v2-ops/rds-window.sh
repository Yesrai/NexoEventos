#!/usr/bin/env bash
# rds-window — ventana CONTROLADA de la RDS de negocio para la prueba de AWS V2 (B1). Solo toca `nexoeventos-academy-postgres` y solo con start-db-instance / stop-db-instance (no modifica datos).
#   check                       solo lectura: cuenta/región, RDS stopped, ASG en 0, sin EC2 ni ALB; informa si el watchdog está armado. No cambia nada.
#   watchdog --minutes N        APAGADO DE SEGURIDAD independiente (N ≤ 120). Se arma ANTES de encender. Detiene la RDS (y verifica `stopped`) cuando: vence la ventana, el LATIDO
#                               se queda viejo (la prueba se interrumpió), o hay credenciales caducadas que impiden vigilarla (alerta fuerte). Cancelar: `cancel`.
#   start --minutes N           (cambia AWS) exige NEXO_ALLOW_CLOUD_CHANGES=YES y --confirm "ENCENDER RDS": rehace `check`, ARMA el watchdog, comprueba que sigue vivo y solo entonces enciende la RDS y espera `available`. Termina y no hace nada más.
#   chain --minutes N [--scenario first|resume]           (cambia AWS) B1 + B2 EN UNA SOLA VENTANA sin pausas: enciende la RDS, REGENERA el plan de Terraform y lo REVISA (exactamente 8 creaciones permitidas + 1 modificación del ASG 0→2;
#                               cualquier destrucción, sustitución o cambio fuera de esos 9 ABORTA y apaga todo), aplica SOLO ese plan guardado, espera 2 destinos sanos en 2 zonas y comprueba HTTPS y /livez.
#                               Exige NEXO_ALLOW_CLOUD_CHANGES=YES, --confirm "ENCENDER RDS Y APLICAR V2" y --not-after HH:MMZ (hora límite de inicio). Mantiene el latido hasta la hora límite (nunca la amplía). Se detiene tras B2.
#   beat                        actualiza el latido (quien conduce la prueba lo ejecuta periódicamente).
#   cancel                      cancela el watchdog (p. ej. tras detener la RDS a mano).
#   stop-now                    (cambia AWS) detiene la RDS ahora y verifica `stopped`; exige NEXO_ALLOW_CLOUD_CHANGES=YES.
# PARADA: el watchdog distingue una parada que AVANZA (RDS en `stopping`, normal en Multi-AZ: 5–15 min) de una fallida. Plazo total NEXO_STOP_DEADLINE_S (def. 1800 s) con reintentos de `stop-db-instance`
# solo cuando la RDS está `available`; alerta intermedia a mitad de plazo; si vence: estado PARADA_INCOMPLETA (archivo rds-window.state, alerta fuerte, salida 2). Con `--also-v2` (la usa `chain`) primero lleva el ASG a 0 y elimina el ALB
# de V2 (red de seguridad de emergencia: el estado de Terraform quedará desfasado hasta el siguiente plan/apply; apagar la RDS NO limpia el ALB ni las EC2).
# Limitación honesta: el watchdog corre en ESTE Mac (con `caffeinate`); si el Mac se apaga o pierde red/credenciales, no puede detener la RDS: por eso avisa antes y la ventana máxima es de 2 h
# (la sesión de Academy y su reinicio automático de la RDS a los 7 días son la red de seguridad última). Pruebas: AWS_BIN, NEXO_WATCHDOG_TEST_SECONDS, NEXO_WATCHDOG_NO_NOTIFY=1.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-nexoeventos-lab}" AWS_REGION="us-east-1" AWS_DEFAULT_REGION="us-east-1" AWS_PAGER=""
AWS="${AWS_BIN:-aws}"; RDS="nexoeventos-academy-postgres"; ASG="nexoeventos-academy-v2-asg"
OPS="${NEXO_OPS_DIR:-$ROOT/work/operacion}"; LOG="$OPS/rds-window.log"; STOP="$OPS/rds-window.stop"; BEAT="$OPS/rds-window.beat"; PIDF="$OPS/rds-window.pid"
COMMON="$ROOT/work/terraform-envs/academy-v2-common.tfvars"
CMD="${1:-}"; shift || true; MIN=""; CONFIRM=""; POLL="${NEXO_WATCHDOG_POLL:-30}"; STALE="${NEXO_WATCHDOG_STALE_MIN:-20}"; ALSO_V2="${NEXO_ALSO_V2:-0}"; NOTAFTER=""; CREDS_UNTIL=""; SCENARIO="first"
TF_DIR="${V2_TF_DIR:-$ROOT/infra/aws-v2}"; PLAN_DIR="${V2_PLAN_DIR:-$ROOT/work/operacion/v2-plans}"; ON_VARS="${V2_ON_VARS:-$ROOT/work/terraform-envs/academy-v2-on.tfvars}"
STATE="$OPS/rds-window.state"; ABORT="$OPS/rds-window.abort"; KEEP="$OPS/rds-window.keepalive"
STOP_DEADLINE="${NEXO_STOP_DEADLINE_S:-1800}"; STOP_POLL="${NEXO_STOP_POLL_S:-20}"
ALB_NAME="nexoeventos-academy-v2-alb"; V2_EC2_NAME="nexoeventos-academy-v2-app"; TF_BIN="${TF_BIN:-terraform}"; V2_DOMAIN="${V2_DOMAIN:-nexoeventos-demo.duckdns.org}"
while [[ $# -gt 0 ]]; do case "$1" in --minutes) MIN="$2"; shift 2;; --confirm) CONFIRM="$2"; shift 2;; --also-v2) ALSO_V2=1; shift;; --not-after) NOTAFTER="$2"; shift 2;; --creds-until) CREDS_UNTIL="$2"; shift 2;; --scenario) SCENARIO="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
mkdir -p "$OPS"; umask 077
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }
notify() { [[ "${NEXO_WATCHDOG_NO_NOTIFY:-0}" == 1 ]] || osascript -e "display notification \"$1\" with title \"NexoEventos RDS\"" >/dev/null 2>&1 || true; }
rds_state() { "$AWS" rds describe-db-instances --db-instance-identifier "$RDS" --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null; }
ident_ok() {
  local exp act; exp="$(awk -F= '$1 ~ /^[[:space:]]*expected_account_id[[:space:]]*$/ {gsub(/[[:space:]"]/,"",$2); print $2; exit}' "$COMMON" 2>/dev/null)"
  act="$("$AWS" sts get-caller-identity --query Account --output text 2>/dev/null)"
  [[ "$exp" =~ ^[0-9]{12}$ && "$act" == "$exp" && "$("$AWS" configure get region 2>/dev/null || echo us-east-1)" == us-east-1 ]]
}
window_min() { [[ "$MIN" =~ ^[0-9]+$ ]] && (( MIN >= 1 && MIN <= 120 )) || { echo "--minutes debe estar entre 1 y 120 (ventana máxima de 2 h)." >&2; exit 2; }; }
set_state() { printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${2:-}" >"$STATE"; }
armed() { [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; }

preflight() {   # solo lectura; devuelve 0 si se puede encender
  local bad=0 st asg ec2 alb
  ident_ok && log "OK cuenta y región coinciden con las esperadas" || { log "BLOQUEO: identidad/credenciales no válidas o cuenta distinta (¿token caducado?)"; return 1; }
  st="$(rds_state)"; [[ "$st" == stopped ]] && log "OK RDS $RDS en 'stopped'" || { log "BLOQUEO: la RDS está en '${st:-?}', se esperaba 'stopped'"; bad=1; }
  asg="$("$AWS" autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG" --query 'AutoScalingGroups[0].[MinSize,DesiredCapacity,length(Instances)]' --output text 2>/dev/null | tr -s '[:space:]' ' ' | sed 's/ $//')"
  [[ "$asg" == "0 0 0" ]] && log "OK ASG de V2 en capacidad 0 y sin instancias" || { log "BLOQUEO: ASG de V2 no está en 0/0/0 ('${asg:-?}')"; bad=1; }
  ec2="$("$AWS" ec2 describe-instances --query 'length(Reservations[].Instances[?State.Name==`running`][])' --output text 2>/dev/null)"
  [[ "$ec2" == 0 ]] && log "OK ninguna EC2 en ejecución (nada se conecta a la base)" || { log "BLOQUEO: hay ${ec2:-?} EC2 en ejecución"; bad=1; }
  alb="$("$AWS" elbv2 describe-load-balancers --query 'length(LoadBalancers)' --output text 2>/dev/null)"
  [[ "$alb" == 0 ]] && log "OK no existe ningún ALB" || { log "BLOQUEO: existe(n) ${alb:-?} ALB"; bad=1; }
  return $bad
}

v2_down() {   # emergencia (solo con --also-v2): ASG a 0, esperar sin EC2 y eliminar el ALB; cada paso se verifica y se registra
  local d arn t0; set_state APAGANDO_V2 "ASG y ALB"
  d="$("$AWS" autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG" --query 'AutoScalingGroups[0].DesiredCapacity' --output text 2>/dev/null)"
  if [[ "$d" =~ ^[0-9]+$ && "$d" != 0 ]]; then log "V2: llevando el ASG a 0 (estaba en $d)."; "$AWS" autoscaling update-auto-scaling-group --auto-scaling-group-name "$ASG" --min-size 0 --desired-capacity 0 >/dev/null 2>&1 || log "ALERTA: no se pudo llevar el ASG a 0"; fi
  t0=$(date +%s); while (( $(date +%s) - t0 < ${NEXO_V2_DOWN_S:-600} )); do
    [[ "$("$AWS" ec2 describe-instances --filters "Name=tag:Name,Values=$V2_EC2_NAME" Name=instance-state-name,Values=pending,running,stopping --query 'length(Reservations[].Instances[])' --output text 2>/dev/null)" == 0 ]] && { log "V2: sin EC2 de V2 en ejecución."; break; }; sleep "${NEXO_STOP_POLL_S:-20}"; done
  arn="$("$AWS" elbv2 describe-load-balancers --names "$ALB_NAME" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null)"
  if [[ -n "$arn" && "$arn" != None && "$arn" == arn:* ]]; then
    tags="$("$AWS" elbv2 describe-tags --resource-arns "$arn" --query 'TagDescriptions[0].Tags[].[Key,Value]' --output text 2>/dev/null | tr '\t' '=')"
    if [[ "$tags" != *"Project=NexoEventos"* || "$tags" != *"Stack=v2"* ]]; then log "ALERTA: el ALB $ALB_NAME NO tiene las etiquetas Project=NexoEventos y Stack=v2: no se elimina (podría no ser de este proyecto). Revise a mano."; arn=""; fi
  fi
  if [[ -n "$arn" && "$arn" != None && "$arn" == arn:* ]]; then log "V2: eliminando el ALB $ALB_NAME (etiquetas Project=NexoEventos, Stack=v2 verificadas)."; "$AWS" elbv2 delete-load-balancer --load-balancer-arn "$arn" >/dev/null 2>&1 || log "ALERTA: no se pudo eliminar el ALB"; fi
  [[ "$("$AWS" elbv2 describe-load-balancers --names "$ALB_NAME" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null)" != arn:* ]] && log "V2: sin ALB de V2." || log "ALERTA: aún existe el ALB de V2 (sigue facturando): revise."
}

rds_stop_verified() {   # plazo TOTAL verificable; distingue una parada que avanza de una fallida
  local t0 now st n_err=0 warned=0 last_prog=0 started=0
  t0=$(date +%s); set_state EJECUTANDO_PARADA "RDS"
  while :; do
    now=$(date +%s); el=$((now-t0))
    st="$(rds_state)"
    case "$st" in
      stopped) log "VERIFICADO: la RDS está detenida (tras ${el}s)."; set_state PARADA_VERIFICADA "${el}s"; notify "RDS detenida (verificado)"; return 0;;
      available) if (( started == 0 || el - started >= ${NEXO_STOP_RETRY_S:-60} )); then log "Parada: stop-db-instance (${el}s)."; started=$el
                   "$AWS" rds stop-db-instance --db-instance-identifier "$RDS" >/dev/null 2>&1 || { n_err=$((n_err+1)); log "stop-db-instance devolvió error ($n_err); se reintentará mientras quede plazo."; }; fi;;
      stopping) if (( el - last_prog >= 120 || last_prog == 0 )); then last_prog=$el; log "Parada AVANZANDO: la RDS sigue en 'stopping' (${el}s de ${STOP_DEADLINE}s; Multi-AZ tarda 5–15 min). No es un fallo."; fi;;
      "") log "No se puede leer la RDS (¿credenciales caducadas o sin red?); se sigue intentando mientras quede plazo."; "$AWS" sts get-caller-identity >/dev/null 2>&1 || { log "ALERTA: credenciales caducadas; renueve YA para que pueda detener la RDS."; notify "RDS: credenciales caducadas"; printf '\a'; };;
      *) log "Parada: la RDS está en '$st' (no se puede detener ahora); se espera a 'available' o 'stopped'.";;
    esac
    if (( warned == 0 && el >= STOP_DEADLINE / 2 )); then warned=1; log "ALERTA: la parada lleva más de la mitad del plazo (${el}s de ${STOP_DEADLINE}s). Estado: '${st:-?}'."; notify "RDS: la parada tarda más de lo normal"; fi
    (( el >= STOP_DEADLINE )) && break
    sleep "$STOP_POLL"
  done
  set_state PARADA_INCOMPLETA "estado=$(rds_state)"
  log "PARADA_INCOMPLETA: tras ${STOP_DEADLINE}s la RDS sigue en '$(rds_state)'. INTERVENGA YA: aws rds stop-db-instance --db-instance-identifier $RDS --profile nexoeventos-lab"; notify "PARADA_INCOMPLETA de la RDS: intervenga ya"; printf '\a'; return 2
}

shutdown_all() {
  local rc=0
  [[ "$ALSO_V2" == 1 ]] && v2_down
  rds_stop_verified || rc=$?
  return $rc
}

run_watchdog() {
  window_min; secs=$(( ${NEXO_WATCHDOG_TEST_SECONDS:-$((MIN*60))} )); start=$(date +%s); deadline=$((start+secs)); rm -f "$STOP" "$ABORT"; touch "$BEAT"; echo $$ >"$PIDF"; set_state ARMADO "hasta $(date -u -r "$deadline" +%H:%M:%SZ)"
  trap 'rm -f "$PIDF"' EXIT
  log "WATCHDOG ARMADO: detendrá $RDS a las $(date -u -r "$deadline" +%H:%M:%SZ) (en ${secs}s) o si el latido supera ${STALE} min. Cancelar: rds-window.sh cancel"
  warned=0; why=""; badcred=0
  while :; do
    now=$(date +%s); left=$((deadline-now))
    [[ -e "$STOP" ]] && { log "CANCELADO por archivo de parada; no se detiene la RDS."; exit 0; }
    [[ -e "$ABORT" ]] && { why="aborto solicitado (plan no aprobado o fallo de la prueba)"; break; }
    (( left <= 0 )) && { why="venció la ventana"; break; }
    age=$(( now - $(stat -f %m "$BEAT" 2>/dev/null || echo "$now") ))
    (( age > STALE * 60 )) && { why="latido viejo (${age}s): la prueba se interrumpió"; break; }
    (( left <= 600 && warned == 0 && secs > 600 )) && { warned=1; log "AVISO: faltan ~10 min para detener la RDS."; notify "Faltan 10 min: se detendrá la RDS"; }
    if ! "$AWS" sts get-caller-identity >/dev/null 2>&1; then
      (( badcred++ )); log "ALERTA: credenciales de AWS caducadas o sin red; NO puedo vigilar ni detener la RDS hasta renovarlas (aviso $badcred)."; notify "RDS: credenciales caducadas, renueve y detenga la RDS"; printf '\a'
    else badcred=0; fi
    s=$POLL; (( left < s )) && s=$left; sleep "$s"
  done
  log "DISPARO: $why."
  shutdown_all; exit $?
}

start_rds_window() {   # B1: comprobaciones, watchdog armado y verificado, start-db-instance, espera a available
  preflight || { log "BLOQUEADO: no se enciende nada."; return 1; }
  armed && { log "BLOQUEO: ya hay un watchdog armado (pid $(cat "$PIDF")); cancélelo o espere."; return 1; }
  rm -f "$ABORT" "$STOP" "$KEEP"
  NEXO_ALSO_V2="$ALSO_V2" nohup caffeinate -i -s "$0" watchdog --minutes "$MIN" >/dev/null 2>&1 &
  for _ in 1 2 3 4 5 6 7 8 9 10; do armed && break; sleep 1; done
  armed || { log "BLOQUEO: el watchdog no quedó armado; no se enciende la RDS."; return 1; }
  log "Watchdog verificado (pid $(cat "$PIDF")). Encendiendo $RDS (solo start-db-instance)."
  "$AWS" rds start-db-instance --db-instance-identifier "$RDS" >/dev/null 2>&1 || { log "start-db-instance falló; el watchdog sigue armado (detendrá si hace falta)."; return 1; }
  local end st; end=$(( $(date +%s) + ${NEXO_START_WAIT:-1500} ))
  while (( $(date +%s) < end )); do
    st="$(rds_state)"; [[ "$st" == available ]] && { log "RDS AVAILABLE. Ventana de ${MIN} min en curso."; return 0; }
    sleep "${NEXO_POLL:-15}"
  done
  log "La RDS no llegó a 'available' en el plazo; el watchdog sigue armado. Estado: $(rds_state)"; return 1
}

# Hora UTC → epoch. Acepta `YYYY-MM-DDTHH:MMZ` (fecha completa; recomendado si la ventana o la caducidad cruzan la medianoche UTC) y `HH:MMZ`.
# `HH:MMZ` se resuelve con la fecha UTC de hoy; si esa hora ya pasó hace MÁS de 12 h se entiende que es de mañana (cruce de medianoche); si pasó hace menos, se deja
# en el pasado y quien llama la rechaza como vencida. Fechas u horas inválidas (30-feb, 25:00, otro formato) salen con error. NEXO_TEST_NOW_EPOCH solo existe para las pruebas.
hhmm_epoch() { python3 - "$1" <<'PY'
import sys,re,os,datetime as dt
U=dt.timezone.utc; s=sys.argv[1]
now=dt.datetime.fromtimestamp(float(os.environ["NEXO_TEST_NOW_EPOCH"]),U) if os.environ.get("NEXO_TEST_NOW_EPOCH") else dt.datetime.now(U)
m=re.fullmatch(r"(\d\d):(\d\d)Z",s)
if m:
    h,mi=int(m[1]),int(m[2])
    if h>23 or mi>59: sys.exit(1)
    t=now.replace(hour=h,minute=mi,second=0,microsecond=0)
    if now-t>dt.timedelta(hours=12): t+=dt.timedelta(days=1)
else:
    m=re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)Z",s)
    if not m: sys.exit(1)
    try: t=dt.datetime(*map(int,m.groups()),tzinfo=U)
    except ValueError: sys.exit(1)
print(int(t.timestamp()))
PY
}
now_epoch() { echo "${NEXO_TEST_NOW_EPOCH:-$(date +%s)}"; }

review_plan() {   # $1 = plan guardado; $2 = escenario (first|resume, por defecto el de --scenario). La revisión es por RECURSO y por ATRIBUTO (scripts/v2-ops/review-plan.py); todo lo demás BLOQUEA
  local json out sc="${2:-$SCENARIO}"; json="$("$TF_BIN" -chdir="$TF_DIR" show -json "$1" 2>/dev/null)" || { log "BLOQUEO: no se pudo leer el plan"; return 1; }
  out="$(python3 "$ROOT/scripts/v2-ops/review-plan.py" "$sc" <<<"$json" 2>&1)"; local rc=$?
  log "$out"; return $rc
}

chain_run() {
  window_min
  [[ "$SCENARIO" == first || "$SCENARIO" == resume || "$SCENARIO" == t5b || "$SCENARIO" == t5c ]] || { echo "--scenario debe ser first (primer despliegue), resume (reanudación tras una limpieza verificada) o t5b/t5c (T5, 2.º intento; también exigen limpieza verificada)." >&2; exit 2; }
  EXPECTED_N="${NEXO_EXPECTED_TARGETS:-2}"; [[ "$EXPECTED_N" =~ ^[0-9]+$ && "$EXPECTED_N" -ge 2 && "$EXPECTED_N" -le 10 ]] || { echo "NEXO_EXPECTED_TARGETS debe ser un entero entre 2 y 10." >&2; exit 2; }
  [[ "$SCENARIO" == t5b && "$EXPECTED_N" != 3 || "$SCENARIO" == t5c && "$EXPECTED_N" != 6 ]] && { echo "El escenario $SCENARIO exige NEXO_EXPECTED_TARGETS=$([[ "$SCENARIO" == t5b ]] && echo 3 || echo 6) (coherente con el plan revisado)." >&2; exit 2; }
  [[ "${NEXO_ALLOW_CLOUD_CHANGES:-}" == YES && "$CONFIRM" == "ENCENDER RDS Y APLICAR V2" ]] || { echo "chain cambia AWS: exige NEXO_ALLOW_CLOUD_CHANGES=YES y --confirm \"ENCENDER RDS Y APLICAR V2\"" >&2; exit 2; }
  [[ -n "$NOTAFTER" && -n "$CREDS_UNTIL" ]] || { echo "chain exige --not-after (hora límite de inicio) y --creds-until (caducidad de credenciales), como HH:MMZ o YYYY-MM-DDTHH:MMZ" >&2; exit 2; }
  local na cu now; na="$(hhmm_epoch "$NOTAFTER")" || { echo "--not-after inválido (use HH:MMZ o YYYY-MM-DDTHH:MMZ, fecha y hora reales)" >&2; exit 2; }; cu="$(hhmm_epoch "$CREDS_UNTIL")" || { echo "--creds-until inválido (use HH:MMZ o YYYY-MM-DDTHH:MMZ, fecha y hora reales)" >&2; exit 2; }; now="$(now_epoch)"
  (( now <= na )) || { log "BLOQUEADO: la hora límite de inicio ($NOTAFTER) ya pasó; NO se reutiliza una ventana vencida."; exit 1; }
  (( cu > now )) || { log "BLOQUEADO: la caducidad de credenciales indicada ($CREDS_UNTIL) ya pasó."; exit 1; }
  (( cu - now <= ${NEXO_MAX_CREDS_AHEAD_MIN:-360}*60 )) || { log "BLOQUEADO: la caducidad indicada ($CREDS_UNTIL) está a más de ${NEXO_MAX_CREDS_AHEAD_MIN:-360} min: una sesión de Academy dura unas 4 h; revise la fecha (¿error de día?)."; exit 1; }
  (( now + MIN*60 + 45*60 <= cu )) || { log "BLOQUEADO: no hay margen (ventana ${MIN} min + 45 min) antes de la caducidad de credenciales ($CREDS_UNTIL)."; exit 1; }
  if [[ "$SCENARIO" != first ]]; then   # reanudar solo después de una limpieza verificada (el estado lo escribe stop-now o el watchdog)
    [[ -f "$STATE" ]] && grep -q "PARADA_VERIFICADA" "$STATE" || { log "BLOQUEADO: --scenario resume exige que la última limpieza conste como PARADA_VERIFICADA en $STATE; use --scenario first si es el primer despliegue."; exit 1; }
  fi
  ALSO_V2=1; PLAN_FILE="$PLAN_DIR/$(date -u +%Y%m%dT%H%M%SZ)-chain.tfplan"
  start_rds_window || exit 1
  deadline=$(( $(date +%s) + MIN*60 - 30 )); touch "$KEEP"            # latido mientras exista KEEP y NUNCA más allá de la hora límite de la ventana
  ( while [[ -e "$KEEP" && $(date +%s) -lt $deadline ]]; do touch "$BEAT"; sleep "${NEXO_KEEPALIVE_S:-60}"; done ) >/dev/null 2>&1 &
  log "B1 completo. Regenerando el plan de Terraform con el estado actual."
  mkdir -p "$PLAN_DIR"; chmod 700 "$PLAN_DIR"
  "$TF_BIN" -chdir="$TF_DIR" plan -input=false -lock=true -no-color -var-file="$COMMON" -var-file="$ON_VARS" -out="$PLAN_FILE" >"$PLAN_FILE.txt" 2>&1 || { log "ABORTO: terraform plan falló."; touch "$ABORT"; rm -f "$KEEP"; exit 1; }
  review_plan "$PLAN_FILE" || { log "ABORTO: el plan no es el esperado. NO se aplica nada; se apaga la RDS."; rm -f "$PLAN_FILE"; touch "$ABORT"; rm -f "$KEEP"; exit 1; }
  (( $(date +%s) + 45*60 <= deadline )) || { log "ABORTO: no queda tiempo para pruebas y reversión."; touch "$ABORT"; rm -f "$KEEP"; exit 1; }
  log "Aplicando EXCLUSIVAMENTE el plan guardado y revisado."
  "$TF_BIN" -chdir="$TF_DIR" apply -input=false -no-color "$PLAN_FILE" >"$PLAN_FILE.apply.txt" 2>&1 || { log "FALLO de terraform apply: no se fuerza nada; revise el estado real (terraform plan) y decida la reversión. El watchdog y el latido siguen activos."; exit 1; }
  log "APLICADO. Esperando 2 destinos sanos en 2 zonas."
  local tg ids zones t0; tg="$("$AWS" elbv2 describe-target-groups --names nexoeventos-academy-v2-tg --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null)"; t0=$(date +%s)
  while (( $(date +%s) - t0 < ${NEXO_HEALTHY_WAIT_S:-720} )); do
    ids="$("$AWS" elbv2 describe-target-health --target-group-arn "$tg" --query 'TargetHealthDescriptions[?TargetHealth.State==`healthy`].Target.Id' --output text 2>/dev/null | tr -s '[:space:]' ' ' | sed 's/ $//')"
    if [[ -n "$ids" ]]; then zones="$("$AWS" ec2 describe-instances --instance-ids $ids --query 'Reservations[].Instances[].Placement.AvailabilityZone' --output text 2>/dev/null | tr '\t' '\n' | sort -u | tr '\n' ' ')"
      [[ "$(wc -w <<<"$ids")" -ge "$EXPECTED_N" && "$zones" == *us-east-1a* && "$zones" == *us-east-1b* ]] && break; fi
    sleep "${NEXO_POLL:-15}"
  done
  [[ -n "${zones:-}" && "$zones" == *us-east-1a* && "$zones" == *us-east-1b* && "$(wc -w <<<"$ids")" -ge "$EXPECTED_N" ]] || { log "FALLO: no hay $EXPECTED_N destinos sanos en us-east-1a y us-east-1b (ids='${ids:-}'). No se fuerza nada: decida la reversión; el watchdog sigue activo."; exit 1; }
  log "DESTINOS SANOS: $(wc -w <<<"$ids" | tr -d ' ') en zonas: ${zones}"
  local dns ip c1 c2; dns="$("$AWS" elbv2 describe-load-balancers --names "$ALB_NAME" --query 'LoadBalancers[0].DNSName' --output text 2>/dev/null)"; ip="$(dig +short "$dns" 2>/dev/null | grep -E '^[0-9.]+$' | head -1)"
  c1="$(curl -s -o /dev/null -m 15 -w '%{http_code}' --resolve "$V2_DOMAIN:443:$ip" "https://$V2_DOMAIN/livez" 2>/dev/null || true)"; c2="$(curl -s -o /dev/null -m 15 -w '%{http_code}' --resolve "$V2_DOMAIN:443:$ip" "https://$V2_DOMAIN/api/events" 2>/dev/null || true)"
  log "HTTPS vía ALB: /livez=$c1  /api/events=$c2 (sin cambiar DNS: --resolve)"
  [[ "$c1" == 200 && "$c2" == 200 ]] && log "B2 COMPLETO: ALB con 2 destinos sanos, HTTPS y /livez OK. Latido activo hasta ~$(date -u -r "$deadline" +%H:%M:%SZ). Me detengo: B3 requiere autorización aparte." || log "B2 con resultado HTTPS no esperado (livez=$c1, events=$c2): revise antes de B3."
}

case "$CMD" in
  check) preflight && rc=0 || rc=1; armed && log "Watchdog: ARMADO (pid $(cat "$PIDF"))" || log "Watchdog: no armado"; exit $rc;;
  watchdog) run_watchdog;;
  beat) touch "$BEAT"; echo "latido actualizado";;
  cancel) touch "$STOP"; log "cancelación solicitada"; exit 0;;
  stop-now)
    [[ "${NEXO_ALLOW_CLOUD_CHANGES:-}" == YES ]] || { echo "stop-now cambia AWS: exige NEXO_ALLOW_CLOUD_CHANGES=YES" >&2; exit 2; }
    ident_ok || { log "BLOQUEO: identidad no válida"; exit 1; }
    [[ "$ALSO_V2" == 1 ]] && v2_down
    rds_stop_verified; exit $?;;
  start)
    window_min
    [[ "${NEXO_ALLOW_CLOUD_CHANGES:-}" == YES && "$CONFIRM" == "ENCENDER RDS" ]] || { echo "start cambia AWS: exige NEXO_ALLOW_CLOUD_CHANGES=YES y --confirm \"ENCENDER RDS\"" >&2; exit 2; }
    start_rds_window; exit $?;;
  chain) chain_run; exit $?;;
  abort) touch "$ABORT"; rm -f "$KEEP"; log "aborto solicitado: el watchdog apagará todo de inmediato"; exit 0;;
  *) echo "Uso: $0 check | watchdog --minutes N [--also-v2] | start --minutes N --confirm \"ENCENDER RDS\" | chain --minutes N [--scenario first|resume] --not-after HH:MMZ|AAAA-MM-DDTHH:MMZ --creds-until HH:MMZ|AAAA-MM-DDTHH:MMZ --confirm \"ENCENDER RDS Y APLICAR V2\" | beat | abort | cancel | stop-now" >&2; exit 2;;
esac
