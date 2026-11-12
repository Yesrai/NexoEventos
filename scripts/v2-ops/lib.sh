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

# ── Guardas de seguridad de Terraform (solo las usa v2-terraform.sh) ─────────────────────────────────────
# Se ejecutan ANTES de cualquier llamada a terraform o a aws. No usan red. Ante cualquier duda: die (no se hace nada).

# guard_env <valor_por_defecto_de_cada_ruta...>: rechaza variables que desvíen el backend y los «overrides» de rutas/binarios.
# Los overrides (V2_TF_DIR, V2_TFSTATE, TF_BIN, AWS_BIN...) solo valen en pruebas aisladas: V2_TEST_MODE=1 + simuladores.
guard_env() {
  local bad v ov="" want_tf="$ROOT/infra/aws-v2" want_vars="$ROOT/work/terraform-envs" want_plans="$ROOT/work/operacion/v2-plans" want_marker="$ROOT/work/operacion/v2-estado-declarado"
  bad="$(env | cut -d= -f1 | grep -E '^(TF_DATA_DIR|TF_WORKSPACE|TF_CLI_ARGS(_.*)?)$' | tr '\n' ' ' || true)"
  [[ -z "$bad" ]] || die "BLOQUEADO: variables de entorno que alteran el backend o el espacio de trabajo de Terraform: ${bad}(ejecuta 'unset' sobre ellas)."
  [[ -z "${V2_STATE_IDENTITY:-}${V2_TFSTATE:-}" || "${V2_TEST_MODE:-}" == 1 ]] || ov+="V2_STATE_IDENTITY/V2_TFSTATE "
  [[ "$V2_TF_DIR" == "$want_tf" ]]          || ov+="V2_TF_DIR "
  [[ "$V2_TFVARS_DIR" == "$want_vars" ]]    || ov+="V2_TFVARS_DIR "
  [[ "$V2_PLAN_DIR" == "$want_plans" ]]     || ov+="V2_PLAN_DIR "
  [[ "$MARKER" == "$want_marker" ]]         || ov+="V2_MARKER "
  [[ "$(basename "$TF_BIN")" == terraform ]] || ov+="TF_BIN "
  [[ "$(basename "$AWS_BIN")" == aws ]]      || ov+="AWS_BIN "
  case "${V2_TEST_MODE:-}" in
    "") [[ -z "$ov" ]] || die "BLOQUEADO: se detectaron overrides (${ov% }) fuera del modo de pruebas. Solo se permiten con V2_TEST_MODE=1 y los simuladores de tests/." ;;
    1)  [[ "$(basename "$TF_BIN")" == fake-terraform.sh && "$(basename "$AWS_BIN")" == fake-aws.sh ]] || die "BLOQUEADO: V2_TEST_MODE=1 solo se admite con tests/fake-terraform.sh y tests/fake-aws.sh (nunca con terraform o aws reales)."
        echo "⚠ MODO DE PRUEBAS AISLADAS (simuladores; no es una operación real)" >&2 ;;
    *)  die "BLOQUEADO: V2_TEST_MODE solo admite el valor 1." ;;
  esac
}

# guard_state: comprueba que el backend cacheado es local y apunta (ruta FÍSICA) al estado real de V2, que el estado existe,
# es JSON válido, tiene la identidad (lineage) esperada de V2 y contiene el recurso gestionado aws_autoscaling_group.web.
# La identidad esperada está en scripts/v2-ops/v2-state-identity (versionado en Git). No se usan serial, hashes ni mínimos de recursos.
guard_state() {
  local ident cache cfg real want lineage_exp lin n
  ident="${V2_STATE_IDENTITY:-$HERE/v2-state-identity}"
  [[ -f "$ident" && ! -L "$ident" ]] || die "BLOQUEADO: falta el archivo de identidad del estado de V2 ($ident)."
  [[ "$(grep -c -E '^lineage=' "$ident" || true)" == 1 ]] || die "BLOQUEADO: el archivo de identidad debe tener exactamente una línea 'lineage='."
  lineage_exp="$(sed -n 's/^lineage=//p' "$ident")"
  [[ "$lineage_exp" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || die "BLOQUEADO: el lineage del archivo de identidad no tiene formato UUID."
  want="${V2_TFSTATE:-$ROOT/work/terraform-state/academy-v2/terraform.tfstate}"
  cache="$V2_TF_DIR/.terraform/terraform.tfstate"
  [[ -f "$cache" ]] || die "BLOQUEADO: no hay caché del backend ($cache). Este script no ejecuta 'terraform init'."
  jq -e 'type=="object"' "$cache" >/dev/null 2>&1 || die "BLOQUEADO: la caché del backend no es JSON válido."
  jq -e '.backend.type=="local" and (.backend.config.path|type=="string" and length>0) and ((.backend.config.workspace_dir // null)==null)' "$cache" >/dev/null 2>&1 \
    || die "BLOQUEADO: el backend cacheado no es 'local' con una ruta de estado explícita (sin workspace_dir)."
  if [[ -e "$V2_TF_DIR/.terraform/environment" ]]; then
    [[ "$(cat "$V2_TF_DIR/.terraform/environment")" == default ]] || die "BLOQUEADO: hay un espacio de trabajo de Terraform distinto de 'default'."
  fi
  cfg="$(jq -r '.backend.config.path' "$cache")"
  [[ "$cfg" == /* ]] || die "BLOQUEADO: la ruta del estado cacheada no es absoluta."
  real="$(cd "$(dirname "$cfg")" 2>/dev/null && printf '%s/%s' "$(pwd -P)" "$(basename "$cfg")")" || die "BLOQUEADO: el directorio del estado cacheado no existe."
  [[ "$real" == "$want" ]] || die "BLOQUEADO: el backend apunta a otro estado ($real); se esperaba $want. Se corrige a mano con 'terraform init -reconfigure -backend-config=path=…'."
  [[ -f "$real" && ! -L "$real" ]] || die "BLOQUEADO: el archivo de estado no existe o es un enlace simbólico ($real)."
  [[ -s "$real" ]] || die "BLOQUEADO: el archivo de estado está vacío."
  jq -e '.version==4 and (.serial|type=="number") and (.lineage|type=="string") and (.resources|type=="array")' "$real" >/dev/null 2>&1 \
    || die "BLOQUEADO: el estado no es un JSON de estado de Terraform válido."
  lin="$(jq -r '.lineage' "$real")"
  [[ "$lin" == "$lineage_exp" ]] || die "BLOQUEADO: identidad inesperada del estado (lineage ${lin:0:8}… distinto del esperado ${lineage_exp:0:8}…). Puede ser un estado ajeno o recreado."
  jq -e '[.resources[]? | select(.mode=="managed" and .type=="aws_autoscaling_group" and .name=="web" and ((.module // "")=="") and (((.instances // [])|length)>=1))] | length==1' "$real" >/dev/null 2>&1 \
    || die "BLOQUEADO: el estado no contiene el recurso gestionado aws_autoscaling_group.web."
  n="$(jq '[.resources[]? | select(.mode=="managed")] | length' "$real")"
  info "Estado de V2 verificado: ruta física correcta, lineage ${lin:0:8}…, serial $(jq -r '.serial' "$real"), $n recursos gestionados"
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
