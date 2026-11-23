#!/usr/bin/env bash
# Comprobaciones de SOLO LECTURA en AWS (Academy) para la viabilidad de la integración AWS-OCI (v2, auditada).
# NO SE HA EJECUTADO. Requiere (1) autorización explícita y exacta de la usuaria (se compara el SHA-256 de este archivo) y (2) que la propia usuaria haya iniciado el laboratorio de Academy
# (Start Lab): este script NO inicia el laboratorio, ni recursos, ni nada.
#
# Garantías de diseño:
#  - Solo llama a `aws` con acciones de consulta: `describe-*` y `get-caller-identity` (y `simulate-principal-policy`, SOLO en la sección opcional `permisos`: simula políticas, no ejecuta las acciones).
#  - Nada de create/modify/delete/start/stop/reboot/run/terminate/put/attach/authorize/allocate/associate, ni `configure`, ni `aws sso`, ni lectura de ~/.aws.
#  - No instala ni repara nada: si falta la CLI o las credenciales caducaron o falta un permiso, SE DETIENE y lo dice (sin intentar arreglarlo).
#  - Toda la salida (también los errores) pasa por un filtro propio que oculta cuenta, ARN, IDs de recursos, IP, correos, claves de acceso, tokens, secretos y el usuario de sesión de Academy.
#  - De la identidad solo se imprime el NOMBRE DEL ROL (no la cuenta ni la sesión).
# Uso:  NEXO_READONLY_VIABILIDAD=YES scripts/multicloud/viabilidad-readonly-aws.sh [estado|rds|parametros|red|permisos|todo]
#       `todo` (por defecto) = estado + rds + parametros + red. `permisos` es opcional y se pide aparte.
set -uo pipefail
[[ "${NEXO_READONLY_VIABILIDAD:-}" == "YES" ]] || { echo "Solo lectura, pero requiere autorización: exporta NEXO_READONLY_VIABILIDAD=YES" >&2; exit 2; }
command -v aws >/dev/null 2>&1 || { echo "DETENIDO: falta la CLI de AWS (aws). No se instala nada." >&2; exit 2; }
PROFILE="${AWS_PROFILE:-nexoeventos-lab}"; REGION="${AWS_REGION:-us-east-1}"; RDS_ID="${RDS_ID:-nexoeventos-academy-postgres}"
sec="${1:-todo}"
case "$sec" in estado|rds|parametros|red|permisos|todo) ;; *) echo "Sección desconocida: $sec" >&2; exit 2;; esac
want() { [[ "$sec" == "$1" || ( "$sec" == "todo" && "$1" != "permisos" ) ]]; }

mask() {
  sed -E \
    -e '/PRIVATE KEY/d' \
    -e '/^[+][-+]*[+]$/b' \
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
# Credenciales: las que la propia usuaria haya dejado en el entorno de ESTA terminal (práctica del proyecto: sesión del Learner Lab aislada) o, si no hay, el perfil indicado. El script solo comprueba si la variable existe; nunca la lee ni la imprime.
if [[ -n "${AWS_ACCESS_KEY_ID:-}" ]]; then OPTS=(--region "$REGION" --no-cli-pager --cli-connect-timeout 10 --cli-read-timeout 30)
else OPTS=(--profile "$PROFILE" --region "$REGION" --no-cli-pager --cli-connect-timeout 10 --cli-read-timeout 30); fi
abortar() { echo "DETENIDO: 'aws $1 $2' falló (código $3). Causa probable: el laboratorio de Academy no está iniciado o sus credenciales caducaron, o falta un permiso. El script NO intenta repararlo, reiniciar nada ni instalar nada." >&2; exit 3; }
# run: ejecuta una consulta y muestra su salida filtrada; si falla, se detiene.  raw: devuelve el valor SIN imprimirlo (la salida estándar y los avisos llegan mezclados: el valor es la última línea).
run() { local out rc; out="$(env AWS_PAGER= aws "${OPTS[@]}" "$@" 2>&1)"; rc=$?; printf '%s\n' "$out" | mask; [[ $rc -eq 0 ]] || abortar "$1" "$2" "$rc"; }
raw() { local out rc; out="$(env AWS_PAGER= aws "${OPTS[@]}" "$@" 2>&1)"; rc=$?; if [[ $rc -ne 0 ]]; then printf '%s\n' "$out" | mask >&2; abortar "$1" "$2" "$rc"; fi; printf '%s' "$out" | tail -n 1; }

echo "== 0. Identidad de la sesión (solo el nombre del rol; sin cuenta ni usuario)"
ARN="$(raw sts get-caller-identity --query Arn --output text)" || exit 3
[[ "$ARN" == arn:aws*:sts::*:assumed-role/* ]] || { echo "DETENIDO: tipo de credencial inesperado (no se imprime)." >&2; exit 3; }
echo "Rol: $(printf '%s' "$ARN" | sed -E 's#^.*:assumed-role/([^/]*)/.*$#\1#')   Región: $REGION"

if want estado; then
  echo "== 1. ¿Qué hay encendido o facturando? (solo estados; sin IDs)"
  echo "-- EC2";             run ec2 describe-instances --query 'Reservations[].Instances[].{estado:State.Name,tipo:InstanceType,lanzada:LaunchTime,nombre:Tags[?Key==`Name`]|[0].Value}' --output table
  echo "-- Auto Scaling";    run autoscaling describe-auto-scaling-groups --query 'AutoScalingGroups[].{nombre:AutoScalingGroupName,minimo:MinSize,deseada:DesiredCapacity,maximo:MaxSize,instancias:length(Instances)}' --output table
  echo "-- Balanceadores";   run elbv2 describe-load-balancers --query 'LoadBalancers[].{nombre:LoadBalancerName,estado:State.Code,tipo:Type,esquema:Scheme}' --output table
  echo "-- NAT gateways";    run ec2 describe-nat-gateways --filter Name=state,Values=pending,available --query 'NatGateways[].{estado:State}' --output table
  echo "-- IP elásticas";    run ec2 describe-addresses --query 'Addresses[].{dominio:Domain,asociada:AssociationId!=null}' --output table
  echo "-- Volúmenes EBS";   run ec2 describe-volumes --query 'Volumes[].{estado:State,GiB:Size,tipo:VolumeType}' --output table
  echo "-- RDS (todas las instancias)"; run rds describe-db-instances --query 'DBInstances[].{nombre:DBInstanceIdentifier,estado:DBInstanceStatus,clase:DBInstanceClass,multiAZ:MultiAZ,GiB:AllocatedStorage}' --output table
fi

if want rds; then
  echo "== 2. Instancia RDS: versión, Multi-AZ, grupo de parámetros, acceso público, almacenamiento"
  run rds describe-db-instances --db-instance-identifier "$RDS_ID" --query 'DBInstances[0].{Estado:DBInstanceStatus,Motor:Engine,Version:EngineVersion,Clase:DBInstanceClass,MultiAZ:MultiAZ,PublicoAccesible:PubliclyAccessible,Grupos:DBParameterGroups[].[DBParameterGroupName,ParameterApplyStatus],AlmacenGiB:AllocatedStorage,AlmacenMaxGiB:MaxAllocatedStorage,Retencion:BackupRetentionPeriod,CA:CACertificateIdentifier,SubredGrupo:DBSubnetGroup.DBSubnetGroupName}' --output json
  echo "-- eventos de RDS de los últimos 14 días (paradas y arranques, incluidos los automáticos tras 7 días detenida)"
  run rds describe-events --source-type db-instance --source-identifier "$RDS_ID" --duration 20160 --query 'Events[?contains(Message, `started`) || contains(Message, `stopped`)].[Date,Message]' --output text
  echo "-- grupos de parámetros existentes (¿hay alguno personalizado?)"
  run rds describe-db-parameter-groups --query 'DBParameterGroups[].[DBParameterGroupName,DBParameterGroupFamily]' --output text
  echo "-- versión de motor 18.3: familia y capacidades declaradas"
  run rds describe-db-engine-versions --engine postgres --engine-version 18.3 --query 'DBEngineVersions[].{Version:EngineVersion,Familia:DBParameterGroupFamily,SoportaReplicaDeLectura:SupportsReadReplica,SoportaFailoverDeSlotsLogicos:SupportsLogicalReplicationSlotFailover}' --output json
fi

if want parametros; then
  echo "== 3. Parámetros relevantes del grupo por defecto de PostgreSQL 18 (IsModifiable = si se pueden cambiar en un grupo PERSONALIZADO)"
  run rds describe-db-parameters --db-parameter-group-name default.postgres18 \
    --query "Parameters[?ParameterName=='synchronous_standby_names' || ParameterName=='synchronous_commit' || ParameterName=='rds.logical_replication' || ParameterName=='wal_level' || ParameterName=='max_wal_senders' || ParameterName=='max_replication_slots' || ParameterName=='max_logical_replication_workers' || ParameterName=='max_slot_wal_keep_size' || ParameterName=='wal_sender_timeout' || ParameterName=='rds.force_ssl' || ParameterName=='rds.replica_identity_full' || ParameterName=='idle_in_transaction_session_timeout' || ParameterName=='statement_timeout' || ParameterName=='tcp_keepalives_idle'].[ParameterName,ParameterValue,IsModifiable,ApplyType,Source]" --output table
fi

if want red; then
  echo "== 4. Red existente (VPC, subredes, rutas, SG y VPN) para valorar un camino hacia OCI"
  run ec2 describe-vpcs --query 'Vpcs[].{cidr:CidrBlock,porDefecto:IsDefault}' --output table
  run ec2 describe-subnets --query 'Subnets[].{cidr:CidrBlock,zona:AvailabilityZone,ipPublicaAlLanzar:MapPublicIpOnLaunch,nombre:Tags[?Key==`Name`]|[0].Value}' --output table
  run ec2 describe-route-tables --query 'RouteTables[].{nombre:Tags[?Key==`Name`]|[0].Value,rutas:Routes[].[DestinationCidrBlock,GatewayId]}' --output json
  run ec2 describe-security-groups --query 'SecurityGroups[].{nombre:GroupName,entradas:IpPermissions[].[IpProtocol,FromPort,ToPort]}' --output json
  run ec2 describe-vpn-gateways --query 'VpnGateways[].{estado:State,tipo:Type}' --output table
fi

if want permisos; then
  echo "== 5. (Opcional) Permisos del rol para los pasos de la integración: SIMULACIÓN de políticas (no ejecuta ninguna de las acciones; los nombres de acción son solo texto)"
  ROLE_ARN="$(printf '%s' "$ARN" | sed -E 's#:assumed-role/([^/]*)/.*#:role/\1#; s#:sts:#:iam:#')"
  run iam simulate-principal-policy --policy-source-arn "$ROLE_ARN" \
    --action-names rds:CreateDBParameterGroup rds:ModifyDBParameterGroup rds:ModifyDBInstance rds:RebootDBInstance rds:CreateDBInstanceReadReplica rds:DescribeDBParameters \
                   ec2:CreateSecurityGroup ec2:AuthorizeSecurityGroupIngress ec2:RunInstances ec2:AllocateAddress ec2:CreateVpnGateway ec2:CreateVpnConnection ec2:CreateTransitGateway \
                   s3:PutObject secretsmanager:GetSecretValue iam:CreateUser iam:CreateAccessKey \
    --query 'EvaluationResults[].{accion:EvalActionName,decision:EvalDecision}' --output table
fi
echo "== fin (solo consultas; nada se creó, modificó, inició ni detuvo; no se instaló nada)"
