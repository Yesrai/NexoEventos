#!/usr/bin/env bash
# Pruebas de v2-terraform.sh con terraform y aws SIMULADOS (sin red, sin credenciales, sin tocar nada real).
cd "$(dirname "$0")/.."; chmod +x tests/*.sh
export AWS_BIN="$PWD/tests/fake-aws.sh" TF_BIN="$PWD/tests/fake-terraform.sh" POLL_INTERVAL=0
export V2_TEST_MODE=1     # SOLO pruebas aisladas: habilita los overrides y exige los simuladores (nunca terraform/aws reales)
unset TF_DATA_DIR TF_WORKSPACE TF_CLI_ARGS TF_CLI_ARGS_plan TF_CLI_ARGS_init
LIN="aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb"      # lineage FICTICIO de prueba (no es el de V2)
pass=0; fail=0
t() { local n="$1"; shift; if "$@"; then echo "PASA  $n"; pass=$((pass+1)); else echo "FALLA $n"; fail=$((fail+1)); fi; }
mkstate() {  # mkstate <lineage> <n recursos de relleno> <con_asg 1|0> → escribe el estado simulado en $V2_TFSTATE
  jq -n --arg l "$1" --argjson n "$2" --argjson a "$3" '{version:4,terraform_version:"1.16.4",serial:7,lineage:$l,outputs:{},check_results:null,
    resources:((if $a==1 then [{mode:"managed",type:"aws_autoscaling_group",name:"web",provider:"p",instances:[{schema_version:0,attributes:{}}]}] else [] end)
      + [range(0;$n)|{mode:"managed",type:"aws_security_group_rule",name:("r\(.)"),provider:"p",instances:[{schema_version:0,attributes:{}}]}])}' > "$V2_TFSTATE"; }
mkcache() {  # mkcache <tipo de backend> <ruta del estado> → escribe la caché .terraform/terraform.tfstate simulada
  jq -n --arg t "$1" --arg p "$2" '{version:3,terraform_version:"1.16.4",backend:{type:$t,config:{path:$p,workspace_dir:null},hash:1}}' > "$V2_TF_DIR/.terraform/terraform.tfstate"; }
new() {  # new <estado_aws on|off>
  export MOCK_DIR="$(cd "$(mktemp -d)" && pwd -P)"; echo "$1" > "$MOCK_DIR/state"; : > "$MOCK_DIR/calls.log"; : > "$MOCK_DIR/tf-calls.log"
  export V2_TF_DIR="$MOCK_DIR/tf"; mkdir -p "$V2_TF_DIR/.terraform"; export V2_TFVARS_DIR="$MOCK_DIR/vars"; mkdir -p "$V2_TFVARS_DIR"
  # estado simulado válido + identidad + caché del backend (todo dentro de $MOCK_DIR; jamás se toca el estado real)
  mkdir -p "$MOCK_DIR/st"; export V2_TFSTATE="$MOCK_DIR/st/terraform.tfstate" V2_STATE_IDENTITY="$MOCK_DIR/identidad"
  printf 'lineage=%s\n' "$LIN" > "$V2_STATE_IDENTITY"; mkstate "$LIN" 18 1; mkcache local "$V2_TFSTATE"
  printf 'expected_account_id = "111111111111"\nami_id = "ami-0123456789abcdef0"\n' > "$V2_TFVARS_DIR/academy-v2-common.tfvars"
  printf 'asg_enabled = true\n' > "$V2_TFVARS_DIR/academy-v2-on.tfvars"; printf 'asg_enabled = false\n' > "$V2_TFVARS_DIR/academy-v2-off.tfvars"
  export V2_PLAN_DIR="$MOCK_DIR/plans" V2_MARKER="$MOCK_DIR/marker" MOCK_PLAN_JSON="$MOCK_DIR/plan.json"; unset MOCK_ACCOUNT MOCK_RDS MOCK_TWO_ASG MOCK_ASG
}
J_NOCHG='{"resource_changes":[{"address":"aws_autoscaling_group.web","change":{"actions":["no-op"]}},{"address":"aws_lb.main","change":{"actions":["no-op"]}}]}'
asg() { echo "{\"resource_changes\":[{\"address\":\"aws_lb.main\",\"change\":{\"actions\":[\"no-op\"]}},{\"address\":\"aws_autoscaling_group.web\",\"change\":{\"actions\":[\"update\"],\"before\":{\"min_size\":$1,\"desired_capacity\":$1,\"max_size\":3,\"name\":\"x\"},\"after\":{\"min_size\":$2,\"desired_capacity\":$2,\"max_size\":${3:-3},\"name\":\"x\"}}}]}"; }
applies() { grep -c ' apply ' "$MOCK_DIR/tf-calls.log" || true; }
plans()   { grep -c ' plan ' "$MOCK_DIR/tf-calls.log" || true; }
unexp()   { grep -c UNEXPECTED "$MOCK_DIR/tf-calls.log" || true; }

new off; ./v2-terraform.sh >/dev/null 2>&1; rc=$?;                         t "sin argumento: error y ninguna llamada a terraform" test "$rc" != 0 -a "$(plans)" = 0
new off; ./v2-terraform.sh quizas >/dev/null 2>&1; rc=$?;                   t "argumento inválido: error" test "$rc" != 0 -a "$(plans)" = 0
new off; echo "$J_NOCHG" > "$MOCK_PLAN_JSON"; ./v2-terraform.sh off >/dev/null 2>&1; rc=$?; t "'No changes' es válido (rc 0, nada aplicado, marcador=off)" test "$rc" = 0 -a "$(applies)" = 0 -a "$(cat "$V2_MARKER")" = off
new off; asg 0 2 > "$MOCK_PLAN_JSON"; ./v2-terraform.sh on --plan-only >/dev/null 2>&1; rc=$?; t "on --plan-only con 1 cambio válido: rc 0 y sin apply" test "$rc" = 0 -a "$(applies)" = 0
new off; asg 0 2 > "$MOCK_PLAN_JSON"; echo "aplicar on" | ./v2-terraform.sh on >/dev/null 2>&1; t "confirmación incorrecta: no se aplica" test "$(applies)" = 0
new off; asg 0 2 > "$MOCK_PLAN_JSON"; echo "APLICAR ON" | ./v2-terraform.sh on >/dev/null 2>&1; rc=$?; t "on confirmado: UN apply del plan guardado y marcador=on" test "$rc" = 0 -a "$(applies)" = 1 -a "$(cat "$V2_MARKER")" = on
t "el apply usa el archivo de plan guardado" grep -q -E ' apply .*\.tfplan$' "$MOCK_DIR/tf-calls.log"
new on;  asg 2 0 > "$MOCK_PLAN_JSON"; echo "APLICAR OFF" | ./v2-terraform.sh off >/dev/null 2>&1; rc=$?; t "off confirmado: UN apply y marcador=off" test "$rc" = 0 -a "$(applies)" = 1 -a "$(cat "$V2_MARKER")" = off
new off; asg 0 2 > "$MOCK_PLAN_JSON"; echo "APLICAR OFF" | ./v2-terraform.sh on >/dev/null 2>&1; t "frase de confirmación del modo contrario: no se aplica" test "$(applies)" = 0
new off; echo '{"resource_changes":[{"address":"aws_lb.main","change":{"actions":["update"],"before":{"a":1},"after":{"a":2}}}]}' > "$MOCK_PLAN_JSON"; echo "APLICAR ON" | ./v2-terraform.sh on >/dev/null 2>&1; t "cambio en otro recurso (ALB): BLOQUEADO" test "$(applies)" = 0
new off; echo '{"resource_changes":[{"address":"aws_lb.nuevo","change":{"actions":["create"],"before":null,"after":{"a":1}}}]}' > "$MOCK_PLAN_JSON"; echo "APLICAR ON" | ./v2-terraform.sh on >/dev/null 2>&1; t "creación de recursos: BLOQUEADO" test "$(applies)" = 0
new off; echo '{"resource_changes":[{"address":"aws_autoscaling_group.web","change":{"actions":["delete","create"],"before":{"min_size":0},"after":{"min_size":2}}}]}' > "$MOCK_PLAN_JSON"; echo "APLICAR ON" | ./v2-terraform.sh on >/dev/null 2>&1; t "reemplazo del ASG: BLOQUEADO" test "$(applies)" = 0
new off; echo '{"resource_changes":[{"address":"aws_autoscaling_group.web","change":{"actions":["delete"],"before":{"min_size":0},"after":null}}]}' > "$MOCK_PLAN_JSON"; echo "APLICAR OFF" | ./v2-terraform.sh off >/dev/null 2>&1; t "destrucción del ASG: BLOQUEADO" test "$(applies)" = 0
new off; asg 0 2 4 > "$MOCK_PLAN_JSON"; echo "APLICAR ON" | ./v2-terraform.sh on >/dev/null 2>&1; t "ASG que además cambia la máxima: BLOQUEADO" test "$(applies)" = 0
new off; echo '{"resource_changes":[{"address":"aws_autoscaling_group.web","change":{"actions":["update"],"before":{"min_size":0,"desired_capacity":0,"max_size":3,"health_check_type":"ELB"},"after":{"min_size":2,"desired_capacity":2,"max_size":3,"health_check_type":"EC2"}}}]}' > "$MOCK_PLAN_JSON"; echo "APLICAR ON" | ./v2-terraform.sh on >/dev/null 2>&1; t "ASG con otro atributo cambiado: BLOQUEADO" test "$(applies)" = 0
new on;  asg 2 2 > "$MOCK_PLAN_JSON"; sed -i '' 's/"desired_capacity":2,"max_size":3,"name":"x"},"after"/"desired_capacity":2,"max_size":3,"name":"x"},"after"/' "$MOCK_PLAN_JSON"; new on; echo '{"resource_changes":[{"address":"aws_autoscaling_group.web","change":{"actions":["update"],"before":{"min_size":2,"desired_capacity":2,"max_size":3},"after":{"min_size":2,"desired_capacity":1,"max_size":3}}}]}' > "$MOCK_PLAN_JSON"; echo "APLICAR OFF" | ./v2-terraform.sh off >/dev/null 2>&1; t "'off' cuyo plan no deja 0/0: BLOQUEADO" test "$(applies)" = 0
new off; asg 0 2 > "$MOCK_PLAN_JSON"; MOCK_ACCOUNT=999999999999 ./v2-terraform.sh on >/dev/null 2>&1; rc=$?; t "cuenta distinta: aborta antes de planear" test "$rc" != 0 -a "$(plans)" = 0
new off; asg 0 2 > "$MOCK_PLAN_JSON"; MOCK_RDS=stopped bash -c 'echo "APLICAR ON" | ./v2-terraform.sh on' >/dev/null 2>&1; t "on con la RDS detenida: no se aplica" test "$(applies)" = 0
new off; echo 'asg_enabled = true' >> "$V2_TFVARS_DIR/academy-v2-common.tfvars"; asg 0 2 > "$MOCK_PLAN_JSON"; ./v2-terraform.sh on --plan-only >/dev/null 2>&1; rc=$?; t "common.tfvars con asg_enabled: aborta" test "$rc" != 0 -a "$(plans)" = 0
new off; printf 'asg_enabled = false\n' > "$V2_TFVARS_DIR/academy-v2-on.tfvars"; asg 0 2 > "$MOCK_PLAN_JSON"; ./v2-terraform.sh on --plan-only >/dev/null 2>&1; rc=$?; t "on.tfvars con valor equivocado: aborta" test "$rc" != 0 -a "$(plans)" = 0
# ── Guarda de estado: lo peligroso se bloquea ANTES de ejecutar terraform o aws (ambos registros vacíos) ──
blocked() { test "$rc" != 0 -a ! -s "$MOCK_DIR/tf-calls.log" -a ! -s "$MOCK_DIR/calls.log"; }
go() { asg 0 2 > "$MOCK_PLAN_JSON"; env "$@" ./v2-terraform.sh on --plan-only >/dev/null 2>&1; rc=$?; }
LIN2="cccccccc-1111-4222-8333-dddddddddddd"
new off; go;                                                        t "guarda: estado válido pasa y llega a terraform (1 plan)" test "$rc" = 0 -a "$(plans)" = 1
new off; rm -f "$V2_TFSTATE"; go;                                   t "guarda: estado ausente → bloqueado" blocked
new off; : > "$V2_TFSTATE"; go;                                     t "guarda: estado vacío → bloqueado" blocked
new off; printf '{"version":4,"serial":' > "$V2_TFSTATE"; go;       t "guarda: JSON corrupto → bloqueado" blocked
new off; mkcache s3 "$V2_TFSTATE"; go;                              t "guarda: backend no local → bloqueado" blocked
new off; mkdir "$MOCK_DIR/otro"; cp "$V2_TFSTATE" "$MOCK_DIR/otro/terraform.tfstate"; mkcache local "$MOCK_DIR/otro/terraform.tfstate"; go; t "guarda: backend apunta a otra ruta (aunque haya un estado válido allí) → bloqueado" blocked
new off; mkcache local "st/terraform.tfstate"; go;                  t "guarda: ruta del backend no absoluta → bloqueado" blocked
new off; mkstate "$LIN2" 18 1; go;                                  t "guarda: lineage incorrecto → bloqueado" blocked
new off; mkstate "$LIN2" 60 1; go;                                  t "guarda: muchos recursos pero identidad incorrecta → bloqueado" blocked
new off; mkstate "$LIN" 18 0; go;                                   t "guarda: falta aws_autoscaling_group.web → bloqueado" blocked
new off; rm -f "$V2_STATE_IDENTITY"; go;                            t "guarda: falta el archivo de identidad → bloqueado" blocked
new off; printf 'lineage=%s\nlineage=%s\n' "$LIN" "$LIN2" > "$V2_STATE_IDENTITY"; go; t "guarda: archivo de identidad con dos líneas → bloqueado" blocked
new off; printf 'lineage=no-es-un-uuid\n' > "$V2_STATE_IDENTITY"; go; t "guarda: lineage de referencia mal formado → bloqueado" blocked
new off; mv "$V2_TFSTATE" "$MOCK_DIR/real.json"; ln -s "$MOCK_DIR/real.json" "$V2_TFSTATE"; go; t "guarda: el archivo de estado es un enlace simbólico → bloqueado" blocked
new off; printf 'otro\n' > "$V2_TF_DIR/.terraform/environment"; go; t "guarda: espacio de trabajo distinto de default → bloqueado" blocked
new off; go TF_DATA_DIR=/tmp/otro-data;                             t "guarda: TF_DATA_DIR definida → bloqueado" blocked
new off; go TF_WORKSPACE=otro;                                      t "guarda: TF_WORKSPACE definida → bloqueado" blocked
new off; go TF_CLI_ARGS_plan="-state=/tmp/otro.tfstate";            t "guarda: TF_CLI_ARGS_plan definida → bloqueado" blocked
new off; go -u V2_TEST_MODE;                                        t "guarda: overrides sin V2_TEST_MODE → bloqueado" blocked
new off; go V2_TEST_MODE=2;                                         t "guarda: V2_TEST_MODE con valor distinto de 1 → bloqueado" blocked
new off; go TF_BIN="$(command -v true)";                            t "guarda: modo de pruebas con un terraform que no es el simulado → bloqueado" blocked
new off; ln -s "$MOCK_DIR/st" "$MOCK_DIR/enlace"; mkcache local "$MOCK_DIR/enlace/terraform.tfstate"; go; t "guarda: ruta con enlace al mismo estado (comparación física) → permitido" test "$rc" = 0 -a "$(plans)" = 1
t "ninguna prueba de la guarda llamó a terraform de forma inesperada" test "$(unexp)" = 0
t "el script nunca invoca 'destroy'" test "$(grep -v '^[[:space:]]*#' v2-terraform.sh | grep -c -E 'TF_BIN.* destroy|terraform destroy')" = 0
t "ninguna prueba produjo llamadas inesperadas" test "$(unexp)" = 0
echo "-- ${pass} pasan, ${fail} fallan"; [[ $fail -eq 0 ]]
