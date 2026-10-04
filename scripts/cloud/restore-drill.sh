#!/usr/bin/env bash
# Ensayo de restauración cloud AISLADO y CRONOMETRADO.
# No conmuta aplicación ni DNS. Mide por separado:
# - desfase del punto recuperable;
# - tiempo hasta RDS disponible;
# - tiempo hasta datos comprobados contra una línea base exacta.
# El tiempo de recuperación del servicio completo queda pendiente de un ensayo
# con aplicación, DNS y HTTPS, y nunca se confunde con la restauración de datos.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_cmd aws python3 shasum

ACTION="${1:-}"
[[ "$ACTION" =~ ^(run|cleanup)$ ]] || { echo "Uso: $0 run [--pitr|snapshot-id] | cleanup <restore-id>" >&2; exit 2; }
verify_identity
require_change_approval

receipt_dir_for() {
  local target="$1" stamp="${1##*-restore-}"
  printf '%s/work/restauracion/%s\n' "$PROJECT_ROOT" "$stamp"
}

if [[ "$ACTION" == "cleanup" ]]; then
  TARGET="${2:-}"
  [[ "$TARGET" =~ ^${NEXO_NAME_PREFIX}-restore-[0-9]{8}t[0-9]{4}$ ]] || die "Identificador temporal inválido."
  OUT="$(receipt_dir_for "$TARGET")"
  RECEIPT="$OUT/recurso.json"
  [[ -f "$RECEIPT" && "$(stat -f '%Lp' "$RECEIPT" 2>/dev/null || stat -c '%a' "$RECEIPT")" == "600" ]] \
    || die "No existe el recibo local protegido de esta ejecución; cleanup se niega."
  RECEIPT_VALUES="$(python3 - "$RECEIPT" "$TARGET" "$AWS_REGION" <<'PY'
import json, sys
p, target, region = sys.argv[1:]
d = json.load(open(p))
if d.get("restore_id") != target or d.get("region") != region or not d.get("arn_sha256"):
    raise SystemExit("Recibo no coincide con destino/región.")
print(d["run_id"], d["arn_sha256"])
PY
)" || die "Recibo inválido."
  RUN_ID="$(awk '{print $1}' <<<"$RECEIPT_VALUES")"
  EXPECTED_ARN_HASH="$(awk '{print $2}' <<<"$RECEIPT_VALUES")"
  META="$(aws rds describe-db-instances --db-instance-identifier "$TARGET" \
    --query 'DBInstances[0].[DBInstanceArn,TagList[?Key==`Project`].Value|[0],TagList[?Key==`Purpose`].Value|[0],TagList[?Key==`ManagedBy`].Value|[0],TagList[?Key==`RunId`].Value|[0]]' --output text)" \
    || die "No se pudo inspeccionar el recurso temporal; no se elimina."
  ARN="$(awk '{print $1}' <<<"$META")"
  [[ "$(printf %s "$ARN" | shasum -a 256 | awk '{print $1}')" == "$EXPECTED_ARN_HASH" ]] \
    || die "ARN distinto del recibo; no se elimina."
  [[ "$(awk '{print $2, $3, $4, $5}' <<<"$META")" == "NexoEventos restore-drill manual-drill $RUN_ID" ]] \
    || die "Etiquetas de propiedad/ejecución no coinciden; no se elimina."
  read -r -p "Escribe el identificador exacto para eliminar SOLO la copia temporal: " answer
  [[ "$answer" == "$TARGET" ]] || die "Confirmación distinta; no se elimina."
  aws rds delete-db-instance --db-instance-identifier "$TARGET" --skip-final-snapshot --delete-automated-backups >/dev/null
  record "restore-drill cleanup solicitado $TARGET run=$RUN_ID"
  waited=0
  while aws rds describe-db-instances --db-instance-identifier "$TARGET" >/dev/null 2>&1; do
    (( waited >= 1800 )) && die "La eliminación no terminó en 1800 s; revisa el mismo identificador."
    sleep 30; waited=$((waited + 30))
  done
  record "restore-drill cleanup completado $TARGET run=$RUN_ID"
  echo "Instancia temporal exacta de esta ejecución eliminada."
  exit 0
fi

STAMP="$(date -u +%Y%m%dt%H%M)"
RESTORE_ID="$NEXO_NAME_PREFIX-restore-$STAMP"
OUT="$PROJECT_ROOT/work/restauracion/$STAMP"
mkdir -p "$OUT"; chmod 700 "$OUT"; umask 077
TL="$OUT/linea-de-tiempo.tsv"
PARAMS=""
SERVICE_PAUSED=0
mark() { printf '%s\t%s\n' "$1" "$(utc_now)" | tee -a "$TL" >&2; }
cleanup_local() { [[ -n "$PARAMS" ]] && rm -f "$PARAMS"; }
resume_if_needed() {
  cleanup_local
  if [[ "$SERVICE_PAUSED" == "1" ]]; then
    log "La API quedó pausada; intenta reanudarla de forma acotada por SSM."
    ssm_exec resume 120 "systemctl start nexoeventos-api.service" >/dev/null 2>&1 || \
      log "ERROR: no se pudo confirmar el reinicio de nexoeventos-api.service."
  fi
}
trap resume_if_needed EXIT

EC2_ID="$(ec2_instance_id)"
[[ "$(ec2_state "$EC2_ID")" == "running" ]] || die "La EC2 debe estar en ejecución para verificar por SSM."
[[ -z "$(aws rds describe-db-instances --query "DBInstances[?starts_with(DBInstanceIdentifier, '$NEXO_NAME_PREFIX-restore-')].DBInstanceIdentifier" --output text)" ]] \
  || die "Ya existe una instancia de restauración; límpiala antes de otro ensayo."

ssm_exec() { # etiqueta timeout comando
  local label="$1" timeout="$2" command="$3" cmd_id status waited=0
  PARAMS="$OUT/.ssm-${label}.json"
  python3 - "$command" "$timeout" >"$PARAMS" <<'PY'
import json, sys
print(json.dumps({"commands": [sys.argv[1]], "executionTimeout": [sys.argv[2]]}))
PY
  cmd_id="$(aws ssm send-command --instance-ids "$EC2_ID" --document-name AWS-RunShellScript \
    --comment "NexoEventos restore drill $label" --parameters "file://$PARAMS" --query 'Command.CommandId' --output text)"
  rm -f "$PARAMS"; PARAMS=""
  status="Pending"
  while [[ "$status" == "InProgress" || "$status" == "Pending" || "$status" == "Delayed" ]]; do
    (( waited >= timeout + 60 )) && { log "SSM $label excedió $((timeout + 60)) s."; return 1; }
    sleep 10; waited=$((waited + 10))
    status="$(aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$EC2_ID" --query Status --output text 2>/dev/null || echo Pending)"
  done
  aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$EC2_ID" \
    --query 'StandardOutputContent' --output text
  [[ "$status" == "Success" ]]
}

# Pausar escrituras es parte explícita del ensayo. Así la línea base lógica puede
# compararse con el punto recuperable, no solo con la existencia de un PITR.
read -r -p "Escribe PAUSAR para detener temporalmente la API y capturar la línea base: " answer
[[ "$answer" == "PAUSAR" ]] || die "Ensayo cancelado."
ssm_exec pause 120 "systemctl stop nexoeventos-api.service && ! systemctl is-active --quiet nexoeventos-api.service" >/dev/null
SERVICE_PAUSED=1
mark "T_pre_escrituras_pausadas"

VERIFY_BODY="$(<"$PROJECT_ROOT/deploy/verify-restore.sh")"
BASELINE_COMMAND="cat > /root/verify-restore.sh <<'NEXO_EOF'
$VERIFY_BODY
NEXO_EOF
chmod 700 /root/verify-restore.sh
/root/verify-restore.sh baseline
rc=\$?
rm -f /root/verify-restore.sh
exit \$rc"
BASELINE_OUTPUT="$(ssm_exec baseline 600 "$BASELINE_COMMAND")" || die "No se pudo capturar línea base; la API se intentará reanudar."
BASELINE_B64="$(awk -F= '$1=="BASELINE_B64"{print $2; exit}' <<<"$BASELINE_OUTPUT")"
[[ "$BASELINE_B64" =~ ^[A-Za-z0-9_-]+$ ]] || die "La línea base no fue válida."
BASELINE_TIME="$(utc_now)"
printf '%s\n' "$BASELINE_OUTPUT" | grep -v '^BASELINE_B64=' >"$OUT/linea-base.txt"
mark "T_base_datos_comprobados"

SNAPSHOT="${2:-}"
MODE="snapshot"
if [[ "$SNAPSHOT" == "--pitr" ]]; then
  MODE="pitr"; SNAPSHOT=""
  deadline=$(( $(date +%s) + 900 ))
  while :; do
    SNAP_TIME="$(aws rds describe-db-instances --db-instance-identifier "$RDS_ID" --query 'DBInstances[0].LatestRestorableTime' --output text)"
    [[ "$SNAP_TIME" != "None" ]] || die "Sin LatestRestorableTime."
    if python3 - "$SNAP_TIME" "$BASELINE_TIME" <<'PY'
from datetime import datetime
import sys
p=lambda s: datetime.fromisoformat(s.replace("Z","+00:00"))
raise SystemExit(0 if p(sys.argv[1]) >= p(sys.argv[2]) else 1)
PY
    then break; fi
    (( $(date +%s) >= deadline )) && die "LatestRestorableTime no alcanzó la línea base en 15 min; no se declara RPO."
    sleep 30
  done
elif [[ -z "$SNAPSHOT" ]]; then
  SNAPSHOT="$(aws rds describe-db-snapshots --db-instance-identifier "$RDS_ID" --snapshot-type manual \
    --query 'sort_by(DBSnapshots[?Status==`available`], &SnapshotCreateTime)[-1].DBSnapshotIdentifier' --output text)"
fi
if [[ "$MODE" == "snapshot" ]]; then
  [[ -n "$SNAPSHOT" && "$SNAPSHOT" != "None" ]] || die "No hay snapshot manual disponible."
  SNAP_TIME="$(aws rds describe-db-snapshots --db-snapshot-identifier "$SNAPSHOT" --query 'DBSnapshots[0].SnapshotCreateTime' --output text)"
fi

DB_SG="$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$DB_SG_NAME" --query 'SecurityGroups[0].GroupId' --output text)"
[[ "$DB_SG" == sg-* ]] || die "SG de datos no encontrado."
echo "Se restaurará una copia privada y aislada. Costo orientativo: USD 0.02-0.03/h mientras exista."
read -r -p "Escribe RESTAURAR para declarar T0 y crear la copia: " answer
[[ "$answer" == "RESTAURAR" ]] || die "Ensayo cancelado."
mark "T0_incidente_declarado"

if [[ "$MODE" == "pitr" ]]; then
  SOURCE_ARGS=(restore-db-instance-to-point-in-time --source-db-instance-identifier "$RDS_ID" \
    --restore-time "$SNAP_TIME" --target-db-instance-identifier "$RESTORE_ID")
else
  SOURCE_ARGS=(restore-db-instance-from-db-snapshot --db-snapshot-identifier "$SNAPSHOT" \
    --db-instance-identifier "$RESTORE_ID")
fi
ARN="$(aws rds "${SOURCE_ARGS[@]}" --db-instance-class db.t3.micro \
  --db-subnet-group-name "$DB_SUBNET_GROUP" --vpc-security-group-ids "$DB_SG" \
  --no-publicly-accessible --no-multi-az --storage-type gp2 --no-deletion-protection \
  --copy-tags-to-snapshot --tags Key=Project,Value=NexoEventos Key=Purpose,Value=restore-drill \
  Key=ManagedBy,Value=manual-drill Key=RunId,Value="$STAMP" \
  --query 'DBInstance.DBInstanceArn' --output text)"
[[ "$ARN" == arn:aws:rds:* ]] || die "AWS no devolvió el ARN de la copia; revisa inventario antes de reintentar."
mark "T1_restauracion_solicitada"

python3 - "$OUT/recurso.json" "$RESTORE_ID" "$STAMP" "$AWS_REGION" "$(printf %s "$ARN" | shasum -a 256 | awk '{print $1}')" <<'PY'
import json, os, sys
path, rid, run, region, digest = sys.argv[1:]
with open(path, "x") as f:
    json.dump({"restore_id": rid, "run_id": run, "region": region, "arn_sha256": digest}, f)
    f.write("\n")
os.chmod(path, 0o600)
PY

ssm_exec resume 120 "systemctl start nexoeventos-api.service && systemctl is-active --quiet nexoeventos-api.service" >/dev/null
SERVICE_PAUSED=0
mark "T_servicio_origen_reanudado"

wait_rds_status "$RESTORE_ID" available 2400 || die "La copia no quedó disponible en 40 min; conserva el recibo y revisa/cierra el recurso exacto."
mark "T2_instancia_disponible"
HOST="$(aws rds describe-db-instances --db-instance-identifier "$RESTORE_ID" --query 'DBInstances[0].Endpoint.Address' --output text)"
PUBLIC="$(aws rds describe-db-instances --db-instance-identifier "$RESTORE_ID" --query 'DBInstances[0].PubliclyAccessible' --output text)"
[[ "$PUBLIC" == "False" ]] || die "La copia no cumple el control privado; no se verifica."

VERIFY_COMMAND="cat > /root/verify-restore.sh <<'NEXO_EOF'
$VERIFY_BODY
NEXO_EOF
chmod 700 /root/verify-restore.sh
/root/verify-restore.sh verify '$HOST' '$BASELINE_B64'
rc=\$?
rm -f /root/verify-restore.sh
exit \$rc"
if ! ssm_exec verify 600 "$VERIFY_COMMAND" | python3 "$PROJECT_ROOT/scripts/cloud/sanitize.py" >"$OUT/verificacion.txt"; then
  mark "T3_verificacion_fallida"
  die "Los datos no coincidieron con la línea base o falló QR. La copia sigue cobrando; usa cleanup con su recibo."
fi
grep -q "VERIFICACION_RESTAURACION=OK" "$OUT/verificacion.txt" || die "Falta confirmación verificable."
mark "T3_datos_verificados"

T0="$(awk -F'\t' '$1=="T0_incidente_declarado"{print $2}' "$TL")"
T2="$(awk -F'\t' '$1=="T2_instancia_disponible"{print $2}' "$TL")"
T3="$(awk -F'\t' '$1=="T3_datos_verificados"{print $2}' "$TL")"
SNAP_Z="$(python3 -c "import sys;from datetime import datetime,timezone;print(datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))" "$SNAP_TIME")"
RPO_S="$(seconds_between "$SNAP_Z" "$T0")"
RESTORE_S="$(seconds_between "$T0" "$T2")"
DATA_S="$(seconds_between "$T0" "$T3")"
{
  echo "# Ensayo de restauración cloud $STAMP"
  echo
  echo "| Medida | Valor | Interpretación |"
  echo "|---|---:|---|"
  echo "| Desfase punto recuperable (T0 − punto $MODE) | $((RPO_S/60)) min $((RPO_S%60)) s | Solo es RPO demostrado porque los datos se compararon con la línea base. |"
  echo "| Restauración RDS (T0 → disponible) | $((RESTORE_S/60)) min $((RESTORE_S%60)) s | Infraestructura de datos disponible. |"
  echo "| Recuperación/verificación de datos (T0 → verificado) | $((DATA_S/60)) min $((DATA_S%60)) s | Conteos, huella lógica, reservas y todas las entradas QR coinciden. |"
  echo "| Recuperación del servicio completo | pendiente | No se conmutaron aplicación, DNS ni HTTPS. |"
  echo
  echo "Verificación sanitizada:"; echo; echo '°°°'; cat "$OUT/verificacion.txt"; echo '°°°'
} | sed 's/°°°/```/g' >"$OUT/resumen.md"
record "restore-drill verificado $RESTORE_ID data_s=$DATA_S point_lag_s=$RPO_S"
cat "$OUT/resumen.md"
echo "La copia temporal sigue cobrando. Elimínala con cleanup; el recibo impide alcanzar otro recurso."
