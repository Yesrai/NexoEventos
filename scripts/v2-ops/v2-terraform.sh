#!/usr/bin/env bash
# v2-terraform — alterna V2 entre APAGADA (asg_enabled=false) y ENCENDIDA (asg_enabled=true) con Terraform, de forma controlada.
# Uso: ./v2-terraform.sh on|off [--plan-only]
#   on  : V2 encendida (mínima=deseada=2, máxima sin cambios). Exige la RDS 'available'.
#   off : V2 apagada (mínima=deseada=0, máxima sin cambios).
# Qué hace: comprueba perfil/cuenta/región → genera un plan GUARDADO con academy-v2-common.tfvars + academy-v2-{on|off}.tfvars → lo revisa →
#   solo acepta (a) «No changes» o (b) UNA modificación en el ASG que cambie únicamente min_size y desired_capacity al valor esperado.
#   Cualquier creación, destrucción, reemplazo o cambio en otro recurso/atributo BLOQUEA todo (no se aplica nada).
#   Para aplicar pide escribir exactamente «APLICAR ON» o «APLICAR OFF» y aplica solo el plan guardado. Nunca ejecuta destroy.
#   --plan-only: genera y revisa el plan, pero no ofrece aplicar.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
ROOT="$(cd "$HERE/../.." && pwd)"
TF_BIN="${TF_BIN:-terraform}"
V2_TF_DIR="${V2_TF_DIR:-$ROOT/infra/aws-v2}"
V2_TFVARS_DIR="${V2_TFVARS_DIR:-$ROOT/work/terraform-envs}"
V2_PLAN_DIR="${V2_PLAN_DIR:-$ROOT/work/operacion/v2-plans}"
MARKER="${V2_MARKER:-$ROOT/work/operacion/v2-estado-declarado}"
ASG_ADDR="aws_autoscaling_group.web"
MODE="${1:-}"; PLAN_ONLY=0
[[ "$MODE" == "on" || "$MODE" == "off" ]] || die "Uso: $0 on|off [--plan-only]   (el argumento es obligatorio: no hay valor por defecto)"
shift
while [[ $# -gt 0 ]]; do case "$1" in --plan-only) PLAN_ONLY=1;; *) die "Opción desconocida: $1";; esac; shift; done
MODE_UP="$(printf '%s' "$MODE" | tr '[:lower:]' '[:upper:]')"
COMMON="$V2_TFVARS_DIR/academy-v2-common.tfvars"; STATE_VARS="$V2_TFVARS_DIR/academy-v2-$MODE.tfvars"
need_tools; command -v "$TF_BIN" >/dev/null || die "Falta terraform."
[[ -f "$COMMON" && -f "$STATE_VARS" ]] || die "Faltan archivos locales: academy-v2-common.tfvars y/o academy-v2-$MODE.tfvars en $V2_TFVARS_DIR."
grep -q -E "^[[:space:]]*asg_enabled[[:space:]]*=" "$COMMON" && die "academy-v2-common.tfvars no debe definir asg_enabled (lo define on/off)."
want="$([[ "$MODE" == on ]] && echo true || echo false)"
grep -q -E "^[[:space:]]*asg_enabled[[:space:]]*=[[:space:]]*$want[[:space:]]*(#.*)?$" "$STATE_VARS" || die "$STATE_VARS no contiene asg_enabled = $want."
[[ -d "$V2_TF_DIR/.terraform" ]] || die "infra/aws-v2 no está inicializada (.terraform). Este script no ejecuta 'terraform init'; hazlo a mano si procede."

# 1) Perfil, cuenta y región (sin imprimir el número de cuenta)
check_identity
expected="$(awk -F= '$1 ~ /^[[:space:]]*expected_account_id[[:space:]]*$/ {gsub(/[[:space:]"]/, "", $2); print $2; exit}' "$COMMON")"
[[ "$expected" =~ ^[0-9]{12}$ ]] || die "No hay expected_account_id válido en academy-v2-common.tfvars."
actual="$(awsx sts get-caller-identity | jq -r '.Account')"
[[ "$actual" == "$expected" ]] || die "La cuenta de AWS activa NO coincide con expected_account_id. No hago nada."
info "Cuenta coincide con expected_account_id; perfil $AWS_PROFILE; región $AWS_REGION"
[[ "$AWS_REGION" == "us-east-1" ]] || die "Región inesperada."

# 2) Plan guardado
mkdir -p "$V2_PLAN_DIR"; chmod 700 "$V2_PLAN_DIR"
PLAN="$V2_PLAN_DIR/$(date -u +%Y%m%dT%H%M%SZ)-$MODE.tfplan"
info "Generando plan guardado: $(basename "$PLAN")"
"$TF_BIN" -chdir="$V2_TF_DIR" plan -input=false -lock=true -no-color -var-file="$COMMON" -var-file="$STATE_VARS" -out="$PLAN" >"$PLAN.txt" 2>&1 \
  || { tail -15 "$PLAN.txt" | sed -E 's/[0-9]{12}/<cuenta>/g'; die "terraform plan falló (detalle en $PLAN.txt)."; }
JSON="$("$TF_BIN" -chdir="$V2_TF_DIR" show -json "$PLAN")"

# 3) Revisión estricta
if jq -e '.errored == true' >/dev/null 2>&1 <<<"$JSON"; then die "El plan terminó con errores."; fi
CHG="$(jq -c '[.resource_changes[]? | select((.change.actions | join(",")) != "no-op" and (.change.actions | join(",")) != "read")]' <<<"$JSON")"
N="$(jq 'length' <<<"$CHG")"
echo "── Revisión del plan ($MODE) ────────────────────"
jq -r '.[] | "  \(.address): \(.change.actions | join("+"))"' <<<"$CHG"
OTHERS="$(jq -r --arg a "$ASG_ADDR" '[.[] | select(.address != $a) | .address] | join(", ")' <<<"$CHG")"
[[ -z "$OTHERS" ]] || die "BLOQUEADO: el plan toca recursos distintos del ASG autorizado ($OTHERS). No se aplica nada."
if (( N == 0 )); then
  ok "Sin cambios: AWS ya coincide con V2 '$MODE'. No hay nada que aplicar."
  printf '%s\n' "$MODE" > "$MARKER"; exit 0
fi
(( N == 1 )) || die "BLOQUEADO: se esperaba como máximo 1 cambio y hay $N."
ACTIONS="$(jq -r '.[0].change.actions | join("+")' <<<"$CHG")"
[[ "$ACTIONS" == "update" ]] || die "BLOQUEADO: la acción sobre el ASG es '$ACTIONS' (solo se admite 'update': nada de crear, destruir ni reemplazar)."
KEYS="$(jq -r '.[0].change as $c | [$c.after | keys[] | select(($c.before[.]) != ($c.after[.]))] | sort | join(",")' <<<"$CHG")"
[[ "$KEYS" == "desired_capacity,min_size" || "$KEYS" == "desired_capacity" || "$KEYS" == "min_size" ]] || die "BLOQUEADO: el cambio del ASG toca atributos no autorizados ($KEYS); solo se permiten min_size y desired_capacity."
MINA="$(jq -r '.[0].change.after.min_size' <<<"$CHG")"; DESA="$(jq -r '.[0].change.after.desired_capacity' <<<"$CHG")"; MAXA="$(jq -r '.[0].change.after.max_size' <<<"$CHG")"
if [[ "$MODE" == off ]]; then
  [[ "$MINA" == 0 && "$DESA" == 0 ]] || die "BLOQUEADO: para 'off' se esperaba min=0 y deseada=0 (plan: min=$MINA, deseada=$DESA)."
else
  [[ "$MINA" =~ ^[0-9]+$ && "$DESA" =~ ^[0-9]+$ && "$MAXA" =~ ^[0-9]+$ ]] && (( MINA >= 2 && DESA >= MINA && DESA <= MAXA )) || die "BLOQUEADO: para 'on' se esperaba 2 <= min <= deseada <= máxima (plan: min=$MINA, deseada=$DESA, máx=$MAXA)."
fi
ok "Plan válido: 1 modificación del ASG ($KEYS) → mínima=$MINA, deseada=$DESA, máxima=$MAXA (sin crear/destruir/reemplazar nada)."
jq -r '(.resource_drift // [])[] | "  (deriva ya existente, informativa) \(.address): \(.change.actions | join("+"))"' <<<"$JSON"
(( PLAN_ONLY )) && { echo "(--plan-only) No se aplica nada. Plan: $PLAN"; exit 0; }

# 4) Aplicación (solo plan guardado, con confirmación)
if [[ "$MODE" == on ]]; then
  db="$(rds_state)"; [[ "$db" == "available" ]] || die "La RDS ($V2_RDS_ID) está '$db'. Inicia la RDS y espera 'available' antes de encender V2."
fi
confirm_phrase "APLICAR $MODE_UP"
info "Aplicando el plan guardado (no se ejecuta destroy)"
"$TF_BIN" -chdir="$V2_TF_DIR" apply -input=false -no-color "$PLAN" >"$PLAN.apply.txt" 2>&1 || { tail -15 "$PLAN.apply.txt" | sed -E 's/[0-9]{12}/<cuenta>/g'; die "terraform apply falló (detalle en $PLAN.apply.txt)."; }
grep -E "^Apply complete" "$PLAN.apply.txt" || true
printf '%s\n' "$MODE" > "$MARKER"
find_asg
if [[ "$MODE" == on ]]; then
  start=$SECONDS
  while :; do
    load_asg; load_alb; el=$(( SECONDS - start ))
    echo "  [${el}s] listas=$ASG_READY/2 zonas=$ASG_ZONES destinos healthy=$TG_HEALTHY"
    (( ASG_READY >= 2 && ASG_ZONES >= 2 && TG_HEALTHY >= 2 )) && break
    (( el < 600 )) || { print_status; die "Tiempo máximo (600 s) agotado esperando V2; revisa ./v2-status.sh."; }
    sleep "$POLL_INTERVAL"
  done
else
  start=$SECONDS
  while :; do load_asg; echo "  [$(( SECONDS - start ))s] instancias=$ASG_TOTAL"; (( ASG_TOTAL == 0 )) && break; (( SECONDS - start < 600 )) || die "Tiempo máximo agotado; revisa ./v2-status.sh."; sleep "$POLL_INTERVAL"; done
fi
load_alb; print_status; verdict
ok "Terraform y AWS coinciden con V2 '$MODE'."
