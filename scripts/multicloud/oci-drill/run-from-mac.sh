#!/usr/bin/env bash
# Orquestador del simulacro de restauración en la VM de OCI. SE EJECUTA EN LA ESTACIÓN LOCAL de la propietaria (pide la frase de paso de la clave de recuperación en la terminal).
# NO crea la VM (eso es Terraform, con aprobación aparte). Requiere: VM y Bastion creados, sesión Bastion de reenvío de puerto abierta hacia 127.0.0.1:$LPORT
# (ver docs/multicloud/07-simulacro-oci.md), RPM PGDG en $RPMS ya verificados, y el perfil NEXOEVENTOS_UPLOADER para leer el bucket.
#
# Variables OBLIGATORIAS:
#   BUNDLE        nombre del respaldo sin extensión, p. ej. nexoeventos-rds-20261111T164610Z (objetos backups/$BUNDLE.oci.cms y .manifest.json)
#   BASELINE_KEY  clave de la línea base con la que se compara la huella, p. ej. rds-20261111T164610Z (SIN valor por defecto: así nunca se compara contra una base equivocada)
#   LPORT, SSH_KEY, RPMS, OCI_NS
# Variables opcionales:
#   BASELINE_FILE (por defecto docs/multicloud/baseline-restauracion.json; para el respaldo del 11-nov: docs/evidencias/multicloud/aws/20261111-respaldo-rds/linea-base-restauracion.json)
#   BUCKET (nexoeventos-recovery) · OCI_PROFILE (NEXOEVENTOS_UPLOADER) · RECOVERY_KEY (~/.nexoeventos/recovery-oci/oci-recovery-private.pem) · OUT_BASE (work/oci-drill)
#   RPM_CHECKSUMS (lista de SHA-256 de los RPM; por defecto oci-drill/rpm-checksums.sha256; solo se cambia en pruebas)
#   PREFLIGHT_ONLY=1  solo comprobaciones LOCALES (herramientas, archivos, línea base) y sale; no usa red ni crea nada. Úsalo antes de crear la VM.
# MODO C-04 (respaldos cifrados para `CN=NexoEventos backup recovery`, objetos backups/c04-AAAAMMDD/<ID>.cms|.manifest.json|.manifest.json.sig): BACKUP_KIND=c04 (o --kind c04) y, de forma OBLIGATORIA,
#   --key CLAVE_PRIVADA · --cert CERT.crt · --cert-sha256 HUELLA · --signer-pub CLAVE_PUBLICA_DE_FIRMA · --bundle ID. La línea base es la huella del PROPIO manifiesto (no hace falta BASELINE_*).
#   Antes de descifrar: firma del manifiesto, SHA-256/tamaño, identidad del certificado (huella fijada, destinatario del CMS, correspondencia con la clave si esta no tiene frase). La clave solo se usa en
#   esta Mac (el volcado en claro viaja por el túnel SSH a tmpfs; la clave nunca sale). Tiempos por etapa → $OUT/etapas.json y, si hay OPS_FAILOVER_DIR (o --status-dir), recovery-run.json del panel Operación.
# Códigos de salida: 0 correcto · 9 firma del manifiesto inválida · 10 identidad del certificado/clave · 2 comprobación previa o parámetros · 3 manifiesto no coincide con BUNDLE · 6 comprobación remota · 7 descifrado local · 8 restauración remota · otros: de verify-transfer/huella.
# Ejemplo: BUNDLE=nexoeventos-rds-20261111T164610Z BASELINE_KEY=rds-20261111T164610Z \
#   BASELINE_FILE=docs/evidencias/multicloud/aws/20261111-respaldo-rds/linea-base-restauracion.json LPORT=2222 SSH_KEY=~/.ssh/nexoeventos_recovery RPMS=work/oci-drill/rpms OCI_NS=<namespace> run-from-mac.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"; HERE="$ROOT/scripts/multicloud"
fail() { echo "ERROR: $1" >&2; exit "${2:-2}"; }
while [[ $# -gt 0 ]]; do case "$1" in
  --bundle) BUNDLE="$2"; shift 2;; --key) RECOVERY_KEY="$2"; shift 2;; --cert) CERT_FILE="$2"; shift 2;; --cert-sha256) CERT_SHA256="$2"; shift 2;;
  --signer-pub) SIGNER_PUB="$2"; shift 2;; --kind) BACKUP_KIND="$2"; shift 2;; --status-dir) OPS_FAILOVER_DIR="$2"; shift 2;; *) fail "opción desconocida: $1";; esac; done
BACKUP_KIND="${BACKUP_KIND:-legacy}"; CERT_FILE="${CERT_FILE:-}"; CERT_SHA256="$(printf %s "${CERT_SHA256:-}" | tr -d : | tr A-F a-f)"; SIGNER_PUB="${SIGNER_PUB:-}"
case "$BACKUP_KIND" in
  legacy) OBJ_PREFIX="backups/"; CMS_SUFFIX=".oci.cms"; : "${BASELINE_KEY:?define BASELINE_KEY (p. ej. rds-20261111T164610Z); no hay valor por defecto a propósito}";;
  c04) OBJ_PREFIX="${OBJECT_PREFIX:-backups/c04-20261119/}"; CMS_SUFFIX=".cms"; BASELINE_KEY="manifiesto"
       [[ -n "$CERT_FILE" && -n "$CERT_SHA256" && -n "$SIGNER_PUB" && -n "${RECOVERY_KEY:-}" ]] || fail "modo c04: son obligatorios --key, --cert, --cert-sha256 y --signer-pub";;
  *) fail "BACKUP_KIND debe ser legacy o c04";;
esac
: "${BUNDLE:?define BUNDLE (p. ej. nexoeventos-rds-20261111T164610Z)}"
: "${LPORT:?}" "${SSH_KEY:?}" "${RPMS:?}"
NS="${OCI_NS:?namespace de Object Storage}"; BUCKET="${BUCKET:-nexoeventos-recovery}"; PROFILE="${OCI_PROFILE:-NEXOEVENTOS_UPLOADER}"
BASELINE_FILE="${BASELINE_FILE:-$ROOT/docs/multicloud/baseline-restauracion.json}"
RECOVERY_KEY="${RECOVERY_KEY:-$HOME/.nexoeventos/recovery-oci/oci-recovery-private.pem}"
# --- comprobaciones locales ANTES de tocar nada (y antes de pedir ninguna frase de paso)
for t in oci openssl ssh scp python3 shasum; do command -v "$t" >/dev/null || fail "falta la herramienta «$t» en esta estación"; done
[[ -r "$RECOVERY_KEY" ]] || fail "no se puede leer la clave de recuperación: $RECOVERY_KEY"
[[ -r "$SSH_KEY" ]] || fail "no se puede leer la clave SSH: $SSH_KEY"
compgen -G "$RPMS/*.rpm" >/dev/null || fail "no hay RPM en $RPMS"
"$HERE/oci-drill/verify-rpms.sh" "$RPMS" "${RPM_CHECKSUMS:-$HERE/oci-drill/rpm-checksums.sha256}" >/dev/null || fail "los RPM no coinciden con la lista fijada de SHA-256 (ejecuta verify-rpms.sh para ver el detalle)"
if [[ "$BACKUP_KIND" == c04 ]]; then
  source "$HERE/oci-drill/lib-recovery.sh"; c04_preflight "$RECOVERY_KEY" "$CERT_FILE" "$CERT_SHA256" "$SIGNER_PUB"
else
  python3 "$HERE/compare-fingerprint.py" --check "$BASELINE_FILE" "$BASELINE_KEY" || fail "línea base inválida (ver mensaje anterior)"
fi
if [[ "${PREFLIGHT_ONLY:-}" == "1" ]]; then echo "OK    preflight local completo (no se usó red ni se creó nada)"; exit 0; fi
OUT="${OUT_BASE:-$ROOT/work/oci-drill}/run-$(date -u +%Y%m%dT%H%M%SZ)"; umask 077; mkdir -p "$OUT"; LOG="$OUT/tiempos.txt"
# known_hosts POR EJECUCIÓN: cada VM nueva tiene otra clave de host y llega por el mismo 127.0.0.1:$LPORT; con ~/.ssh/known_hosts la 2.ª ejecución fallaría con «HOST IDENTIFICATION HAS CHANGED».
# La identidad de la VM se fija en la primera conexión de ESTA ejecución (el túnel ya lo autentica OCI Bastion con su clave).
SSHOPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$OUT/known_hosts" -o IdentitiesOnly=yes)
SSH=(ssh "${SSHOPTS[@]}" -p "$LPORT" opc@127.0.0.1)
SCP=(scp "${SSHOPTS[@]}" -P "$LPORT")
mark() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$1" | tee -a "$LOG"; }
source "$HERE/oci-drill/lib-recovery.sh"; stages_init
t0=$(date +%s); mark "inicio (T0 del RTO de esta fase: vm ya creada) · respaldo=$BUNDLE · línea base=$BASELINE_KEY · modo=$BACKUP_KIND"
CMS_LOCAL="$OUT/$BUNDLE$CMS_SUFFIX"; MANIFEST="$OUT/$BUNDLE.manifest.json"
stage_begin descarga
GETS=("$CMS_SUFFIX" ".manifest.json"); [[ "$BACKUP_KIND" == c04 ]] && GETS+=(".manifest.json.sig")
for f in "${GETS[@]}"; do oci os object get --profile "$PROFILE" -ns "$NS" --bucket-name "$BUCKET" --name "$OBJ_PREFIX$BUNDLE$f" --file "$OUT/$BUNDLE$f"; done
stage_end; mark "descargado desde OCI con el perfil de carga"
stage_begin verificacion
if [[ "$BACKUP_KIND" == c04 ]]; then
  c04_verify_bundle "$MANIFEST" "$CMS_LOCAL" "$OUT/$BUNDLE.manifest.json.sig" "$SIGNER_PUB" "$CERT_FILE" "$CERT_SHA256" "$BUNDLE"
  mark "firma, SHA-256 e identidad del certificado verificados (huella fijada, destinatario del CMS)"
fi
"$HERE/verify-transfer.sh" "$MANIFEST" "$CMS_LOCAL"; mark "SHA-256 del cifrado = manifiesto"
python3 - "$MANIFEST" "$BUNDLE" <<'PY' || fail "el manifiesto no corresponde a BUNDLE (nombre distinto): no se continúa" 3
import json, sys
m = json.load(open(sys.argv[1]))
sys.exit(0 if m.get("name") == sys.argv[2] else 1)
PY
if [[ "$BACKUP_KIND" == c04 ]]; then
  python3 - "$MANIFEST" "$OUT/linea-base.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
json.dump({"baselines": {"manifiesto": {"fingerprint": m["fingerprint_before"], "fingerprint_after": m["fingerprint_after"]}}}, open(sys.argv[2], "w"))
PY
  BASELINE_FILE="$OUT/linea-base.json"; mark "línea base = huella del manifiesto"
fi
stage_end
PLAIN="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['plaintext_dump_sha256'])" "$MANIFEST")"
stage_begin instalacion
"${SSH[@]}" 'mkdir -p ~/drill/rpms'; "${SCP[@]}" "$RPMS"/*.rpm "opc@127.0.0.1:drill/rpms/"; "${SCP[@]}" "$HERE/oci-drill/"*.sh "$HERE/oci-drill/rpm-checksums.sha256" "$HERE/fingerprint.sql" "opc@127.0.0.1:drill/"
# /home/opc es 0700: el usuario postgres no puede leer ~opc; las herramientas van a un directorio propio (sin datos).
"${SSH[@]}" 'sudo install -d -m 0755 -o postgres -g postgres /var/lib/pgsql/drill-tools && sudo install -m 0755 -o postgres -g postgres ~/drill/remote-restore.sh /var/lib/pgsql/drill-tools/ && sudo install -m 0644 -o postgres -g postgres ~/drill/fingerprint.sql /var/lib/pgsql/drill-tools/'
mark "RPM y scripts copiados a la VM"
"${SSH[@]}" 'sudo bash ~/drill/install-postgres.sh ~/drill/rpms' | tee "$OUT/postgres-version.txt"; mark "PostgreSQL 18 instalado (solo socket Unix)"
# Comprobación remota ANTES de pedir la frase de paso (si falla, no se solicita nada). El 'cd' va DENTRO del sudo: /var/lib/pgsql es 0700 postgres y el usuario SSH (opc) no puede entrar.
RUN="sudo -u postgres bash -c 'cd /var/lib/pgsql && exec bash /var/lib/pgsql/drill-tools/remote-restore.sh"
"${SSH[@]}" "$RUN --check'" | tee "$OUT/preflight-remoto.txt" || { echo "FALLÓ la comprobación remota; no se pidió la frase de paso." >&2; exit 6; }
mark "comprobación remota correcta"
stage_end
echo ">> Se pedirá la frase de paso de la clave de recuperación (solo en esta terminal) si la clave está protegida."
stage_begin descifrado_restauracion      # el volcado se descifra en la Mac y se transmite en tubería: descifrado y restauración se solapan y no se pueden separar sin escribir el volcado en claro
set +e
openssl cms -decrypt -binary -inform DER -in "$CMS_LOCAL" -inkey "$RECOVERY_KEY" 2>"$OUT/openssl.err" \
  | "${SSH[@]}" "$RUN $PLAIN /var/lib/pgsql/drill-tools/fingerprint.sql'" | tee "$OUT/huella-restaurada.txt"
rc=("${PIPESTATUS[@]}"); set -e
if [[ ${rc[0]} -ne 0 ]]; then echo "FALLÓ el descifrado local (openssl código ${rc[0]}); el volcado no se restauró. Detalle (sin datos): $(head -c 300 "$OUT/openssl.err")" >&2; exit 7; fi
if [[ ${rc[1]} -ne 0 ]]; then echo "FALLÓ la restauración remota (ssh/remote-restore código ${rc[1]}); revise la salida anterior." >&2; exit 8; fi
stage_end; mark "volcado descifrado localmente, transmitido por SSH y restaurado"
stage_begin comprobacion
python3 "$HERE/compare-fingerprint.py" "$BASELINE_FILE" "$BASELINE_KEY" "$OUT/huella-restaurada.txt" | tee -a "$LOG"; crc=${PIPESTATUS[0]}
[[ $crc -eq 0 ]] || fail "la huella restaurada NO coincide con la línea base «$BASELINE_KEY» (código $crc)" "$crc"
stage_end; mark "huella verificada; duración de la fase: $(( $(date +%s) - t0 )) s"
