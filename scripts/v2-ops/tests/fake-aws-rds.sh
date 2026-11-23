#!/usr/bin/env bash
# AWS simulado SOLO para probar rds-window.sh: estado en $FAKE_DIR; registra cada llamada en $FAKE_DIR/calls.
# Parada Multi-AZ simulada: FAKE_STOP_SECS=n → `stopping` durante n segundos; FAKE_STOP_NEVER=1 → se queda en `stopping`; archivo stop_err → stop-db-instance falla.
d="$FAKE_DIR"; echo "$1 $2 ${*:3}" >>"$d/calls"
now=$(date +%s)
if [[ "$1 $2" == "rds describe-db-instances" && -e "$d/stop_at" && "$(cat "$d/rds")" == stopping && -z "${FAKE_STOP_NEVER:-}" && $now -ge $(cat "$d/stop_at") ]]; then echo stopped >"$d/rds"; fi
case "$1 $2" in
  "sts get-caller-identity") [[ -e "$d/expired" ]] && { echo "ExpiredToken" >&2; exit 254; }; echo "$FAKE_ACCOUNT";;
  "configure get") echo us-east-1;;
  "rds describe-db-instances") [[ -e "$d/expired" ]] && exit 254; cat "$d/rds";;
  "rds start-db-instance") echo starting >"$d/rds"; echo 0 >"$d/polls";;
  "rds stop-db-instance")
    [[ -e "$d/expired" || -e "$d/stop_err" ]] && exit 1
    if [[ -n "${FAKE_STOP_SECS:-}" || -n "${FAKE_STOP_NEVER:-}" ]]; then echo stopping >"$d/rds"; echo $((now + ${FAKE_STOP_SECS:-9999})) >"$d/stop_at"; else echo stopped >"$d/rds"; fi;;
  "autoscaling describe-auto-scaling-groups") if [[ "$*" == *"[0].DesiredCapacity"* ]]; then awk -F'\t' '{print $2}' "$d/asg"; else cat "$d/asg"; fi;;
  "autoscaling update-auto-scaling-group") printf '0\t0\t0\n' >"$d/asg"; echo 0 >"$d/ec2";;
  "ec2 describe-instances") if [[ "$*" == *--instance-ids* ]]; then cat "$d/zones"; else cat "$d/ec2"; fi;;
  "elbv2 describe-load-balancers")
    if [[ "$*" == *--names* ]]; then if [[ "$(cat "$d/alb")" != 0 ]]; then [[ "$*" == *DNSName* ]] && echo "fake-alb.example.elb.amazonaws.com" || echo "arn:aws:elasticloadbalancing:us-east-1:000000000000:loadbalancer/app/fake/1"; else echo None; fi
    else cat "$d/alb"; fi;;
  "elbv2 describe-tags") [[ -e "$d/notags" ]] && echo "" || printf 'Project\tNexoEventos\nStack\tv2\n';;
  "elbv2 delete-load-balancer") echo 0 >"$d/alb";;
  "elbv2 describe-target-groups") echo "arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/fake/1";;
  "elbv2 describe-target-health") cat "$d/healthy" 2>/dev/null;;
  *) echo "llamada no prevista: $*" >&2; exit 99;;
esac
if [[ "$1 $2" == "rds describe-db-instances" && "$(cat "$d/rds")" == starting ]]; then n=$(( $(cat "$d/polls") + 1 )); echo $n >"$d/polls"; (( n >= 2 )) && echo available >"$d/rds"; fi
exit 0
