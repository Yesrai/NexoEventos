#!/usr/bin/env bash
# Funciones comunes de los scripts de operación de AWS V2 (v2-status, v2-up, v2-down).
# Principios: perfil y región fijos; recursos identificados por etiqueta/nombre (nunca por IP ni ID fijo);
# la ÚNICA llamada que cambia recursos es `autoscaling update-auto-scaling-group` sobre el ASG de V2.
set -euo pipefail

export AWS_PROFILE="nexoeventos-lab" AWS_REGION="us-east-1" AWS_DEFAULT_REGION="us-east-1" AWS_PAGER=""
AWS_BIN="${AWS_BIN:-aws}"                       # solo se cambia en las pruebas con un aws simulado
V2_PROJECT="${V2_PROJECT:-nexoeventos}"
V2_ENV="${V2_ENV:-academy}"
V2_ASG_TAG_NAME="${V2_PROJECT}-${V2_ENV}-v2-app"   # etiqueta Name que Terraform propaga desde el ASG
V2_RDS_ID="${V2_RDS_ID:-${V2_PROJECT}-${V2_ENV}-postgres}"
V1_EC2_NAME="${V2_PROJECT}-${V2_ENV}-app"
V2_DOMAIN="${V2_DOMAIN:-nexoeventos-demo.duckdns.org}"
POLL_INTERVAL="${POLL_INTERVAL:-15}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "• $*"; }
ok()   { echo "OK: $*"; }
awsx() { "$AWS_BIN" "$@" --output json; }

need_tools() {
  command -v jq >/dev/null || die "Falta jq (brew install jq)."
  command -v "$AWS_BIN" >/dev/null || die "Falta AWS CLI."
}

check_identity() {
  local arn
  arn="$(awsx sts get-caller-identity 2>/dev/null | jq -r '.Arn')" || die "La sesión de AWS no es válida. Abre el laboratorio de Academy (Start Lab) y vuelve a intentar."
  local role; role="$(printf '%s' "$arn" | sed -E 's#.*assumed-role/([^/]+)/.*#\1#')"
  info "Sesión AWS válida (rol: $role, perfil: $AWS_PROFILE, región: $AWS_REGION)"
}

# Localiza el ASG de V2 por la etiqueta Name; exige exactamente uno y que su nombre termine en -v2-asg.
find_asg() {
  local j n
  j="$(awsx autoscaling describe-auto-scaling-groups --filters "Name=tag:Name,Values=${V2_ASG_TAG_NAME}")"
  n="$(jq '.AutoScalingGroups | length' <<<"$j")"
  [[ "$n" == "1" ]] || die "Se esperaba exactamente 1 grupo de Auto Scaling con la etiqueta Name=${V2_ASG_TAG_NAME} y hay $n. No hago nada."
  ASG_NAME="$(jq -r '.AutoScalingGroups[0].AutoScalingGroupName' <<<"$j")"
  [[ "$ASG_NAME" =~ ^[a-z0-9-]+-v2-asg$ ]] || die "El nombre del grupo ('$ASG_NAME') no termina en -v2-asg; por seguridad no continúo."
}

load_asg() {
  ASG_JSON="$(awsx autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG_NAME")"
  [[ "$(jq '.AutoScalingGroups | length' <<<"$ASG_JSON")" == "1" ]] || die "No encuentro el grupo $ASG_NAME."
  ASG_MIN="$(jq -r '.AutoScalingGroups[0].MinSize' <<<"$ASG_JSON")"
  ASG_DES="$(jq -r '.AutoScalingGroups[0].DesiredCapacity' <<<"$ASG_JSON")"
  ASG_MAX="$(jq -r '.AutoScalingGroups[0].MaxSize' <<<"$ASG_JSON")"
  ASG_TOTAL="$(jq '.AutoScalingGroups[0].Instances | length' <<<"$ASG_JSON")"
  ASG_READY="$(jq '[.AutoScalingGroups[0].Instances[] | select(.LifecycleState=="InService" and .HealthStatus=="Healthy")] | length' <<<"$ASG_JSON")"
  ASG_ZONES="$(jq '[.AutoScalingGroups[0].Instances[] | select(.LifecycleState=="InService" and .HealthStatus=="Healthy") | .AvailabilityZone] | unique | length' <<<"$ASG_JSON")"
  TG_ARN="$(jq -r '.AutoScalingGroups[0].TargetGroupARNs[0] // empty' <<<"$ASG_JSON")"
}

load_alb() {
  TG_HEALTHY=0; ALB_NAME="-"; ALB_STATE="-"; ALB_DNS=""
  [[ -n "${TG_ARN:-}" ]] || return 0
  TH_JSON="$(awsx elbv2 describe-target-health --target-group-arn "$TG_ARN")"
  TG_HEALTHY="$(jq '[.TargetHealthDescriptions[] | select(.TargetHealth.State=="healthy")] | length' <<<"$TH_JSON")"
  local lb_arn lb
  lb_arn="$(awsx elbv2 describe-target-groups --target-group-arns "$TG_ARN" | jq -r '.TargetGroups[0].LoadBalancerArns[0] // empty')"
  if [[ -n "$lb_arn" ]]; then
    lb="$(awsx elbv2 describe-load-balancers --load-balancer-arns "$lb_arn")"
    ALB_NAME="$(jq -r '.LoadBalancers[0].LoadBalancerName' <<<"$lb")"
    ALB_STATE="$(jq -r '.LoadBalancers[0].State.Code' <<<"$lb")"
    ALB_DNS="$(jq -r '.LoadBalancers[0].DNSName' <<<"$lb")"
  fi
}

rds_state() {
  awsx rds describe-db-instances --db-instance-identifier "$V2_RDS_ID" 2>/dev/null | jq -r '.DBInstances[0].DBInstanceStatus' || echo "desconocido"
}

v1_state() {
  awsx ec2 describe-instances --filters "Name=tag:Name,Values=${V1_EC2_NAME}" "Name=instance-state-name,Values=pending,running,stopping,stopped" 2>/dev/null \
    | jq -r '[.Reservations[].Instances[] | .State.Name] | if length==0 then "no encontrada" else join(",") end' || echo "desconocido"
}

print_status() {
  echo "── AWS V2 ───────────────────────────────────────"
  echo "ASG:        $ASG_NAME"
  echo "Capacidad:  mínima=$ASG_MIN  deseada=$ASG_DES  máxima=$ASG_MAX"
  echo "Instancias: $ASG_TOTAL en el grupo, $ASG_READY InService/Healthy en $ASG_ZONES zona(s)"
  jq -r '.AutoScalingGroups[0].Instances[] | "   - \(.InstanceId)  \(.AvailabilityZone)  \(.LifecycleState)/\(.HealthStatus)"' <<<"$ASG_JSON"
  echo "ALB:        $ALB_NAME ($ALB_STATE)  destinos healthy: $TG_HEALTHY"
  [[ -z "${TH_JSON:-}" ]] || jq -r '.TargetHealthDescriptions[] | "   - destino \(.Target.Id): \(.TargetHealth.State)"' <<<"$TH_JSON"
  echo "RDS:        $(rds_state)  ($V2_RDS_ID)"
  echo "EC2 de V1:  $(v1_state)  (solo informativo; estos scripts no la tocan)"
}

verdict() {
  if (( ASG_DES == 0 && ASG_TOTAL == 0 )); then echo "RESULTADO: V2 APAGADA (capacidad 0). El ALB y la RDS siguen facturando."
  elif (( ASG_READY >= 2 && ASG_ZONES >= 2 && TG_HEALTHY >= 2 )); then echo "RESULTADO: V2 ENCENDIDA y SANA (2 instancias en 2 zonas, 2 destinos healthy)."
  else echo "RESULTADO: V2 EN TRANSICIÓN o DEGRADADA (listas=$ASG_READY, zonas=$ASG_ZONES, destinos healthy=$TG_HEALTHY, deseada=$ASG_DES)."; fi
}

confirm_phrase() {  # confirm_phrase "FRASE"  → exige escribir exactamente la frase
  local phrase="$1" ans
  read -r -p "Para continuar escribe exactamente «${phrase}» (cualquier otra cosa cancela): " ans || true
  [[ "$ans" == "$phrase" ]] || { echo "Cancelado: no se cambió nada."; exit 0; }
}

# ÚNICA función que cambia recursos en toda la suite.
set_capacity() {  # set_capacity MIN DESEADA
  info "Ejecutando: autoscaling update-auto-scaling-group --auto-scaling-group-name $ASG_NAME --min-size $1 --desired-capacity $2"
  "$AWS_BIN" autoscaling update-auto-scaling-group --auto-scaling-group-name "$ASG_NAME" --min-size "$1" --desired-capacity "$2" >/dev/null
}

recent_activities() {
  awsx autoscaling describe-scaling-activities --auto-scaling-group-name "$ASG_NAME" --max-items 3 2>/dev/null \
    | jq -r '.Activities[]? | "   \(.StartTime) \(.StatusCode): \(.StatusMessage // .Description)"' | cut -c1-230 || true
}
