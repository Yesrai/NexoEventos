#!/usr/bin/env bash
# aws SIMULADO para pruebas locales: no usa red ni credenciales. Registra cada llamada en $MOCK_DIR/calls.log.
# Estado en $MOCK_DIR/state: "on" (2 instancias sanas) | "off" (0). update-auto-scaling-group cambia el estado.
set -u
D="${MOCK_DIR:?}"; echo "$*" >> "$D/calls.log"
ST="$(cat "$D/state")"; ASGNAME="${MOCK_ASG:-nexoeventos-academy-v2-asg}"
args=("$@"); svc="${args[0]:-}"; cmd="${args[1]:-}"
inst() { cat <<J
[{"InstanceId":"i-aaa","AvailabilityZone":"us-east-1a","LifecycleState":"InService","HealthStatus":"Healthy"},{"InstanceId":"i-bbb","AvailabilityZone":"us-east-1b","LifecycleState":"InService","HealthStatus":"Healthy"}]
J
}
case "$svc $cmd" in
 "sts get-caller-identity") echo "{\"Arn\":\"arn:aws:sts::000000000000:assumed-role/voclabs/test\",\"Account\":\"${MOCK_ACCOUNT:-111111111111}\"}";;
 "autoscaling describe-auto-scaling-groups")
   if [[ "$*" == *"--filters"* && "${MOCK_TWO_ASG:-0}" == "1" ]]; then
     echo '{"AutoScalingGroups":[{"AutoScalingGroupName":"a-v2-asg"},{"AutoScalingGroupName":"b-v2-asg"}]}'
   else
     if [[ "$ST" == "on" ]]; then I="$(inst)"; MIN=2; DES=2; else I='[]'; MIN=0; DES=0; fi
     echo "{\"AutoScalingGroups\":[{\"AutoScalingGroupName\":\"$ASGNAME\",\"MinSize\":$MIN,\"DesiredCapacity\":$DES,\"MaxSize\":3,\"TargetGroupARNs\":[\"arn:tg\"],\"Instances\":$I}]}"
   fi;;
 "autoscaling update-auto-scaling-group")
   for ((i=0;i<${#args[@]};i++)); do [[ "${args[i]}" == "--desired-capacity" ]] && des="${args[i+1]}"; done
   [[ "$des" == "0" ]] && echo off > "$D/state" || echo on > "$D/state";;
 "autoscaling describe-scaling-activities") echo '{"Activities":[]}';;
 "elbv2 describe-target-health")
   if [[ "$ST" == "on" ]]; then echo '{"TargetHealthDescriptions":[{"Target":{"Id":"i-aaa"},"TargetHealth":{"State":"healthy"}},{"Target":{"Id":"i-bbb"},"TargetHealth":{"State":"healthy"}}]}'; else echo '{"TargetHealthDescriptions":[]}'; fi;;
 "elbv2 describe-target-groups") echo '{"TargetGroups":[{"LoadBalancerArns":["arn:lb"]}]}';;
 "elbv2 describe-load-balancers") echo '{"LoadBalancers":[{"LoadBalancerName":"alb-v2","State":{"Code":"active"},"DNSName":"alb.example"}]}';;
 "rds describe-db-instances") echo "{\"DBInstances\":[{\"DBInstanceStatus\":\"${MOCK_RDS:-available}\"}]}";;
 "ec2 describe-instances") echo '{"Reservations":[{"Instances":[{"State":{"Name":"running"}}]}]}';;
 *) echo "LLAMADA NO PREVISTA: $*" >&2; echo "UNEXPECTED $*" >> "$D/calls.log"; exit 9;;
esac
