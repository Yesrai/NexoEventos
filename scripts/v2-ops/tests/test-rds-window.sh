#!/usr/bin/env bash
# Pruebas de rds-window.sh con un AWS simulado: no toca AWS. Uso: bash scripts/v2-ops/tests/test-rds-window.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; SCRIPT="$HERE/../rds-window.sh"; fails=0
chmod +x "$HERE/fake-aws-rds.sh"
ACC="$(awk -F= '$1 ~ /expected_account_id/ {gsub(/[[:space:]"]/,"",$2);print $2;exit}' "$HERE/../../../work/terraform-envs/academy-v2-common.tfvars" 2>/dev/null)"; ACC="${ACC:-123456789012}"
ok() { echo "OK    $1"; }; ko() { echo "FALLÓ $1"; fails=$((fails+1)); }
setup() { T="$(mktemp -d)"; export FAKE_DIR="$T/f" NEXO_OPS_DIR="$T/ops" FAKE_ACCOUNT="$ACC" AWS_BIN="$HERE/fake-aws-rds.sh" NEXO_WATCHDOG_NO_NOTIFY=1 NEXO_POLL=0.2 NEXO_WATCHDOG_POLL=1 NEXO_WATCHDOG_RETRY_SLEEP=0.3
  mkdir -p "$FAKE_DIR" "$NEXO_OPS_DIR"; echo stopped >"$FAKE_DIR/rds"; printf '0\t0\t0\n' >"$FAKE_DIR/asg"; echo 0 >"$FAKE_DIR/ec2"; echo 0 >"$FAKE_DIR/alb"; : >"$FAKE_DIR/calls"; unset NEXO_ALLOW_CLOUD_CHANGES NEXO_WATCHDOG_TEST_SECONDS NEXO_WATCHDOG_STALE_MIN; }
called() { grep -q "$1" "$FAKE_DIR/calls"; }
wait_state() { for _ in $(seq 1 60); do [[ "$(cat "$FAKE_DIR/rds")" == "$1" ]] && return 0; sleep 0.2; done; return 1; }

setup; "$SCRIPT" start --minutes 5 >/dev/null 2>&1; rc=$?
[[ $rc -ne 0 ]] && ! called "start-db-instance" && ok "start sin NEXO_ALLOW_CLOUD_CHANGES ni confirmación: no enciende" || ko "start sin autorización"
setup; export NEXO_ALLOW_CLOUD_CHANGES=YES; "$SCRIPT" start --minutes 5 --confirm "otra frase" >/dev/null 2>&1; ! called "start-db-instance" && ok "frase de confirmación incorrecta: no enciende" || ko "frase"
setup; "$SCRIPT" start --minutes 121 --confirm "ENCENDER RDS" >/dev/null 2>&1; rc=$?; [[ $rc -ne 0 ]] && ! called "start-db-instance" && ok "ventana > 120 min rechazada" || ko "ventana"
for case_ in "asg:1\t2\t2" "ec2:1" "alb:1" "rds:available"; do
  setup; export NEXO_ALLOW_CLOUD_CHANGES=YES; k="${case_%%:*}"; v="${case_#*:}"; printf "$v\n" >"$FAKE_DIR/$k"
  "$SCRIPT" start --minutes 5 --confirm "ENCENDER RDS" >/dev/null 2>&1; rc=$?
  [[ $rc -ne 0 ]] && ! called "start-db-instance" && ! called "stop-db-instance" && ok "precondición incumplida ($k): bloquea sin cambiar nada" || ko "precondición $k"
done
setup; touch "$FAKE_DIR/expired"; export NEXO_ALLOW_CLOUD_CHANGES=YES; "$SCRIPT" start --minutes 5 --confirm "ENCENDER RDS" >/dev/null 2>&1; ! called "start-db-instance" && ok "credenciales caducadas: no enciende" || ko "credenciales"

# flujo completo: el watchdog se arma ANTES de encender y detiene al vencer
setup; export NEXO_ALLOW_CLOUD_CHANGES=YES NEXO_WATCHDOG_TEST_SECONDS=4
"$SCRIPT" start --minutes 5 --confirm "ENCENDER RDS" >"$T/out" 2>&1; rc=$?
[[ $rc -eq 0 && "$(cat "$FAKE_DIR/rds")" == available ]] && ok "start: RDS available y termina (no hace nada más)" || ko "start completo ($(cat "$FAKE_DIR/rds"), rc=$rc)"
grep -n "Watchdog verificado" "$NEXO_OPS_DIR/rds-window.log" >/dev/null && ok "watchdog verificado antes de encender" || ko "watchdog no verificado"
a=$(grep -n "WATCHDOG ARMADO" "$NEXO_OPS_DIR/rds-window.log" | head -1 | cut -d: -f1); b=$(grep -n "Encendiendo" "$NEXO_OPS_DIR/rds-window.log" | head -1 | cut -d: -f1); [[ -n "$a" && -n "$b" && "$a" -lt "$b" ]] && ok "orden: armado < encendido" || ko "orden"
wait_state stopped && ok "VENCE LA VENTANA: el watchdog detiene la RDS y verifica stopped" || ko "no detuvo al vencer"
! called "terminate\|delete\|update-auto-scaling\|put-secret\|modify" && ok "solo se llamó a start/stop de la RDS (ninguna otra mutación)" || ko "llamada inesperada"

# latido viejo = prueba interrumpida
setup; export NEXO_ALLOW_CLOUD_CHANGES=YES NEXO_WATCHDOG_TEST_SECONDS=300 NEXO_WATCHDOG_STALE_MIN=0
echo available >"$FAKE_DIR/rds"; ( "$SCRIPT" watchdog --minutes 5 >/dev/null 2>&1 & ); sleep 3; wait_state stopped && ok "latido viejo (prueba interrumpida): detiene la RDS antes de vencer" || ko "latido"
# cancelación
setup; export NEXO_WATCHDOG_TEST_SECONDS=300; echo available >"$FAKE_DIR/rds"; ( "$SCRIPT" watchdog --minutes 5 >/dev/null 2>&1 & ); sleep 2; "$SCRIPT" cancel >/dev/null; sleep 2.5
[[ "$(cat "$FAKE_DIR/rds")" == available ]] && ! called "stop-db-instance" && ok "cancel: el watchdog sale sin detener la RDS" || ko "cancel"
# reintento: la RDS en transición no se detiene hasta available
setup; export NEXO_WATCHDOG_TEST_SECONDS=1 NEXO_STOP_POLL_S=0.3; echo starting >"$FAKE_DIR/rds"; echo 0 >"$FAKE_DIR/polls"; ( "$SCRIPT" watchdog --minutes 5 >/dev/null 2>&1 & ); wait_state stopped && ok "RDS en 'starting' al vencer: espera a available y luego la detiene" || ko "transición"
# credenciales caducadas durante la vigilancia: alerta fuerte
setup; export NEXO_WATCHDOG_TEST_SECONDS=300; echo available >"$FAKE_DIR/rds"; touch "$FAKE_DIR/expired"; ( "$SCRIPT" watchdog --minutes 5 >/dev/null 2>&1 & ); sleep 2.5; "$SCRIPT" cancel >/dev/null; sleep 2; grep -q "ALERTA: credenciales" "$NEXO_OPS_DIR/rds-window.log" && ok "credenciales caducadas durante la ventana: alerta" || ko "alerta credenciales"

# ───────────── parada Multi-AZ: una parada que AVANZA no es un fallo; una que no termina es PARADA_INCOMPLETA ─────────────
# (escala de tiempo: 1 minuto simulado = 1 s; plazo total 24 «min» = 24 s)
slog() { sed 's/^[^ ]* //' "$NEXO_OPS_DIR/rds-window.log"; }
for secs in 5 15; do
  setup; export NEXO_WATCHDOG_TEST_SECONDS=1 NEXO_STOP_DEADLINE_S=24 NEXO_STOP_POLL_S=0.4 FAKE_STOP_SECS=$secs; echo available >"$FAKE_DIR/rds"
  "$SCRIPT" watchdog --minutes 5 >/dev/null 2>&1; rc=$?; unset FAKE_STOP_SECS
  st="$(cut -d' ' -f2 "$NEXO_OPS_DIR/rds-window.state")"
  [[ $rc -eq 0 && "$st" == PARADA_VERIFICADA && "$(cat "$FAKE_DIR/rds")" == stopped ]] && ! grep -qE "FALLO|PARADA_INCOMPLETA" "$NEXO_OPS_DIR/rds-window.log" && ok "parada Multi-AZ de ${secs} «min» en 'stopping': sin falsa alarma (PARADA_VERIFICADA)" || ko "parada de $secs ($st rc=$rc)"
done
grep -q "Parada AVANZANDO" "$NEXO_OPS_DIR/rds-window.log" && ok "registra que la parada AVANZA (no es un fallo)" || ko "sin mensaje de avance"
grep -q "más de la mitad del plazo" "$NEXO_OPS_DIR/rds-window.log" && ok "alerta intermedia al pasar la mitad del plazo (parada de 15 de 24)" || ko "alerta intermedia"
setup; export NEXO_WATCHDOG_TEST_SECONDS=1 NEXO_STOP_DEADLINE_S=4 NEXO_STOP_POLL_S=0.3 FAKE_STOP_NEVER=1; echo available >"$FAKE_DIR/rds"
"$SCRIPT" watchdog --minutes 5 >/dev/null 2>&1; rc=$?; unset FAKE_STOP_NEVER
[[ $rc -eq 2 && "$(cut -d' ' -f2 "$NEXO_OPS_DIR/rds-window.state")" == PARADA_INCOMPLETA ]] && grep -q "PARADA_INCOMPLETA" "$NEXO_OPS_DIR/rds-window.log" && ok "parada que NO termina en el plazo total: PARADA_INCOMPLETA, salida 2 y orden de intervención" || ko "PARADA_INCOMPLETA"
setup; export NEXO_WATCHDOG_TEST_SECONDS=1 NEXO_STOP_DEADLINE_S=4 NEXO_STOP_POLL_S=0.3 NEXO_STOP_RETRY_S=1; echo available >"$FAKE_DIR/rds"; touch "$FAKE_DIR/stop_err"
"$SCRIPT" watchdog --minutes 5 >/dev/null 2>&1; rc=$?; n=$(grep -c "stop-db-instance" "$FAKE_DIR/calls")
[[ $rc -eq 2 && $n -ge 3 && "$(cut -d' ' -f2 "$NEXO_OPS_DIR/rds-window.state")" == PARADA_INCOMPLETA ]] && ok "stop-db-instance que falla siempre: reintenta ($n veces) y termina en PARADA_INCOMPLETA" || ko "reintentos ($n, rc=$rc)"
setup; export NEXO_WATCHDOG_TEST_SECONDS=1 NEXO_STOP_DEADLINE_S=20 NEXO_STOP_POLL_S=0.4 NEXO_STOP_RETRY_S=1; echo available >"$FAKE_DIR/rds"; touch "$FAKE_DIR/expired"
( sleep 2.5; rm -f "$FAKE_DIR/expired" ) & "$SCRIPT" watchdog --minutes 5 >/dev/null 2>&1; rc=$?
[[ $rc -eq 0 && "$(cat "$FAKE_DIR/rds")" == stopped ]] && grep -q "ALERTA: credenciales caducadas" "$NEXO_OPS_DIR/rds-window.log" && ok "credenciales caducadas durante la parada: alerta y la completa al renovarse" || ko "credenciales durante la parada"
unset NEXO_STOP_DEADLINE_S NEXO_STOP_POLL_S NEXO_STOP_RETRY_S

# ───────────── --also-v2: ASG a 0 y ALB eliminado ANTES de apagar la RDS; aborto inmediato ─────────────
setup; export NEXO_WATCHDOG_TEST_SECONDS=1 NEXO_STOP_POLL_S=0.3 NEXO_V2_DOWN_S=3; echo available >"$FAKE_DIR/rds"; printf '2\t2\t2\n' >"$FAKE_DIR/asg"; echo 2 >"$FAKE_DIR/ec2"; echo 1 >"$FAKE_DIR/alb"
"$SCRIPT" watchdog --minutes 5 --also-v2 >/dev/null 2>&1; rc=$?
a=$(grep -n "update-auto-scaling-group" "$FAKE_DIR/calls" | head -1 | cut -d: -f1); b=$(grep -n "delete-load-balancer" "$FAKE_DIR/calls" | head -1 | cut -d: -f1); c=$(grep -n "stop-db-instance" "$FAKE_DIR/calls" | head -1 | cut -d: -f1)
[[ $rc -eq 0 && -n "$a" && -n "$b" && -n "$c" && $a -lt $b && $b -lt $c && "$(cat "$FAKE_DIR/alb")" == 0 && "$(cat "$FAKE_DIR/rds")" == stopped ]] && ok "--also-v2: ASG a 0 → ALB eliminado → RDS detenida (apagar la RDS sola NO basta)" || ko "also-v2 (a=$a b=$b c=$c)"
# un ALB con el mismo nombre pero SIN las etiquetas del proyecto NO se elimina (la limpieza de emergencia solo toca recursos identificados de NexoEventos)
setup; export NEXO_WATCHDOG_TEST_SECONDS=1 NEXO_STOP_POLL_S=0.3 NEXO_V2_DOWN_S=2; echo available >"$FAKE_DIR/rds"; echo 1 >"$FAKE_DIR/alb"; touch "$FAKE_DIR/notags"; "$SCRIPT" watchdog --minutes 5 --also-v2 >/dev/null 2>&1
! grep -q "delete-load-balancer" "$FAKE_DIR/calls" && grep -q "NO tiene las etiquetas" "$NEXO_OPS_DIR/rds-window.log" && [[ "$(cat "$FAKE_DIR/rds")" == stopped ]] && ok "ALB sin etiquetas de NexoEventos: NO se elimina (la RDS sí se detiene)" || ko "ALB sin etiquetas"
grep -q "describe-tags" "$FAKE_DIR/calls" && ok "antes de eliminar el ALB se verifican sus etiquetas Project/Stack" || ko "no verifica etiquetas"
setup; unset NEXO_STOP_POLL_S NEXO_V2_DOWN_S; export NEXO_WATCHDOG_TEST_SECONDS=300; echo available >"$FAKE_DIR/rds"; ( "$SCRIPT" watchdog --minutes 5 >/dev/null 2>&1 & ); sleep 2; "$SCRIPT" abort >/dev/null; wait_state stopped && ok "abort: apagado inmediato sin esperar la hora límite" || ko "abort"

# ───────────── chain: B1 + B2 en una ventana con revisión estricta del plan ─────────────
mkplans() { python3 - "$1" <<'PY'
import json,sys,copy
d=sys.argv[1]
ALB_ALARMS=["aws_cloudwatch_metric_alarm.alb_healthy_below_desired[0]","aws_cloudwatch_metric_alarm.alb_latency_p95[0]","aws_cloudwatch_metric_alarm.alb_target_5xx[0]","aws_cloudwatch_metric_alarm.alb_unhealthy_hosts[0]"]
creates=["aws_lb.main","aws_lb_listener.http_redirect","aws_lb_listener.https","aws_cloudwatch_dashboard.v2"]+ALB_ALARMS
def c(a,act,b=None,af=None,unk=None): return {"address":a,"change":{"actions":act,"before":b,"after":af if af is not None else {},"after_unknown":unk or {}}}
LBA={"name":"nexoeventos-academy-v2-alb","internal":False,"load_balancer_type":"application","drop_invalid_header_fields":True}
HTTPA={"port":80,"protocol":"HTTP","default_action":[{"type":"redirect","redirect":[{"port":"443","protocol":"HTTPS","status_code":"HTTP_301"}]}]}
HTTPSA={"port":443,"protocol":"HTTPS","ssl_policy":"ELBSecurityPolicy-TLS13-1-2-2021-06","default_action":[{"type":"forward","redirect":[]}]}
ATTRS={"aws_lb.main":LBA,"aws_lb_listener.http_redirect":HTTPA,"aws_lb_listener.https":HTTPSA}
cr=lambda a:c(a,["create"],None,ATTRS.get(a,{}))
asg=lambda mn,ds,mx=3: c("aws_autoscaling_group.web",["update"],{"min_size":0,"desired_capacity":0,"max_size":3,"name":"x"},{"min_size":mn,"desired_capacity":ds,"max_size":mx,"name":"x"})
base=[cr(a) for a in creates]+[asg(2,2)]
noop=[c("aws_lb_target_group.web",["no-op"],{},{}),c("data.aws_vpc.v1",["read"],{},{})]
plans={"good":base+noop,
 "destroy":base+[c("aws_db_instance.rds",["delete"],{"id":"x"},None)],
 "replace":[x for x in base if x["address"]!="aws_autoscaling_group.web"]+[c("aws_autoscaling_group.web",["delete","create"],{"min_size":0,"desired_capacity":0},{"min_size":2,"desired_capacity":2})],
 "extra":base+[c("aws_iam_role.x",["create"])],
 "wrongasg":[x for x in base if x["address"]!="aws_autoscaling_group.web"]+[asg(2,3)],
 "missing":base[:7]+[asg(2,2)],
 "asgmax":[x for x in base if x["address"]!="aws_autoscaling_group.web"]+[asg(2,2,5)],
 "secret":base+[c("aws_secretsmanager_secret.s",["update"],{"a":1},{"a":2})],
 "lbinternal":[c("aws_lb.main",["create"],None,dict(LBA,internal=True)) if x["address"]=="aws_lb.main" else x for x in base],
 "weaktls":[c("aws_lb_listener.https",["create"],None,dict(HTTPSA,ssl_policy="ELBSecurityPolicy-2016-08")) if x["address"]=="aws_lb_listener.https" else x for x in base]}
# ---- REANUDACIÓN tras una limpieza verificada: ALB y listeners recreados; panel y alarmas actualizados SOLO en lo que depende del ALB ----
def upd(a,before,after,unk): return c(a,["update"],before,after,unk)
dash=upd("aws_cloudwatch_dashboard.v2",{"dashboard_name":"n","dashboard_body":"old"},{"dashboard_name":"n"},{"dashboard_body":True})
al_dim=lambda a: upd(a,{"threshold":5,"alarm_actions":["t"],"dimensions":{"LoadBalancer":"old"}},{"threshold":5,"alarm_actions":["t"]},{"dimensions":True,"alarm_actions":[False]})
al_mq=upd(ALB_ALARMS[0],{"threshold":1,"metric_query":[{"id":"a","expression":"x"}]},{"threshold":1,"metric_query":[{"id":"a","expression":"y"}]},{})
rbase=[cr("aws_lb.main"),cr("aws_lb_listener.http_redirect"),cr("aws_lb_listener.https"),asg(2,2),dash,al_mq]+[al_dim(a) for a in ALB_ALARMS[1:]]
def swap(lst,addr,new): return [new if x["address"]==addr else x for x in lst]
plans.update({"r_good":rbase+noop,
 "r_destroy_rds":rbase+[c("aws_db_instance.postgres",["delete"],{"id":"x"},None)],
 "r_update_rds":rbase+[upd("aws_db_instance.postgres",{"multi_az":True},{"multi_az":False},{})],
 "r_replace_lb":swap(rbase,"aws_lb.main",c("aws_lb.main",["delete","create"],{"name":"x"},LBA)),
 "r_iam":rbase+[upd("aws_iam_role_policy.p",{"a":1},{"a":2},{})],
 "r_secret":rbase+[upd("aws_secretsmanager_secret.s",{"a":1},{"a":2},{})],
 "r_dns":rbase+[c("aws_route53_record.r",["create"],None,{})],
 "r_net":rbase+[upd("aws_security_group.alb",{"x":1},{"x":2},{})],
 "r_alarm_attr":swap(rbase,ALB_ALARMS[2],upd(ALB_ALARMS[2],{"threshold":5,"dimensions":{"a":"b"}},{"threshold":99},{"dimensions":True})),
 "r_alarm_actions":swap(rbase,ALB_ALARMS[1],upd(ALB_ALARMS[1],{"alarm_actions":["t"],"dimensions":{"a":"b"}},{"alarm_actions":["otro"]},{"dimensions":True})),
 "r_dash_attr":swap(rbase,"aws_cloudwatch_dashboard.v2",upd("aws_cloudwatch_dashboard.v2",{"dashboard_name":"n","dashboard_body":"old"},{"dashboard_name":"otro"},{"dashboard_body":True})),
 "r_asg_max":swap(rbase,"aws_autoscaling_group.web",asg(2,2,5)),
 "r_asg_03":swap(rbase,"aws_autoscaling_group.web",asg(3,3)),
 "r_missing_listener":[x for x in rbase if x["address"]!="aws_lb_listener.https"],
 "r_missing_update":[x for x in rbase if x["address"]!=ALB_ALARMS[3]],
 "r_tg_create":rbase+[c("aws_lb_target_group.web",["create"],None,{})],
 "r_extra_alarm":rbase+[c("aws_cloudwatch_metric_alarm.nueva",["create"],None,{})],
 "r_lb_internal":swap(rbase,"aws_lb.main",c("aws_lb.main",["create"],None,dict(LBA,internal=True)))})
for k,v in plans.items(): json.dump({"errored":False,"resource_changes":v},open(f"{d}/plan-{k}.json","w"))
PY
}
chain_setup() { setup; mkplans "$T"; mkdir -p "$T/tf" "$T/bin"; : >"$T/on.tfvars"; printf '#!/bin/bash\necho 200\n' >"$T/bin/curl"; printf '#!/bin/bash\necho 10.1.2.3\n' >"$T/bin/dig"; chmod +x "$T/bin/"*
  export PATH="$T/bin:$PATH" TF_BIN="$HERE/fake-terraform-chain.sh" V2_TF_DIR="$T/tf" V2_PLAN_DIR="$T/plans" V2_ON_VARS="$T/on.tfvars" NEXO_ALLOW_CLOUD_CHANGES=YES NEXO_WATCHDOG_TEST_SECONDS=120 NEXO_KEEPALIVE_S=1 NEXO_HEALTHY_WAIT_S=6 NEXO_STOP_POLL_S=0.3 NEXO_V2_DOWN_S=3 FAKE_PLAN_JSON="$T/plan-${1:-good}.json"
  NA="$(date -u -v+40M +%H:%MZ)"; CU="$(date -u -v+5H +%H:%MZ)"; }
chain() { "$SCRIPT" chain ${SCEN:+--scenario $SCEN} --minutes 90 --not-after "${1:-$NA}" --creds-until "${2:-$CU}" --confirm "${3:-ENCENDER RDS Y APLICAR V2}" >"$T/chain.out" 2>&1; echo $?; }
chain_end() { rm -f "$NEXO_OPS_DIR/rds-window.keepalive"; "$SCRIPT" cancel >/dev/null 2>&1; sleep 1.5; }

chain_setup good; rc=$(chain); applied=$(grep -c "^apply" "$FAKE_DIR/applied" 2>/dev/null || echo 0); chain_end
[[ $rc -eq 0 && "$applied" == 1 ]] && grep -q "apply $T/plans/.*-chain.tfplan\$" "$FAKE_DIR/applied" && ok "chain con plan correcto: aplica UNA vez y SOLO el plan guardado regenerado" || ko "chain bueno (rc=$rc, applied=$applied)"
sed 's/^[^ ]* //' "$NEXO_OPS_DIR/rds-window.log" | grep -q "PLAN REVISADO: exactamente 8 creaciones" && ok "revisión obligatoria: 8 creaciones permitidas + 1 modificación del ASG (0→2)" || ko "revisión"
grep -q "DESTINOS SANOS: 2 en zonas: us-east-1a us-east-1b" "$NEXO_OPS_DIR/rds-window.log" && grep -q "B2 COMPLETO" "$NEXO_OPS_DIR/rds-window.log" && grep -q "/livez=200" "$NEXO_OPS_DIR/rds-window.log" && ok "espera 2 destinos sanos en 2 zonas y comprueba HTTPS y /livez; se detiene tras B2" || ko "salud/HTTPS"
a=$(grep -n "start-db-instance" "$FAKE_DIR/calls" | head -1 | cut -d: -f1); [[ -n "$a" ]] && ! grep -qE "stop-db-instance|update-auto-scaling|delete-load-balancer" "$FAKE_DIR/calls" && ok "durante B1+B2 no se apagó nada (el watchdog sigue armado hasta la hora límite)" || ko "llamadas inesperadas"
for bad in destroy replace extra wrongasg missing asgmax secret; do
  chain_setup $bad; rc=$(chain); n=$(grep -c "^apply" "$FAKE_DIR/applied" 2>/dev/null || true); sleep 3; chain_end
  [[ $rc -ne 0 && -z "$n$(ls "$FAKE_DIR/applied" 2>/dev/null)" || ( $rc -ne 0 && ! -e "$FAKE_DIR/applied" ) ]] && [[ "$(cat "$FAKE_DIR/rds")" == stopped ]] && grep -q "BLOQUEO\|ABORTO" "$NEXO_OPS_DIR/rds-window.log" && ok "plan '$bad': ABORTA sin aplicar y apaga la RDS" || ko "plan $bad (rc=$rc, applied=$(ls "$FAKE_DIR/applied" 2>/dev/null))"
done
chain_setup good; rc=$(chain "$(date -u -v-5M +%H:%MZ)"); [[ $rc -ne 0 ]] && ! called "start-db-instance" && ok "hora límite de inicio vencida: NO se reutiliza la ventana ni se enciende nada" || ko "ventana vencida"
chain_setup good; rc=$(chain "$NA" "$(date -u -v+60M +%H:%MZ)"); [[ $rc -ne 0 ]] && ! called "start-db-instance" && ok "sin margen frente a la caducidad de credenciales: no enciende" || ko "margen de credenciales"
chain_setup good; rc=$(chain "$NA" "$CU" "ENCENDER RDS"); [[ $rc -ne 0 ]] && ! called "start-db-instance" && ok "frase de confirmación distinta: no enciende" || ko "frase chain"
chain_setup good; export FAKE_APPLY_FAIL=1; rc=$(chain); n=$(grep -c "^apply" "$FAKE_DIR/applied"); chain_end; unset FAKE_APPLY_FAIL
[[ $rc -ne 0 && "$n" == 1 ]] && grep -q "FALLO de terraform apply: no se fuerza nada" "$NEXO_OPS_DIR/rds-window.log" && ok "apply que falla: no reintenta ni fuerza nada; informa" || ko "apply fallido"
# ───────────── REANUDACIÓN tras una limpieza verificada: revisión por recurso y por atributo; primer despliegue sigue igual ─────────────
resume_setup() { chain_setup "$1"; echo "2026-11-20T23:37:58Z PARADA_VERIFICADA 401s" >"$NEXO_OPS_DIR/rds-window.state"; }
bad_plan_blocked() {   # $1 = plan; $2 = escenario; $3 = texto de la prueba. Debe abortar SIN aplicar nada y con la RDS detenida de nuevo
  if [[ "$2" == resume ]]; then resume_setup "$1"; else chain_setup "$1"; fi
  rc=$(SCEN="$2" chain); sleep 3; chain_end
  [[ $rc -ne 0 && ! -e "$FAKE_DIR/applied" ]] && [[ "$(cat "$FAKE_DIR/rds")" == stopped ]] && grep -q "BLOQUEO\|ABORTO" "$NEXO_OPS_DIR/rds-window.log" && ok "$3" || ko "$3 (rc=$rc, rds=$(cat "$FAKE_DIR/rds"))"
}
resume_setup r_good; rc=$(SCEN=resume chain); applied=$(grep -c "^apply" "$FAKE_DIR/applied" 2>/dev/null || echo 0); chain_end
[[ $rc -eq 0 && "$applied" == 1 ]] && grep -q "PLAN REVISADO (reanudación)" "$NEXO_OPS_DIR/rds-window.log" && grep -q "B2 COMPLETO" "$NEXO_OPS_DIR/rds-window.log" && ok "reanudación con el plan correcto (3 creaciones + ASG 0→2 + 5 actualizaciones de monitoreo): aplica UNA vez, solo el plan guardado" || ko "reanudación buena (rc=$rc, applied=$applied)"
chain_setup good; rc=$(chain); chain_end; [[ $rc -eq 0 ]] && ok "primer despliegue (--scenario por defecto = first) sigue aceptando su plan de 8 creaciones" || ko "primer despliegue"
bad_plan_blocked good resume "reanudación con el plan de PRIMER despliegue (8 creaciones): bloquea"
bad_plan_blocked r_good first "primer despliegue con el plan de REANUDACIÓN (3 creaciones + 5 actualizaciones): bloquea"
bad_plan_blocked r_destroy_rds resume "reanudación: destrucción de la RDS: aborta sin aplicar"
bad_plan_blocked r_update_rds resume "reanudación: modificación MENOR de la RDS (multi_az): aborta sin aplicar"
bad_plan_blocked r_replace_lb resume "reanudación: sustitución del ALB (delete+create): aborta sin aplicar"
bad_plan_blocked r_iam resume "reanudación: cambio de IAM: aborta sin aplicar"
bad_plan_blocked r_secret resume "reanudación: cambio de un secreto: aborta sin aplicar"
bad_plan_blocked r_dns resume "reanudación: creación de un registro DNS: aborta sin aplicar"
bad_plan_blocked r_net resume "reanudación: cambio de un grupo de seguridad (redes): aborta sin aplicar"
bad_plan_blocked r_alarm_attr resume "reanudación: una alarma cambia de umbral (atributo no permitido): aborta"
bad_plan_blocked r_alarm_actions resume "reanudación: una alarma cambia sus acciones de notificación: aborta"
bad_plan_blocked r_dash_attr resume "reanudación: el panel cambia de nombre (solo se admite dashboard_body): aborta"
bad_plan_blocked r_asg_max resume "reanudación: el ASG cambia su máximo: aborta"
bad_plan_blocked r_asg_03 resume "reanudación: el ASG sube a 3 en vez de 2: aborta"
bad_plan_blocked r_missing_listener resume "reanudación: falta un listener (plan distinto del esperado): aborta"
bad_plan_blocked r_missing_update resume "reanudación: falta una de las 5 actualizaciones de monitoreo: aborta"
bad_plan_blocked r_tg_create resume "reanudación: recurso residual inesperado ausente (se recrearía el grupo de destino): aborta"
bad_plan_blocked r_extra_alarm resume "reanudación: alarma nueva no prevista: aborta"
bad_plan_blocked r_lb_internal resume "reanudación: ALB interno en vez de público: aborta"
bad_plan_blocked lbinternal first "primer despliegue: ALB interno en vez de público: aborta"
bad_plan_blocked weaktls first "primer despliegue: política TLS débil en el listener HTTPS: aborta"
# precondiciones de la reanudación
resume_setup r_good; rm -f "$NEXO_OPS_DIR/rds-window.state"; rc=$(SCEN=resume chain); chain_end
[[ $rc -ne 0 ]] && ! called "start-db-instance" && grep -q "PARADA_VERIFICADA" "$NEXO_OPS_DIR/rds-window.log" && ok "reanudación sin una limpieza verificada previa: no enciende nada" || ko "reanudación sin limpieza"
resume_setup r_good; echo "2026-11-20T23:37:58Z PARADA_INCOMPLETA 1800s" >"$NEXO_OPS_DIR/rds-window.state"; rc=$(SCEN=resume chain); chain_end
[[ $rc -ne 0 ]] && ! called "start-db-instance" && ok "reanudación tras una parada INCOMPLETA: no enciende nada" || ko "parada incompleta"
resume_setup r_good; rc=$(SCEN=otro chain); [[ $rc -eq 2 ]] && ! called "start-db-instance" && ok "--scenario inválido: se rechaza sin encender nada" || ko "escenario inválido"
for res in "alb:1" "ec2:2" "asg:2\t2\t2" "rds:available"; do   # recursos residuales inesperados: el preflight bloquea antes de encender
  resume_setup r_good; k="${res%%:*}"; v="${res#*:}"; printf "$v\n" >"$FAKE_DIR/$k"; rc=$(SCEN=resume chain); chain_end
  [[ $rc -ne 0 ]] && ! called "start-db-instance" && ok "reanudación con residuo inesperado ($k=$v): bloquea sin encender nada" || ko "residuo $k"
done
unset SCEN

# ───────────── horas UTC: fechas completas, cruce de medianoche, caducidad de credenciales y margen de seguridad ─────────────
ep() { date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$1" +%s; }    # UTC → epoch (macOS)
eval "$(sed -n '/^hhmm_epoch()/,/^}/p' "$SCRIPT")"
chk() { [[ "$(NEXO_TEST_NOW_EPOCH="$(ep "$1")" hhmm_epoch "$2" 2>/dev/null)" == "$(ep "$3")" ]]; }
chk 2026-11-20T21:48:00Z 2026-11-21T01:30Z 2026-11-21T01:30:00Z && ok "fecha completa UTC (2026-11-21T01:30Z) se acepta tal cual" || ko "fecha completa"
chk 2026-11-20T21:48:00Z 01:30Z 2026-11-21T01:30:00Z && ok "HH:MMZ que ya pasó hace > 12 h (21:48Z → 01:30Z) es de MAÑANA (cruce de medianoche)" || ko "cruce de medianoche"
chk 2026-11-20T21:48:00Z 22:30Z 2026-11-20T22:30:00Z && ok "HH:MMZ futura del mismo día se queda en hoy" || ko "mismo día"
chk 2026-11-20T21:48:00Z 21:00Z 2026-11-20T21:00:00Z && ok "HH:MMZ que pasó hace < 12 h se queda en el pasado (se rechaza como vencida)" || ko "hora vencida"
chk 2026-11-21T00:10:00Z 01:30Z 2026-11-21T01:30:00Z && ok "pasada la medianoche, 01:30Z es de hoy (no salta a mañana)" || ko "tras medianoche"
chk 2026-11-20T23:50:00Z 00:20Z 2026-11-21T00:20:00Z && ok "a las 23:50Z, 00:20Z es de mañana" || ko "00:20Z"
inval=0; for bad in 2026-02-30T01:30Z 2026-13-01T01:30Z 25:00Z 01:60Z "2026-11-21 01:30" 01:30 "" 2026-11-21T01:30; do NEXO_TEST_NOW_EPOCH="$(ep 2026-11-20T21:48:00Z)" hhmm_epoch "$bad" >/dev/null 2>&1 && { inval=1; echo "   aceptó: '$bad'"; }; done
[[ $inval == 0 ]] && ok "fechas/horas inválidas rechazadas (30-feb, mes 13, 25:00, minuto 60, sin Z, sin hora)" || ko "inválidas"
NOW_T=2026-11-20T21:48:00Z
chain_t() { NEXO_TEST_NOW_EPOCH="$(ep $NOW_T)" chain "$@"; }
chain_setup good; rc=$(chain_t 22:30Z 01:30Z); chain_end
[[ $rc -eq 0 ]] && grep -q "start-db-instance" "$FAKE_DIR/calls" && ok "chain con caducidad 01:30Z del día siguiente (ahora 21:48Z): ARRANCA (antes lo bloqueaba por leerla como pasada)" || ko "chain cruce de medianoche (rc=$rc)"
chain_setup good; rc=$(chain_t 22:30Z 2026-11-21T01:30Z); chain_end
[[ $rc -eq 0 ]] && ok "chain con fecha completa 2026-11-21T01:30Z: arranca" || ko "chain fecha completa"
chain_setup good; rc=$(chain_t 22:30Z 23:59Z); ! called "start-db-instance" && [[ $rc -ne 0 ]] && grep -q "no hay margen" "$NEXO_OPS_DIR/rds-window.log" && ok "caducidad 23:59Z (21:48Z + 90 + 45 min > 23:59Z): sin margen, no enciende" || ko "margen 23:59Z"
chain_setup good; rc=$(chain_t 22:30Z 21:00Z); ! called "start-db-instance" && [[ $rc -ne 0 ]] && grep -q "ya pasó" "$NEXO_OPS_DIR/rds-window.log" && ok "caducidad ya vencida (21:00Z): no enciende" || ko "caducidad vencida"
chain_setup good; rc=$(chain_t 22:30Z 2026-11-25T01:30Z); ! called "start-db-instance" && [[ $rc -ne 0 ]] && grep -q "más de 360 min" "$NEXO_OPS_DIR/rds-window.log" && ok "caducidad a días vista (error de fecha): no enciende" || ko "caducidad lejana"
chain_setup good; rc=$(chain_t 22:30Z 2026-02-30T01:30Z); ! called "start-db-instance" && [[ $rc -eq 2 ]] && ok "fecha inexistente (30-feb): se rechaza sin encender nada" || ko "fecha inexistente"
chain_setup good; rc=$(chain_t 22:30Z 2026-11-21T00:02:00Z); ! called "start-db-instance" && [[ $rc -ne 0 ]] && ok "margen: caducidad 1 min antes de ahora+135 min: no enciende" || ko "margen -1 min"
chain_setup good; rc=$(chain_t 22:30Z 2026-11-21T00:03Z); chain_end; [[ $rc -eq 0 ]] && ok "margen: caducidad exactamente ahora+135 min (90 + 45): enciende" || ko "margen exacto (rc=$rc)"
NOW_T=2026-11-20T23:50:00Z
chain_setup good; rc=$(chain_t 00:20Z 2026-11-21T02:30Z); chain_end; [[ $rc -eq 0 ]] && ok "hora límite de inicio 00:20Z a las 23:50Z (cruza la medianoche): vigente" || ko "not-after cruzado"
chain_setup good; rc=$(chain_t 23:40Z 2026-11-21T02:30Z); ! called "start-db-instance" && [[ $rc -ne 0 ]] && ok "hora límite de inicio 23:40Z a las 23:50Z: vencida, no enciende" || ko "not-after vencido"
unset NOW_T
unset NEXO_ALLOW_CLOUD_CHANGES NEXO_KEEPALIVE_S NEXO_HEALTHY_WAIT_S TF_BIN V2_TF_DIR V2_PLAN_DIR V2_ON_VARS FAKE_PLAN_JSON
pkill -f "rds-window.sh watchdog" 2>/dev/null
(( fails == 0 )) && { echo "TODAS LAS PRUEBAS OK"; exit 0; } || { echo "$fails FALLOS"; exit 1; }
