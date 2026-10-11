#!/usr/bin/env bash
# Demuestra recepción real en CloudWatch Logs sin descargar mensajes.
# Genera una única solicitud GET con una ruta ficticia identificable y segura.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_cmd aws curl python3
verify_identity
require_change_approval

EC2_ID="$(ec2_instance_id)"
[[ "$(ec2_state "$EC2_ID")" == "running" ]] || die "La EC2 debe estar activa."
API_GROUP="/nexoeventos/$NEXO_ENV/api"
NGINX_GROUP="/nexoeventos/$NEXO_ENV/nginx"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MARKER="ev08-$STAMP"
START_MS="$(python3 -c 'import time; print(int((time.time()-600)*1000))')"
OUT="$PROJECT_ROOT/work/evidencias/$STAMP"
mkdir -p "$OUT"; chmod 700 "$OUT"; umask 077

API_RETENTION="$(aws logs describe-log-groups --log-group-name-prefix "$API_GROUP" \
  --query "logGroups[?logGroupName=='$API_GROUP'].retentionInDays | [0]" --output text)"
NGINX_RETENTION="$(aws logs describe-log-groups --log-group-name-prefix "$NGINX_GROUP" \
  --query "logGroups[?logGroupName=='$NGINX_GROUP'].retentionInDays | [0]" --output text)"
[[ "$API_RETENTION" == "7" && "$NGINX_RETENTION" == "7" ]] \
  || die "La retención efectiva no coincide con los 7 días definidos por Terraform."

# La simulación es una comprobación previa. La prueba efectiva es que aparezcan
# streams/eventos nuevos; no se amplía ni adjunta ninguna política.
PROFILE_NAME="$(aws ec2 describe-instances --instance-ids "$EC2_ID" \
  --query 'Reservations[0].Instances[0].IamInstanceProfile.Arn' --output text | awk -F/ '{print $NF}')"
ROLE_NAME="$(aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" \
  --query 'InstanceProfile.Roles[0].RoleName' --output text)"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
PERMISSIONS="$(aws iam simulate-principal-policy --policy-source-arn "arn:aws:iam::$ACCOUNT:role/$ROLE_NAME" \
  --action-names logs:CreateLogStream logs:PutLogEvents \
  --query 'EvaluationResults[].EvalDecision' --output text)" || die "No se pudieron simular los permisos del rol."
[[ "$PERMISSIONS" == *allowed* && "$(awk '{for(i=1;i<=NF;i++) if($i=="allowed") n++; print n+0}' <<<"$PERMISSIONS")" == "2" ]] \
  || die "El rol no tiene ambos permisos mínimos de escritura en Logs."

CODE="$(curl --connect-timeout 10 --max-time 20 -sS -o /dev/null -w '%{http_code}' \
  "https://$NEXO_FQDN/_observability/$MARKER")"
[[ "$CODE" == "204" ]] || die "La solicitud identificable devolvió HTTP $CODE."

NGINX_MATCHES=0
API_STREAMS=0
NGINX_STREAMS=0
API_LAST_EVENT=0
NGINX_LAST_EVENT=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  NGINX_MATCHES="$(aws logs filter-log-events --no-paginate --log-group-name "$NGINX_GROUP" --start-time "$START_MS" \
    --filter-pattern "\"$MARKER\"" --query 'length(events)' --output text 2>/dev/null)" || NGINX_MATCHES=0
  API_STREAMS="$(aws logs describe-log-streams --no-paginate --log-group-name "$API_GROUP" \
    --query 'length(logStreams)' --output text 2>/dev/null)" || API_STREAMS=0
  NGINX_STREAMS="$(aws logs describe-log-streams --no-paginate --log-group-name "$NGINX_GROUP" \
    --query 'length(logStreams)' --output text 2>/dev/null)" || NGINX_STREAMS=0
  API_LAST_EVENT="$(aws logs describe-log-streams --no-paginate --log-group-name "$API_GROUP" \
    --order-by LastEventTime --descending --limit 1 --query 'logStreams[0].lastEventTimestamp' --output text 2>/dev/null)" || API_LAST_EVENT=0
  NGINX_LAST_EVENT="$(aws logs describe-log-streams --no-paginate --log-group-name "$NGINX_GROUP" \
    --order-by LastEventTime --descending --limit 1 --query 'logStreams[0].lastEventTimestamp' --output text 2>/dev/null)" || NGINX_LAST_EVENT=0
  [[ "$API_LAST_EVENT" =~ ^[0-9]+$ ]] || API_LAST_EVENT=0
  [[ "$NGINX_LAST_EVENT" =~ ^[0-9]+$ ]] || NGINX_LAST_EVENT=0
  [[ "$NGINX_MATCHES" -ge 1 && "$API_STREAMS" -ge 1 && "$NGINX_STREAMS" -ge 1 \
     && "$API_LAST_EVENT" -ge "$START_MS" && "$NGINX_LAST_EVENT" -ge "$START_MS" ]] && break
  sleep 10
done
[[ "$NGINX_MATCHES" -ge 1 && "$API_STREAMS" -ge 1 && "$NGINX_STREAMS" -ge 1 \
   && "$API_LAST_EVENT" -ge "$START_MS" && "$NGINX_LAST_EVENT" -ge "$START_MS" ]] \
  || die "No se demostraron registros nuevos de ambos orígenes dentro de 120 s."

SENSITIVE_TOTAL=0
for group in "$API_GROUP" "$NGINX_GROUP"; do
  for pattern in password Authorization Cookie nexoeventos_session nexoeventos_csrf "token=" Bearer DUCKDNS_TOKEN; do
    count="$(aws logs filter-log-events --no-paginate --log-group-name "$group" --start-time "$START_MS" \
      --filter-pattern "\"$pattern\"" --query 'length(events)' --output text 2>/dev/null)" || count=error
    [[ "$count" =~ ^[0-9]+$ ]] || die "No se pudo completar el escaneo de patrones sensibles."
    SENSITIVE_TOTAL=$((SENSITIVE_TOTAL + count))
  done
done
[[ "$SENSITIVE_TOTAL" == "0" ]] || die "Se detectaron patrones sensibles; no usar la evidencia hasta revisar el origen."

ALARM="$(aws cloudwatch describe-alarms --alarm-name-prefix "$NEXO_NAME_PREFIX" \
  --query 'MetricAlarms[0].[StateValue,MetricName,Statistic,Threshold,Period,EvaluationPeriods,TreatMissingData,ActionsEnabled,length(AlarmActions),length(OKActions),length(InsufficientDataActions)]' \
  --output text)"
read -r ALARM_STATE ALARM_METRIC ALARM_STAT ALARM_THRESHOLD ALARM_PERIOD ALARM_EVAL ALARM_MISSING \
  ALARM_ENABLED ALARM_ACTIONS ALARM_OK_ACTIONS ALARM_INSUFFICIENT_ACTIONS <<<"$ALARM"

cat >"$OUT/ev08-observabilidad.md" <<EOF
# EV08 — verificación de recepción $STAMP

- Identidad/cuenta esperada y región verificadas (ID oculto): sí.
- Permisos simulados del rol: CreateLogStream=allowed; PutLogEvents=allowed.
- Prueba efectiva: solicitud HTTPS ficticia identificable, HTTP $CODE, coincidencias en Nginx=$NGINX_MATCHES.
- Streams con eventos nuevos en la ventana: FastAPI=$API_STREAMS; Nginx=$NGINX_STREAMS.
- Patrones sensibles en la ventana comprobada: $SENSITIVE_TOTAL.
- Retención efectiva: FastAPI=${API_RETENTION} días; Nginx=${NGINX_RETENTION} días. Administrada por Terraform; el agente no llama PutRetentionPolicy.

Alarma: estado=$ALARM_STATE; métrica=$ALARM_METRIC; estadística=$ALARM_STAT; umbral=$ALARM_THRESHOLD; periodo=${ALARM_PERIOD}s; evaluaciones=$ALARM_EVAL; datos ausentes=$ALARM_MISSING; acciones habilitadas=$ALARM_ENABLED; AlarmActions=$ALARM_ACTIONS; OKActions=$ALARM_OK_ACTIONS; InsufficientDataActions=$ALARM_INSUFFICIENT_ACTIONS.

No se descargaron ni guardaron mensajes, IDs de cuenta, nombres de streams, IP, cookies, cabeceras, cuerpos o tokens.
EOF
chmod 600 "$OUT/ev08-observabilidad.md"
record "observability verified marker=$MARKER nginx_matches=$NGINX_MATCHES api_streams=$API_STREAMS"
echo "EV08 verificada: ambos orígenes tienen streams y la solicitud sanitizada fue recibida."
echo "Evidencia protegida: work/evidencias/$STAMP/ev08-observabilidad.md"
