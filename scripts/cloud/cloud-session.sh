#!/usr/bin/env bash
# Arranque, comprobación y apagado controlado de la V1 AWS de NexoEventos.
#   status  solo lectura: estados EC2/RDS y fecha límite de reinicio automático de RDS.
#   check   solo lectura: DNS, HTTPS, certificado, health y respaldos.
#   start   cambia AWS: inicia RDS, luego EC2, y ejecuta check.
#   stop    cambia AWS: verifica respaldos, detiene EC2 y RDS y espera 'stopped'.
# start/stop exigen NEXO_ALLOW_CLOUD_CHANGES=YES. Nunca imprime IDs de cuenta, endpoints ni secretos.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

ACTION="${1:-}"
[[ "$ACTION" =~ ^(status|check|start|stop)$ ]] || { echo "Uso: $0 {status|check|start|stop}" >&2; exit 2; }
require_cmd aws python3 curl openssl dig

verify_identity
EC2_ID="$(ec2_instance_id)"
[[ -n "$EC2_ID" && "$EC2_ID" != "None" && "$EC2_ID" != *$'\t'* ]] || die "No se encontró exactamente una EC2 con tag Name=$EC2_NAME_TAG."

rds_autostart_deadline() {
  # El límite de 7 días solo corre mientras la RDS está detenida; se calcula desde el último evento exacto "DB instance stopped".
  # Los eventos de arranque automático ("... being started due to it exceeding the maximum allowed time being stopped")
  # también contienen la palabra "stopped": no son paradas y no deben contarse.
  local state t auto
  state="$(rds_status "$RDS_ID")"
  auto="$(aws rds describe-events --source-type db-instance --source-identifier "$RDS_ID" --duration 20160 \
        --query "Events[?contains(Message, 'being started due to it exceeding')].Date | [-1]" --output text 2>/dev/null || true)"
  if [[ "$state" != "stopped" ]]; then
    local extra=""
    [[ -n "$auto" && "$auto" != "None" ]] && extra="; último arranque automático por exceder 7 días: $auto"
    echo "no aplica: RDS en estado '$state' (el límite solo corre mientras está detenida)$extra"
    return
  fi
  t="$(aws rds describe-events --source-type db-instance --source-identifier "$RDS_ID" --duration 20160 \
        --query "Events[?Message=='DB instance stopped'].Date | [-1]" --output text 2>/dev/null || true)"
  if [[ -z "$t" || "$t" == "None" ]]; then echo "desconocida (sin evento de parada en 14 días)"; return; fi
  python3 - "$t" <<'PY'
import sys
from datetime import datetime, timedelta, timezone
stop = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
limit = stop + timedelta(days=7)
lima = timezone(timedelta(hours=-5))
left = limit - datetime.now(timezone.utc)
print(f"detenida {stop.astimezone(lima):%Y-%m-%d %H:%M} Lima -> reinicio automático aprox. {limit.astimezone(lima):%Y-%m-%d %H:%M} Lima (faltan {left.days} d {left.seconds // 3600} h)")
PY
}

do_status() {
  echo "EC2 $(mask_id "$EC2_ID"): $(ec2_state "$EC2_ID")"
  echo "RDS $RDS_ID: $(rds_status "$RDS_ID")"
  echo "RDS reinicio automático: $(rds_autostart_deadline)"
}

check_dns() {
  local ip resolved i
  ip="$(ec2_public_ip "$EC2_ID")"
  [[ "$ip" != "None" && -n "$ip" ]] || { echo "DNS: EC2 sin IPv4 pública (¿detenida?)"; return 1; }
  for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    resolved="$(dig +short A "$NEXO_FQDN" @1.1.1.1 | tail -n1)"
    if [[ "$resolved" == "$ip" ]]; then
      echo "DNS: $NEXO_FQDN -> $(mask_ip "$resolved") coincide con la EC2 [OK]"; return 0
    fi
    log "DNS aún apunta a $(mask_ip "$resolved"); EC2 tiene $(mask_ip "$ip"). Esperando timer DuckDNS (${i}/12)."
    sleep 30
  done
  echo "DNS: no coincide tras 6 min [FALLO]"; return 1
}

check_https() {
  local code redirect enddate issuer days ok=0
  redirect="$(curl --connect-timeout 10 --max-time 20 -sS -o /dev/null -w '%{http_code} %{redirect_url}' "http://$NEXO_FQDN/" || true)"
  [[ "$redirect" == 301\ https://* ]] && echo "HTTP->HTTPS: 301 [OK]" || { echo "HTTP->HTTPS: '$redirect' [FALLO]"; ok=1; }
  code="$(curl --connect-timeout 10 --max-time 20 -sS -o /dev/null -w '%{http_code}' "https://$NEXO_FQDN/" || true)"
  [[ "$code" == "200" ]] && echo "HTTPS /: 200 [OK]" || { echo "HTTPS /: $code [FALLO]"; ok=1; }
  code="$(curl --connect-timeout 10 --max-time 20 -sS -o /dev/null -w '%{http_code}' "https://$NEXO_FQDN/healthz" || true)"
  [[ "$code" == "200" ]] && echo "HTTPS /healthz (ready + BD): 200 [OK]" || { echo "HTTPS /healthz: $code [FALLO]"; ok=1; }
  code="$(curl --connect-timeout 10 --max-time 20 -sS -o /dev/null -w '%{http_code}' "https://$NEXO_FQDN/api/events" || true)"
  [[ "$code" == "200" ]] && echo "HTTPS /api/events: 200 [OK]" || { echo "HTTPS /api/events: $code [FALLO]"; ok=1; }
  enddate="$(echo | openssl s_client -servername "$NEXO_FQDN" -connect "$NEXO_FQDN:443" 2>/dev/null | openssl x509 -noout -enddate | cut -d= -f2)"
  issuer="$(echo | openssl s_client -servername "$NEXO_FQDN" -connect "$NEXO_FQDN:443" 2>/dev/null | openssl x509 -noout -issuer | sed 's/.*O *= *//; s/,.*//')"
  days="$(python3 - "$enddate" <<'PY'
import sys
from datetime import datetime, timezone
end = datetime.strptime(sys.argv[1].strip(), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
print((end - datetime.now(timezone.utc)).days)
PY
)"
  echo "Certificado: emisor $issuer, vence $enddate ($days días)"
  (( days >= 14 )) || { echo "Certificado: menos de 14 días [REVISAR renovación]"; ok=1; }
  return $ok
}

check_backups() {
  local bucket latest snap lrt
  bucket=""
  if bucket="$(private_bucket)"; then
    latest="$(aws s3api list-objects-v2 --bucket "$bucket" --prefix backups/database/ \
      --query 'sort_by(Contents, &LastModified)[-1].[LastModified, Size]' --output text 2>/dev/null || true)"
    if [[ -n "$latest" && "$latest" != "None" ]]; then
      echo "S3 (bucket privado, nombre oculto): último respaldo $(cut -f1 <<<"$latest"), $(cut -f2 <<<"$latest") bytes"
      echo "S3 antigüedad del último respaldo: $(( $(seconds_between "$(cut -f1 <<<"$latest" | sed 's/+00:00/Z/')" "$(utc_now)") / 3600 )) h (objetivo RPO <= 24 h)"
    else
      echo "S3: sin objetos en backups/database/ o lectura denegada [REVISAR]"
    fi
  else
    echo "S3: bucket esperado no accesible [REVISAR permiso/estado]"
  fi
  snap="$(aws rds describe-db-snapshots --db-instance-identifier "$RDS_ID" --snapshot-type manual \
    --query 'sort_by(DBSnapshots, &SnapshotCreateTime)[-1].[SnapshotCreateTime, Status, Encrypted, AllocatedStorage]' --output text 2>/dev/null || true)"
  echo "Snapshot manual más reciente: ${snap:-ninguno} (fecha, estado, cifrado, GiB)"
  lrt="$(aws rds describe-db-instances --db-instance-identifier "$RDS_ID" --query 'DBInstances[0].LatestRestorableTime' --output text 2>/dev/null || true)"
  echo "RDS LatestRestorableTime (backup automático): ${lrt:-None}"
}

do_check() {
  local rc=0
  echo "== Estado =="; do_status
  echo "== DNS =="; check_dns || rc=1
  echo "== HTTPS =="; check_https || rc=1
  echo "== Respaldos =="; check_backups
  record "check rc=$rc"
  return $rc
}

do_start() {
  require_change_approval
  log "Inicio solicitado. Revisa antes el consumo del panel Academy."
  record "start solicitado"
  if [[ "$(rds_status "$RDS_ID")" == "stopped" ]]; then
    aws rds start-db-instance --db-instance-identifier "$RDS_ID" >/dev/null
    record "rds start-db-instance aceptado"
  fi
  if ! wait_rds_status "$RDS_ID" available 2400; then
    record "start parcial: RDS no llegó a available; revisar antes de reintentar"
    die "Arranque parcial: comprueba RDS y consumo antes de reintentar."
  fi
  record "rds available"
  if [[ "$(ec2_state "$EC2_ID")" == "stopped" ]]; then
    aws ec2 start-instances --instance-ids "$EC2_ID" >/dev/null
    record "ec2 start-instances aceptado"
  fi
  if ! wait_ec2_state "$EC2_ID" running 900 || ! aws ec2 wait instance-status-ok --instance-ids "$EC2_ID"; then
    record "start parcial: RDS available; EC2 no superó comprobaciones"
    die "Arranque parcial: RDS quedó activa y puede seguir cobrando; revisa EC2 antes de reintentar."
  fi
  record "ec2 running + status ok"
  log "Cómputo activo. Comprobando servicio público..."
  do_check
}

do_stop() {
  require_change_approval
  echo "== Comprobación previa de respaldos =="; check_backups
  read -r -p "¿Respaldos y evidencias de esta sesión confirmados? Escribe DETENER para continuar: " answer
  [[ "$answer" == "DETENER" ]] || die "Apagado cancelado por la operadora."
  record "stop solicitado"
  if [[ "$(ec2_state "$EC2_ID")" == "running" ]]; then
    aws ec2 stop-instances --instance-ids "$EC2_ID" >/dev/null
    record "ec2 stop-instances aceptado"
  fi
  if ! wait_ec2_state "$EC2_ID" stopped 900; then
    record "stop parcial: EC2 no llegó a stopped; RDS no se modificó"
    die "Apagado parcial: revisa EC2; RDS conserva su estado anterior."
  fi
  record "ec2 stopped"; log "EC2 stopped."
  if [[ "$(rds_status "$RDS_ID")" == "available" ]]; then
    aws rds stop-db-instance --db-instance-identifier "$RDS_ID" >/dev/null
    record "rds stop-db-instance aceptado"
  fi
  if ! wait_rds_status "$RDS_ID" stopped 2400; then
    record "stop parcial: EC2 stopped; RDS no llegó a stopped"
    die "Apagado parcial: EC2 quedó detenida, pero RDS puede seguir cobrando; revisa su estado."
  fi
  record "rds stopped"
  do_status
  echo "Recordatorio: RDS se reiniciará sola a los 7 días; EBS, snapshots, S3, logs, alarma y secreto siguen cobrando."
}

case "$ACTION" in
  status) do_status ;;
  check) do_check ;;
  start) do_start ;;
  stop) do_stop ;;
esac
