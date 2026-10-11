#!/usr/bin/env bash
# Inventario SOLO LECTURA y sanitizado para EV02, EV03, EV04, EV06, EV07 y EV08.
# Genera work/evidencias/<fecha>/ (ignorado por Git). Revisar manualmente antes de
# copiar extractos a docs/evidencias/EVxx/. No cambia recursos AWS.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_cmd aws python3
verify_identity

SAN="$PROJECT_ROOT/scripts/cloud/sanitize.py"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$PROJECT_ROOT/work/evidencias/$STAMP"
mkdir -p "$OUT"; chmod 700 "$OUT"; umask 077
HOURS="${NEXO_LOG_SCAN_HOURS:-24}"

cap() { # cap <archivo> <comando aws...>
  local file="$1"; shift
  if "$@" --output json 2>"$OUT/.err" | python3 "$SAN" >"$OUT/$file"; then
    log "capturado $file"
  else
    log "no se pudo capturar $file: $(python3 "$SAN" <"$OUT/.err" | head -n1)"
  fi
}

VPC_IDS="$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=$NEXO_NAME_PREFIX-vpc" --query 'Vpcs[].VpcId' --output text)"
[[ "$(awk '{print NF}' <<<"$VPC_IDS")" == "1" ]] || die "Se esperaba exactamente una VPC $NEXO_NAME_PREFIX-vpc."
VPC_ID="$VPC_IDS"

# EV02 — VPC
cap ev02-vpc.json aws ec2 describe-vpcs --vpc-ids "$VPC_ID" \
  --query 'Vpcs[0].{Cidr:CidrBlock,Estado:State,Tags:Tags}'
cap ev02-vpc-dns.json aws ec2 describe-vpc-attribute --vpc-id "$VPC_ID" --attribute enableDnsHostnames
# EV03 — subredes, rutas, IGW
cap ev03-subnets.json aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[].{Nombre:Tags[?Key==`Name`]|[0].Value,Cidr:CidrBlock,Zona:AvailabilityZone,IpPublicaAuto:MapPublicIpOnLaunch,Id:SubnetId}'
cap ev03-route-tables.json aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'RouteTables[].{Nombre:Tags[?Key==`Name`]|[0].Value,Rutas:Routes[].{Destino:DestinationCidrBlock,Gateway:GatewayId},Asociaciones:Associations[].{Subred:SubnetId,Principal:Main}}'
cap ev03-igw.json aws ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=$VPC_ID" \
  --query 'InternetGateways[].{Id:InternetGatewayId,Adjuntos:Attachments}'
# EV04 — security groups (reglas efectivas)
cap ev04-security-groups.json aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[].{Nombre:GroupName,Id:GroupId,Entrada:IpPermissions[].{Proto:IpProtocol,Desde:FromPort,Hasta:ToPort,Cidr:IpRanges[].CidrIp,SG:UserIdGroupPairs[].GroupId},Salida:IpPermissionsEgress[].{Proto:IpProtocol,Desde:FromPort,Hasta:ToPort,Cidr:IpRanges[].CidrIp,SG:UserIdGroupPairs[].GroupId}}'
# EV05 — EC2 (sin IP completa)
cap ev05-ec2.json aws ec2 describe-instances --filters "Name=tag:Name,Values=$EC2_NAME_TAG" \
  --query 'Reservations[].Instances[].{Id:InstanceId,Tipo:InstanceType,Estado:State.Name,Zona:Placement.AvailabilityZone,Ami:ImageId,IMDSv2:MetadataOptions.HttpTokens,IpPublica:PublicIpAddress,Subred:SubnetId,Volumenes:BlockDeviceMappings[].Ebs.VolumeId}'
# EV06 — RDS privado
cap ev06-rds.json aws rds describe-db-instances --db-instance-identifier "$RDS_ID" \
  --query 'DBInstances[0].{Motor:Engine,Version:EngineVersion,Clase:DBInstanceClass,Estado:DBInstanceStatus,Publico:PubliclyAccessible,MultiAZ:MultiAZ,Cifrado:StorageEncrypted,GiB:AllocatedStorage,MaxGiB:MaxAllocatedStorage,RetencionBackupDias:BackupRetentionPeriod,SubnetGroup:DBSubnetGroup.DBSubnetGroupName,SG:VpcSecurityGroups[].VpcSecurityGroupId}'
# EV07 — respaldos (metadatos, nunca contenido)
cap ev07-rds-snapshots.json aws rds describe-db-snapshots --db-instance-identifier "$RDS_ID" \
  --query 'DBSnapshots[].{Tipo:SnapshotType,Creado:SnapshotCreateTime,Estado:Status,Cifrado:Encrypted,GiB:AllocatedStorage}'
BUCKET=""
if BUCKET="$(private_bucket)"; then
  cap ev07-s3-public-access.json aws s3api get-public-access-block --bucket "$BUCKET"
  cap ev07-s3-versioning.json aws s3api get-bucket-versioning --bucket "$BUCKET"
  cap ev07-s3-encryption.json aws s3api get-bucket-encryption --bucket "$BUCKET"
  cap ev07-s3-backups.json aws s3api list-objects-v2 --bucket "$BUCKET" --prefix backups/database/ \
    --query 'Contents[].{Fecha:LastModified,Bytes:Size,Clase:StorageClass}'
else
  log "bucket privado esperado no accesible; EV07 S3 queda pendiente"
fi
# EV08 — CloudWatch
cap ev08-log-groups.json aws logs describe-log-groups --log-group-name-prefix "/nexoeventos/" \
  --query 'logGroups[].{Grupo:logGroupName,RetencionDias:retentionInDays,Bytes:storedBytes}'
cap ev08-alarm.json aws cloudwatch describe-alarms --alarm-name-prefix "$NEXO_NAME_PREFIX" \
  --query 'MetricAlarms[].{Alarma:AlarmName,Estado:StateValue,Metrica:MetricName,Estadistica:Statistic,Umbral:Threshold,Periodo:Period,Evaluaciones:EvaluationPeriods,DatosAusentes:TreatMissingData,AccionesHabilitadas:ActionsEnabled,AlarmActions:length(AlarmActions),OKActions:length(OKActions),InsufficientDataActions:length(InsufficientDataActions),Actualizado:StateUpdatedTimestamp}'

# EV08 — búsqueda de fugas en logs: solo cuenta coincidencias, nunca imprime mensajes.
START_MS="$(python3 -c "import time; print(int((time.time() - $HOURS*3600) * 1000))")"
{
  echo "# Búsqueda de datos sensibles en CloudWatch Logs (últimas $HOURS h)"
  echo
  echo "| Grupo | Patrón | Coincidencias |"
  echo "|---|---|---:|"
  for group in $(aws logs describe-log-groups --log-group-name-prefix "/nexoeventos/" --query 'logGroups[].logGroupName' --output text); do
    for pattern in password Authorization Cookie nexoeventos_session nexoeventos_csrf "token=" Bearer DUCKDNS_TOKEN; do
      n="$(aws logs filter-log-events --log-group-name "$group" --start-time "$START_MS" \
            --filter-pattern "\"$pattern\"" --query 'length(events)' --output text 2>/dev/null || echo error)"
      echo "| $group | \`$pattern\` | $n |"
    done
  done
  echo
  echo "Nota: filter-log-events devuelve como máximo una página; un valor 0 en todas las filas es la evidencia esperada."
} >"$OUT/ev08-log-scan.md"
log "capturado ev08-log-scan.md"

rm -f "$OUT/.err"
# Control final: ningún archivo debe conservar ID de cuenta ni endpoint.
if grep -RIEq '(^|[^0-9])[0-9]{12}([^0-9]|$)|rds\.amazonaws\.com' "$OUT"; then
  die "La sanitización dejó posibles identificadores en $OUT; revisar antes de usar."
fi
echo "Inventario sanitizado en: work/evidencias/$STAMP"
echo "Siguiente paso: revisar cada archivo y copiar solo extractos a docs/evidencias/EVxx/."
