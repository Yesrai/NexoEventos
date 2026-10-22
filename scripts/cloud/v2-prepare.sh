#!/usr/bin/env bash
# Pasos con EFECTO en AWS para preparar V2 (certificado, secreto compartido y AMI dorada). NO se ejecuta sin autorización explícita por paso:
# todos exigen NEXO_ALLOW_CLOUD_CHANGES=YES. Nunca imprime IDs de cuenta, secretos ni claves (solo ARN/IDs enmascarados donde corresponde).
#   v1-ec2-start    arranca SOLO la EC2 de V1 (no la RDS) para leer el certificado y el backend.env desde su propio disco
#   import-cert     importa el certificado Let's Encrypt de V1 en ACM (ejecutado en la EC2 de V1; guarda el ARN en work/operacion/v2-certificate-arn)
#   create-secret   crea el secreto compartido copiando /etc/nexoeventos/backend.env de V1 dentro de AWS (no sobrescribe)
#   v1-ec2-stop     detiene la EC2 de V1 otra vez
#   builder-launch  lanza la instancia TEMPORAL de construcción (SG propio sin entradas, IMDSv2, volumen cifrado)
#   builder-image   detiene el constructor y crea la AMI dorada (guarda el ID en work/operacion/v2-ami-id)
#   builder-delete  termina el constructor y borra su SG temporal
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
ACTION="${1:-}"
[[ "$ACTION" =~ ^(v1-ec2-start|import-cert|create-secret|v1-ec2-stop|builder-launch|builder-image|builder-delete)$ ]] || { sed -n 2,12p "$0" >&2; exit 2; }
require_cmd aws python3
verify_identity
require_change_approval
mkdir -p "$OPS_DIR"; chmod 700 "$OPS_DIR"; umask 077
TFV() { awk -F= -v k="$1" '$1 ~ "^[[:space:]]*"k"[[:space:]]*$" {gsub(/[[:space:]\"]/, "", $2); print $2; exit}' "$TFVARS"; }
BUILDER_TAG=nexoeventos-academy-v2-bake
BUILDER_SG=nexoeventos-academy-v2-bake-sg
V1_ID="$(ec2_instance_id)"

ssm_payload() { # $1 = script local, $2... = argumentos → JSON de SSM (el script viaja como heredoc de la propia orden; no hay secretos en él)
  python3 - "$@" <<'PY'
import json, shlex, sys
script, args = open(sys.argv[1], encoding="utf-8").read(), " ".join(shlex.quote(a) for a in sys.argv[2:])
print(json.dumps({"commands": ["cat > /tmp/v2-step.sh <<'NEXO_EOS'\n" + script + "\nNEXO_EOS", f"bash /tmp/v2-step.sh {args}; rc=$?; rm -f /tmp/v2-step.sh; exit $rc"]}))
PY
}

ssm_file() { # ejecuta un script local en la EC2 de V1 con el rol de la instancia y devuelve su salida
  local cid st
  cid="$(aws ssm send-command --instance-ids "$V1_ID" --document-name AWS-RunShellScript --comment "$2" --parameters "$(ssm_payload "$1" "${@:3}")" --query Command.CommandId --output text)"
  for _ in $(seq 60); do
    sleep 3
    st="$(aws ssm get-command-invocation --command-id "$cid" --instance-id "$V1_ID" --query Status --output text 2>/dev/null || echo Pending)"
    case "$st" in Success) aws ssm get-command-invocation --command-id "$cid" --instance-id "$V1_ID" --query StandardOutputContent --output text; return 0;;
      Failed|Cancelled|TimedOut) die "SSM $st: $(aws ssm get-command-invocation --command-id "$cid" --instance-id "$V1_ID" --query StandardErrorContent --output text | tail -c 300)";; esac
  done
  die "SSM sin respuesta"
}

case "$ACTION" in
  v1-ec2-start)
    [[ "$(ec2_state "$V1_ID")" == stopped ]] || die "La EC2 de V1 no está detenida."
    aws ec2 start-instances --instance-ids "$V1_ID" >/dev/null; record "v2-prepare: ec2 V1 start (solo EC2)"
    wait_ec2_state "$V1_ID" running 900; aws ec2 wait instance-status-ok --instance-ids "$V1_ID"
    log "EC2 de V1 en ejecución (la RDS NO se inició)." ;;
  v1-ec2-stop)
    aws ec2 stop-instances --instance-ids "$V1_ID" >/dev/null; record "v2-prepare: ec2 V1 stop"
    wait_ec2_state "$V1_ID" stopped 900; log "EC2 de V1 detenida." ;;
  import-cert)
    arn="$(ssm_file "$PROJECT_ROOT/deploy/v2/import-acm-certificate-on-v1.sh" "v2: importar certificado en ACM" "nexoeventos-demo.duckdns.org" | tr -d '[:space:]')"
    [[ "$arn" =~ ^arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/ ]] || die "ACM no devolvió un ARN válido."
    printf '%s\n' "$arn" >"$OPS_DIR/v2-certificate-arn"; record "v2-prepare: certificado importado en ACM"; log "Certificado importado (ARN guardado en work/operacion/v2-certificate-arn)." ;;
  create-secret)
    arn="$(ssm_file "$PROJECT_ROOT/deploy/v2/create-shared-secret-on-v1.sh" "v2: crear secreto compartido" | tr -d '[:space:]')"
    [[ "$arn" =~ ^arn:aws:secretsmanager: ]] || die "Secrets Manager no devolvió un ARN válido."
    record "v2-prepare: secreto compartido creado"; log "Secreto compartido creado (ARN oculto)." ;;
  builder-launch)
    vpc="$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=$NEXO_NAME_PREFIX-vpc" --query 'Vpcs[0].VpcId' --output text)"
    subnet="$(aws ec2 describe-subnets --filters "Name=tag:Name,Values=$NEXO_NAME_PREFIX-public-a" "Name=vpc-id,Values=$vpc" --query 'Subnets[0].SubnetId' --output text)"
    sg="$(aws ec2 create-security-group --group-name "$BUILDER_SG" --description "Constructor temporal de la AMI de NexoEventos V2 (sin entradas)" --vpc-id "$vpc" --query GroupId --output text)"
    aws ec2 revoke-security-group-egress --group-id "$sg" --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null
    aws ec2 authorize-security-group-egress --group-id "$sg" --ip-permissions '[{"IpProtocol":"tcp","FromPort":443,"ToPort":443,"IpRanges":[{"CidrIp":"0.0.0.0/0"}]},{"IpProtocol":"udp","FromPort":53,"ToPort":53,"IpRanges":[{"CidrIp":"0.0.0.0/0"}]},{"IpProtocol":"tcp","FromPort":53,"ToPort":53,"IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null
    iid="$(aws ec2 run-instances --image-id "$(TFV ec2_ami_id)" --instance-type t3.small --subnet-id "$subnet" --security-group-ids "$sg" --associate-public-ip-address \
      --iam-instance-profile "Name=$(TFV instance_profile_name)" --metadata-options HttpTokens=required,HttpEndpoint=enabled \
      --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3","Encrypted":true,"DeleteOnTermination":true}}]' \
      --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$BUILDER_TAG},{Key=Project,Value=NexoEventos},{Key=Purpose,Value=ami-bake}]" --query 'Instances[0].InstanceId' --output text)"
    record "v2-prepare: constructor lanzado"; wait_ec2_state "$iid" running 900; aws ec2 wait instance-status-ok --instance-ids "$iid"
    log "Constructor $(mask_id "$iid") en ejecución. Siguiente: NEXO_ALLOW_CLOUD_CHANGES=YES scripts/ansible-aws.sh bake" ;;
  builder-image)
    iid="$(aws ec2 describe-instances --filters "Name=tag:Name,Values=$BUILDER_TAG" "Name=instance-state-name,Values=running,stopped" --query 'Reservations[0].Instances[0].InstanceId' --output text)"
    [[ "$iid" =~ ^i- ]] || die "No hay constructor."
    aws ec2 stop-instances --instance-ids "$iid" >/dev/null; wait_ec2_state "$iid" stopped 900
    ami="$(aws ec2 create-image --instance-id "$iid" --name "nexoeventos-v2-$(date -u +%Y%m%dt%H%M%S)z" --description "NexoEventos V2 dorada: sin secretos ni certificados" \
      --tag-specifications "ResourceType=image,Tags=[{Key=Project,Value=NexoEventos},{Key=Stack,Value=v2}]" --query ImageId --output text)"
    aws ec2 wait image-available --image-ids "$ami"; printf '%s\n' "$ami" >"$OPS_DIR/v2-ami-id"; record "v2-prepare: AMI dorada creada"
    log "AMI creada: $(mask_id "$ami") (ID completo en work/operacion/v2-ami-id)." ;;
  builder-delete)
    iid="$(aws ec2 describe-instances --filters "Name=tag:Name,Values=$BUILDER_TAG" "Name=instance-state-name,Values=pending,running,stopping,stopped" --query 'Reservations[0].Instances[0].InstanceId' --output text)"
    [[ "$iid" =~ ^i- ]] && { aws ec2 terminate-instances --instance-ids "$iid" >/dev/null; aws ec2 wait instance-terminated --instance-ids "$iid"; }
    sg="$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$BUILDER_SG" --query 'SecurityGroups[0].GroupId' --output text)"
    [[ "$sg" =~ ^sg- ]] && aws ec2 delete-security-group --group-id "$sg"
    record "v2-prepare: constructor y SG temporal eliminados"; log "Constructor y SG temporal eliminados." ;;
esac
