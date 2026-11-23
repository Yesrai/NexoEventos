#!/usr/bin/env bash
# Pruebas de v2-up / v2-down / v2-status con un aws SIMULADO (sin red, sin credenciales, sin cambiar nada en AWS).
cd "$(dirname "$0")/.."; chmod +x tests/fake-aws.sh
export AWS_BIN="$PWD/tests/fake-aws.sh" POLL_INTERVAL=0 V2_SKIP_HTTP=1
pass=0; fail=0
t() { local name="$1"; shift; if "$@"; then echo "PASA  $name"; pass=$((pass+1)); else echo "FALLA $name"; fail=$((fail+1)); fi; }
new() { export MOCK_DIR="$(mktemp -d)"; echo "$1" > "$MOCK_DIR/state"; : > "$MOCK_DIR/calls.log"; unset MOCK_TWO_ASG MOCK_ASG MOCK_RDS; }
muts() { grep -c -E '^(autoscaling update-|ec2 (run|start|stop|terminate)|rds (start|stop|delete|modify)|elbv2 (delete|modify|create)|route53|acm|secretsmanager)' "$MOCK_DIR/calls.log" || true; }
updates() { grep -c '^autoscaling update-auto-scaling-group' "$MOCK_DIR/calls.log" || true; }
unexpected() { grep -c '^UNEXPECTED' "$MOCK_DIR/calls.log" || true; }

new on;  ./v2-status.sh >/dev/null;                                  t "status no cambia nada (0 llamadas de escritura)" test "$(muts)" = 0
new off; ./v2-up.sh --dry-run >/dev/null;                            t "up --dry-run no cambia nada" test "$(muts)" = 0
new off; echo "no" | ./v2-up.sh >/dev/null;                          t "up con confirmación incorrecta no cambia nada" test "$(muts)" = 0
new off; echo "ENCENDER V2" | ./v2-up.sh >/dev/null;                t "up confirmado hace UNA sola llamada de escritura" test "$(muts)" = 1
t "up pide mínima=2 y deseada=2 sobre el ASG de V2" grep -q -- "update-auto-scaling-group --auto-scaling-group-name nexoeventos-academy-v2-asg --min-size 2 --desired-capacity 2" "$MOCK_DIR/calls.log"
t "up deja el estado en 'on'" test "$(cat "$MOCK_DIR/state")" = on
new on;  ./v2-down.sh --dry-run >/dev/null;                          t "down --dry-run no cambia nada" test "$(muts)" = 0
new on;  echo "apagar" | ./v2-down.sh >/dev/null;                    t "down con confirmación incorrecta no cambia nada" test "$(muts)" = 0
new on;  echo "APAGAR V2" | ./v2-down.sh >/dev/null;                 t "down confirmado hace UNA sola llamada de escritura" test "$(muts)" = 1
t "down pone mínima=0 y deseada=0 sobre el ASG de V2" grep -q -- "update-auto-scaling-group --auto-scaling-group-name nexoeventos-academy-v2-asg --min-size 0 --desired-capacity 0" "$MOCK_DIR/calls.log"
t "down no llama a ec2/rds/elbv2 de escritura ni a nada no previsto" test "$(unexpected)" = 0
new on;  ./v2-up.sh >/dev/null <<<"" ;                               t "up con V2 ya encendida no hace nada" test "$(muts)" = 0
new off; ./v2-down.sh >/dev/null <<<"";                              t "down con V2 ya apagada no hace nada" test "$(muts)" = 0
new off; MOCK_RDS=stopped ./v2-up.sh >/dev/null 2>&1 <<<"ENCENDER V2"; rc=$?; t "up aborta si la RDS no está available (sin cambios)" test "$(muts)" = 0 -a "$rc" != 0
new off; MOCK_TWO_ASG=1 ./v2-down.sh >/dev/null 2>&1 <<<"APAGAR V2"; t "con 2 ASG coincidentes aborta sin cambios" test "$(muts)" = 0
new on;  MOCK_ASG=otro-asg ./v2-down.sh >/dev/null 2>&1 <<<"APAGAR V2"; t "si el nombre no termina en -v2-asg aborta sin cambios" test "$(muts)" = 0
echo "-- ${pass} pasan, ${fail} fallan"; [[ $fail -eq 0 ]]
