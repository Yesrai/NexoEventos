#!/usr/bin/env bash
# Consultas de SOLO LECTURA en AWS para planificar (sin ejecutar) la eliminación del ALB de V2 y la parada temporal de RDS (10-nov-2026).
# Autorizado por la usuaria SOLO como comprobaciones de lectura; NO modifica nada. Defensa en ejecución: `run` y `raw` rechazan cualquier acción que no sea describe-*, list-* o get-caller-identity.
# Salida enmascarada (cuenta, ARN, IDs de recursos, IP, correos, claves y tokens). Se detiene ante cualquier error (credenciales caducadas o permiso ausente) sin intentar repararlo.
# Uso:  NEXO_READONLY_VIABILIDAD=YES scripts/multicloud/aws-planificacion-solo-lectura.sh
set -uo pipefail
[[ "${NEXO_READONLY_VIABILIDAD:-}" == "YES" ]] || { echo "Solo lectura, pero requiere autorización: exporta NEXO_READONLY_VIABILIDAD=YES" >&2; exit 2; }
command -v aws >/dev/null 2>&1 || { echo "DETENIDO: falta la CLI de AWS. No se instala nada." >&2; exit 2; }
PROFILE="${AWS_PROFILE:-nexoeventos-lab}"; REGION="${AWS_REGION:-us-east-1}"; RDS_ID="${RDS_ID:-nexoeventos-academy-postgres}"; ALB_NAME="${ALB_NAME:-nexoeventos-academy-v2-alb}"
mask() {
  sed -E \
    -e '/PRIVATE KEY/d' -e '/^[+][-+]*[+]$/b' \
    -e 's/arn:aws[A-Za-z-]*:[^"[:space:],]*/<arn>/g' \
    -e 's/(^|[^0-9])[0-9]{12}([^0-9]|$)/\1<id>\2/g' -e 's/(^|[^0-9])[0-9]{12}([^0-9]|$)/\1<id>\2/g' \
    -e 's/A[SK]IA[0-9A-Z]{16}/<clave-de-acceso>/g' \
    -e 's/(aws_secret_access_key|aws_session_token|[Ss]ecretAccessKey|[Ss]essionToken|[Ss]ecurityToken|[Pp]assword|[Ss]ignature|[Aa]uthorization)[^ ]*[ ]*[:=][ "]*[^ ",]+/\1=<oculto>/g' \
    -e 's/user[0-9]+=[A-Za-z_]+/<usuario>/g' \
    -e 's/(i|vpc|subnet|sg|ami|snap|vol|eni|rtb|igw|nat|eipalloc|eipassoc|lt|vgw)-[0-9a-f]{8,17}/<\1>/g' \
    -e 's/[A-Za-z0-9+\/=_.-]{40,}/<largo-oculto>/g' \
    -e 's/(^|[^0-9.])[0-9]{1,3}(\.[0-9]{1,3}){3}([^0-9.]|$)/\1<ip>\3/g' \
    -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<correo>/g'
}
if [[ -n "${AWS_ACCESS_KEY_ID:-}" ]]; then OPTS=(--region "$REGION" --no-cli-pager --cli-connect-timeout 10 --cli-read-timeout 30)
else OPTS=(--profile "$PROFILE" --region "$REGION" --no-cli-pager --cli-connect-timeout 10 --cli-read-timeout 30); fi
abortar() { echo "DETENIDO: 'aws $1 $2' falló o no está permitido (código $3). El script NO intenta repararlo ni instalar nada." >&2; exit 3; }
solo_lectura() { [[ "$2" == describe-* || "$2" == list-* || "$2" == get-caller-identity ]] || abortar "$1" "$2" 4; }
run() { solo_lectura "$1" "$2"; local out rc; out="$(env AWS_PAGER= aws "${OPTS[@]}" "$@" 2>&1)"; rc=$?; printf '%s\n' "$out" | mask; [[ $rc -eq 0 ]] || abortar "$1" "$2" "$rc"; }
raw() { solo_lectura "$1" "$2"; local out rc; out="$(env AWS_PAGER= aws "${OPTS[@]}" "$@" 2>&1)"; rc=$?; if [[ $rc -ne 0 ]]; then printf '%s\n' "$out" | mask >&2; abortar "$1" "$2" "$rc"; fi; printf '%s' "$out" | tail -n 1; }

echo "== 0. Sesión"; ARN="$(raw sts get-caller-identity --query Arn --output text)" || exit 3
[[ "$ARN" == arn:aws*:sts::*:assumed-role/* ]] || { echo "DETENIDO: tipo de credencial inesperado." >&2; exit 3; }
echo "Rol: $(printf '%s' "$ARN" | sed -E 's#^.*:assumed-role/([^/]*)/.*$#\1#')"

echo; echo "== A. ALB de V2, listeners, reglas, target groups y dependencias"
LB="$(raw elbv2 describe-load-balancers --names "$ALB_NAME" --query 'LoadBalancers[0].LoadBalancerArn' --output text)" || exit 3
[[ "$LB" == arn:aws*:elasticloadbalancing:*:loadbalancer/app/* ]] || { echo "DETENIDO: no se identificó el ALB $ALB_NAME." >&2; exit 3; }
run elbv2 describe-load-balancers --names "$ALB_NAME" --query 'LoadBalancers[].{nombre:LoadBalancerName,estado:State.Code,tipo:Type,esquema:Scheme,creado:CreatedTime,zonas:length(AvailabilityZones),gruposDeSeguridad:length(SecurityGroups)}' --output table
echo "-- atributos (protección contra eliminación, tiempo de inactividad, registros de acceso)"
run elbv2 describe-load-balancer-attributes --load-balancer-arn "$LB" --query 'Attributes[?Key==`deletion_protection.enabled` || Key==`idle_timeout.timeout_seconds` || Key==`access_logs.s3.enabled`].{clave:Key,valor:Value}' --output table
echo "-- listeners"
run elbv2 describe-listeners --load-balancer-arn "$LB" --query 'Listeners[].{puerto:Port,protocolo:Protocol,politicaTLS:SslPolicy,accionPorDefecto:DefaultActions[0].Type,certificados:length(Certificates || `[]`)}' --output table
for L in $(raw elbv2 describe-listeners --load-balancer-arn "$LB" --query 'Listeners[].ListenerArn' --output text); do
  echo "-- reglas del listener"; run elbv2 describe-rules --listener-arn "$L" --query 'Rules[].{prioridad:Priority,porDefecto:IsDefault,condiciones:length(Conditions),acciones:Actions[0].Type}' --output table
done
echo "-- target groups del ALB y salud de sus destinos"
run elbv2 describe-target-groups --load-balancer-arn "$LB" --query 'TargetGroups[].{nombre:TargetGroupName,puerto:Port,protocolo:Protocol,rutaDeSalud:HealthCheckPath,tipo:TargetType}' --output table
for TG in $(raw elbv2 describe-target-groups --load-balancer-arn "$LB" --query 'TargetGroups[].TargetGroupArn' --output text); do
  run elbv2 describe-target-health --target-group-arn "$TG" --query 'length(TargetHealthDescriptions)' --output text
done
echo "-- interfaces de red del ALB (se liberan al eliminarlo)"
run ec2 describe-network-interfaces --filters 'Name=description,Values=ELB app/nexoeventos-academy-v2-alb/*' --query 'NetworkInterfaces[].{estado:Status,zona:AvailabilityZone,tipo:InterfaceType,ipPublica:Association.PublicIp!=null}' --output table
echo "-- Auto Scaling de V2 (su grupo de destino es el del ALB)"
run autoscaling describe-auto-scaling-groups --query 'AutoScalingGroups[].{nombre:AutoScalingGroupName,minimo:MinSize,deseada:DesiredCapacity,maximo:MaxSize,instancias:length(Instances),gruposDeDestino:length(TargetGroupARNs)}' --output table
echo "-- grupos de seguridad de V2 y reglas"
run ec2 describe-security-groups --filters 'Name=group-name,Values=*v2*' --query 'SecurityGroups[].{nombre:GroupName,entradas:length(IpPermissions),salidas:length(IpPermissionsEgress)}' --output table
echo "-- certificados de ACM (el certificado importado no lo gestiona Terraform)"
run acm list-certificates --query 'CertificateSummaryList[].{dominio:DomainName,estado:Status,tipo:Type}' --output table
echo "-- plantillas de lanzamiento, imágenes (AMI) e instantáneas propias (cobran almacenamiento)"
run ec2 describe-launch-templates --query 'LaunchTemplates[].{nombre:LaunchTemplateName,versiones:LatestVersionNumber}' --output table
run ec2 describe-images --owners self --query 'Images[].{nombre:Name,estado:State,GiB:BlockDeviceMappings[0].Ebs.VolumeSize,creada:CreationDate}' --output table
run ec2 describe-snapshots --owner-ids self --query 'Snapshots[].{GiB:VolumeSize,estado:State,iniciada:StartTime}' --output table

echo; echo "== B. IP elásticas: a qué están asociadas"
run ec2 describe-addresses --query 'Addresses[].{dominio:Domain,asociada:AssociationId!=null,aInstancia:InstanceId!=null,aInterfaz:NetworkInterfaceId!=null,etiqueta:Tags[?Key==`Name`]|[0].Value}' --output table
ENIS="$(raw ec2 describe-addresses --query 'Addresses[?NetworkInterfaceId!=null].NetworkInterfaceId' --output text)" || exit 3
[[ -n "$ENIS" && "$ENIS" != "None" ]] && run ec2 describe-network-interfaces --network-interface-ids $ENIS --query 'NetworkInterfaces[].{descripcion:Description,estado:Status,tipo:InterfaceType,instanciaAdjunta:Attachment.InstanceId!=null,zona:AvailabilityZone}' --output table
echo "-- instancias EC2 (¿a cuál pertenece cada IP?)"
run ec2 describe-instances --query 'Reservations[].Instances[].{nombre:Tags[?Key==`Name`]|[0].Value,estado:State.Name,ipPublica:PublicIpAddress!=null}' --output table

echo; echo "== C. RDS: copias disponibles y condiciones para detenerla"
run rds describe-db-instances --db-instance-identifier "$RDS_ID" --query 'DBInstances[0].{estado:DBInstanceStatus,multiAZ:MultiAZ,clase:DBInstanceClass,GiB:AllocatedStorage,maxGiB:MaxAllocatedStorage,cifrada:StorageEncrypted,retencionDias:BackupRetentionPeriod,ultimaRestauracionPosible:LatestRestorableTime,ventanaDeCopia:PreferredBackupWindow,ventanaDeMantenimiento:PreferredMaintenanceWindow,proteccionContraEliminacion:DeletionProtection,replicasDeLectura:length(ReadReplicaDBInstanceIdentifiers),esReplica:ReadReplicaSourceDBInstanceIdentifier!=null,modificacionesPendientes:PendingModifiedValues}' --output json
echo "-- instantáneas (manuales y automáticas)"
run rds describe-db-snapshots --db-instance-identifier "$RDS_ID" --query 'DBSnapshots[].{tipo:SnapshotType,estado:Status,creada:SnapshotCreateTime,GiB:AllocatedStorage,motor:EngineVersion}' --output table
echo "-- copias automáticas (ventana de restauración)"
run rds describe-db-instance-automated-backups --db-instance-identifier "$RDS_ID" --query 'DBInstanceAutomatedBackups[].{estado:Status,desde:RestoreWindow.EarliestTime,hasta:RestoreWindow.LatestTime,retencionDias:BackupRetentionPeriod}' --output table
echo "-- acciones de mantenimiento pendientes"
run rds describe-pending-maintenance-actions --filters "Name=db-instance-id,Values=$RDS_ID" --query 'PendingMaintenanceActions[].PendingMaintenanceActionDetails[].{accion:Action,aplicarDesde:AutoAppliedAfterDate,fechaLimite:ForcedApplyDate}' --output table
echo "-- eventos de RDS de los últimos 14 días (paradas, arranques y avisos)"
run rds describe-events --source-type db-instance --source-identifier "$RDS_ID" --duration 20160 --query 'Events[].[Date,Message]' --output text
echo "-- respaldos lógicos cifrados en S3 (prefijo database-backups/)"
BK="$(raw s3api list-buckets --query 'Buckets[?contains(Name, `nexoeventos`)].Name | [0]' --output text)" || exit 3
[[ -n "$BK" && "$BK" != "None" ]] && run s3api list-objects-v2 --bucket "$BK" --prefix database-backups/ --query 'Contents[].{objeto:Key,bytes:Size,fecha:LastModified}' --output table

echo; echo "== D. Otros costos que continúan (almacenamiento, alarmas, secretos, registros)"
run cloudwatch describe-alarms --query 'MetricAlarms[].{alarma:AlarmName,estado:StateValue}' --output table
run secretsmanager list-secrets --query 'SecretList[].{nombre:Name}' --output table
run logs describe-log-groups --query 'logGroups[].{grupo:logGroupName,bytes:storedBytes,retencionDias:retentionInDays}' --output table
echo; echo "== fin (solo consultas; nada se creó, modificó, inició ni detuvo; no se instaló nada)"
