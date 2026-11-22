#!/usr/bin/env bash
# Recuperación de la APLICACIÓN en la VM temporal de OCI (PostgreSQL 18 + FastAPI + Nginx + frontend). SE EJECUTA EN LA ESTACIÓN LOCAL de la propietaria: pide DOS veces la frase de paso de la
# clave de recuperación (datos y claves de aplicación), solo en la terminal. NO crea la VM (Terraform, con aprobación aparte). Requiere dos túneles de OCI Bastion abiertos:
# SSH (127.0.0.1:$LPORT -> VM:22) y HTTPS (127.0.0.1:$HPORT -> VM:443), y los RPM de PostgreSQL ya verificados.
# MODO C-04 (BACKUP_KIND=c04 o --kind c04): datos = backups/c04-AAAAMMDD/<ID>.cms|.manifest.json|.manifest.json.sig y claves de aplicación = secrets/c04-AAAAMMDD/<ID>.cms|... cifrados para el certificado C-04.
#   Obligatorios: --key CLAVE --cert CERT --cert-sha256 HUELLA --signer-pub PUB --bundle ID --secbundle ID. La clave solo se usa en esta Mac. Antes de restaurar se verifican firma, SHA-256 e identidad del certificado
#   de AMBOS paquetes; las claves de aplicación entregadas deben tener el SHA-256 del manifiesto (son las ORIGINALES; no se generan valores nuevos). Código 11 = claves de aplicación distintas de las originales.
#   Tiempos por etapa → etapas.json y (con OPS_FAILOVER_DIR/--status-dir) recovery-run.json del panel Operación.
# Uso: BUNDLE=<respaldo> SECBUNDLE=<app-secrets-AAAAMMDDThhmmssZ> OCI_NS=<ns> LPORT=2222 HPORT=8443 SSH_KEY=~/.ssh/nexoeventos_recovery RPMS=work/oci-drill/rpms app-recovery.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"; HERE="$ROOT/scripts/multicloud"; cd "$ROOT"
fail() { echo "ERROR: $1" >&2; exit "${2:-2}"; }
while [[ $# -gt 0 ]]; do case "$1" in
  --bundle) BUNDLE="$2"; shift 2;; --secbundle) SECBUNDLE="$2"; shift 2;; --key) RECOVERY_KEY="$2"; shift 2;; --cert) CERT_FILE="$2"; shift 2;; --cert-sha256) CERT_SHA256="$2"; shift 2;;
  --signer-pub) SIGNER_PUB="$2"; shift 2;; --allow-writes) READONLY=0; shift;; --kind) BACKUP_KIND="$2"; shift 2;; --status-dir) OPS_FAILOVER_DIR="$2"; shift 2;; *) fail "opción desconocida: $1";; esac; done
READONLY="${READONLY:-}"; BACKUP_KIND="${BACKUP_KIND:-legacy}"; CERT_FILE="${CERT_FILE:-}"; CERT_SHA256="$(printf %s "${CERT_SHA256:-}" | tr -d : | tr A-F a-f)"; SIGNER_PUB="${SIGNER_PUB:-}"
case "$BACKUP_KIND" in
  legacy) OBJ_PREFIX="backups/"; SEC_PREFIX="secrets/"; CMS_SUFFIX=".oci.cms"
          # La línea base se elige SIEMPRE de forma explícita (antes estaba fija en 0008-estado-20261022 y habría rechazado cualquier respaldo posterior).
          : "${BASELINE_KEY:?define BASELINE_KEY (p. ej. rds-20261111T164610Z); no hay valor por defecto a propósito}";;
  c04) [[ -n "$READONLY" ]] || READONLY=1     # la recuperación aislada C-04 es de SOLO LECTURA por defecto (sin doble escritor); --allow-writes lo desactiva
       OBJ_PREFIX="${OBJECT_PREFIX:-backups/c04-20261119/}"; SEC_PREFIX="${SECRET_PREFIX:-secrets/c04-20261119/}"; CMS_SUFFIX=".cms"; BASELINE_KEY="manifiesto"
       [[ -n "$CERT_FILE" && -n "$CERT_SHA256" && -n "$SIGNER_PUB" && -n "${RECOVERY_KEY:-}" ]] || fail "modo c04: son obligatorios --key, --cert, --cert-sha256 y --signer-pub";;
  *) fail "BACKUP_KIND debe ser legacy o c04";;
esac
: "${BUNDLE:?}" "${SECBUNDLE:?}" "${OCI_NS:?}" "${LPORT:?}" "${HPORT:?}" "${SSH_KEY:?}" "${RPMS:?}"
BASELINE_FILE="${BASELINE_FILE:-$ROOT/docs/multicloud/baseline-restauracion.json}"
BUCKET="${BUCKET:-nexoeventos-recovery}"; PROFILE="${OCI_PROFILE:-NEXOEVENTOS_UPLOADER}"; KEY="${RECOVERY_KEY:-$HOME/.nexoeventos/recovery-oci/oci-recovery-private.pem}"; RECOVERY_KEY="$KEY"
# Comprobaciones LOCALES antes de tocar nada ni pedir ninguna frase de paso.
for t in oci openssl ssh scp python3 shasum npm tar; do command -v "$t" >/dev/null || fail "falta la herramienta «$t» en esta estación"; done
[[ -r "$KEY" ]] || fail "no se puede leer la clave de recuperación: $KEY"; [[ -r "$SSH_KEY" ]] || fail "no se puede leer la clave SSH: $SSH_KEY"
compgen -G "$RPMS/*.rpm" >/dev/null || fail "no hay RPM en $RPMS"; "$HERE/oci-drill/verify-rpms.sh" "$RPMS" "${RPM_CHECKSUMS:-$HERE/oci-drill/rpm-checksums.sha256}" >/dev/null || fail "los RPM no coinciden con la lista fijada de SHA-256"; [[ -x backend/.venv/bin/python ]] || fail "falta backend/.venv (necesario para descargar las ruedas y ejecutar el humo)"
for f in deploy/systemd/nexoeventos-api.service deploy/nginx/nexoeventos.conf.template backend/requirements-production.lock; do [[ -f "$f" ]] || fail "falta $f"; done
source "$HERE/oci-drill/lib-recovery.sh"
if [[ "$BACKUP_KIND" == c04 ]]; then c04_preflight "$KEY" "$CERT_FILE" "$CERT_SHA256" "$SIGNER_PUB"
else python3 "$HERE/compare-fingerprint.py" --check "$BASELINE_FILE" "$BASELINE_KEY" || fail "línea base inválida (ver mensaje anterior)"; fi
if [[ "${PREFLIGHT_ONLY:-}" == "1" ]]; then echo "OK    preflight local completo (no se usó red ni se creó nada)"; exit 0; fi
# Reanudación: START_AT=download|build|copy|postgres|app1|data|secrets|app2|smoke y OUT_DIR=<carpeta de la ejecución anterior> (conserva descargas, paquete y tiempos; el RTO sigue contando desde el T0 original).
STAGES=(download build copy postgres app1 data secrets app2 smoke); START_AT="${START_AT:-download}"
idx() { local i=0; for x in "${STAGES[@]}"; do [[ "$x" == "$1" ]] && { echo $i; return; }; i=$((i+1)); done; echo "etapa desconocida: $1" >&2; exit 2; }
STOP_BEFORE="${STOP_BEFORE:-}"   # opcional: detenerse antes de una etapa (p. ej. smoke, que pide contraseñas en la terminal)
want() { [[ $(idx "$1") -ge $(idx "$START_AT") ]] && { [[ -z "$STOP_BEFORE" ]] || [[ $(idx "$1") -lt $(idx "$STOP_BEFORE") ]]; }; }
OUT="${OUT_DIR:-$ROOT/work/oci-drill/app-$(date -u +%Y%m%dT%H%M%SZ)}"; umask 077; mkdir -p "$OUT/bundle/wheels"; LOG="$OUT/tiempos.txt"; B="$OUT/bundle"
# known_hosts POR EJECUCIÓN (en $OUT): cada VM nueva llega por el mismo 127.0.0.1:$LPORT con otra clave de host; con ~/.ssh/known_hosts la 2.ª ejecución fallaría («HOST IDENTIFICATION HAS CHANGED»).
SSHOPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$OUT/known_hosts" -o IdentitiesOnly=yes)
SSH=(ssh "${SSHOPTS[@]}" -p "$LPORT" opc@127.0.0.1); SCP=(scp "${SSHOPTS[@]}" -P "$LPORT")
mark() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$1" | tee -a "$LOG"; }; if [[ -s "$LOG" ]]; then T0=$(python3 -c "import sys,datetime as d;print(int(d.datetime.strptime(open(sys.argv[1]).readline().split()[0],'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=d.timezone.utc).timestamp()))" "$LOG"); mark "REANUDACIÓN desde la etapa '$START_AT' (el T0 original no se reinicia)"; else T0=$(date +%s); mark "T0 inicio de la recuperación de la aplicación"; fi
RUN_T0="$T0"; stages_init
# Frase de la clave protegida: se pide UNA vez (sin eco) cuando hace falta descifrar, queda en una variable NO exportada y viaja a openssl por un descriptor (-passin fd:4); no hay variable de entorno ni archivo.
KEYPW=""
ask_pw() {   # en el shell PRINCIPAL (las tuberías corren en subshells y no conservarían la variable)
  grep -q -E 'ENCRYPTED' "$KEY" || return 0; [[ -z "$KEYPW" ]] || return 0
  [[ -t 0 ]] || fail "la clave está protegida: ejecute este script en una terminal interactiva" 7
  IFS= read -r -s -p "Frase de paso de la clave de recuperación (no se muestra): " KEYPW; echo
}
decrypt_cms() {   # $1 = paquete CMS → volcado en claro por stdout
  if grep -q -E 'ENCRYPTED' "$KEY"; then exec 4< <(printf '%s\n' "$KEYPW"); openssl cms -decrypt -binary -inform DER -in "$1" -inkey "$KEY" -passin fd:4
  else openssl cms -decrypt -binary -inform DER -in "$1" -inkey "$KEY"; fi
}
RO_ARG=""; [[ "${READONLY:-0}" == 1 ]] && RO_ARG="--read-only"
if [[ "$BACKUP_KIND" == c04 ]]; then CMS_DATA="$OUT/$BUNDLE.cms"; CMS_SEC="$OUT/$SECBUNDLE.cms"; [[ -s "$OUT/linea-base.json" ]] && BASELINE_FILE="$OUT/linea-base.json"
else CMS_DATA="$OUT/$BUNDLE.oci.cms"; CMS_SEC="$OUT/$SECBUNDLE.oci.cms"; fi
RUNPG="sudo -u postgres env DRILL_DB=nexoeventos bash -c 'cd /var/lib/pgsql && exec bash /var/lib/pgsql/drill-tools/remote-restore.sh"
if want download; then
stage_begin descarga
# 1. Descarga y verificación de los dos paquetes cifrados (perfil de carga)
aws_writers_quiet "antes de recuperar"
if [[ "$BACKUP_KIND" == c04 ]]; then
  for pair in "$OBJ_PREFIX$BUNDLE" "$SEC_PREFIX$SECBUNDLE"; do for suf in .cms .manifest.json .manifest.json.sig; do
    oci os object get --profile "$PROFILE" -ns "$OCI_NS" --bucket-name "$BUCKET" --name "$pair$suf" --file "$OUT/$(basename "$pair")$suf"
  done; done
  c04_verify_bundle "$OUT/$BUNDLE.manifest.json" "$OUT/$BUNDLE.cms" "$OUT/$BUNDLE.manifest.json.sig" "$SIGNER_PUB" "$CERT_FILE" "$CERT_SHA256" "$BUNDLE"
  c04_verify_bundle "$OUT/$SECBUNDLE.manifest.json" "$OUT/$SECBUNDLE.cms" "$OUT/$SECBUNDLE.manifest.json.sig" "$SIGNER_PUB" "$CERT_FILE" "$CERT_SHA256" "$SECBUNDLE"
  python3 - "$OUT/$SECBUNDLE.manifest.json" <<'PY' || fail "el manifiesto de claves no declara el SHA-256 de TICKET_ENCRYPTION_KEY y SECURITY_HASH_KEY: no se puede comprobar que sean las originales" 11
import json, re, sys
m = json.load(open(sys.argv[1])).get("secret_sha256") or {}
sys.exit(0 if set(m) == {"TICKET_ENCRYPTION_KEY", "SECURITY_HASH_KEY"} and all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in m.values()) else 1)
PY
  python3 - "$OUT/$BUNDLE.manifest.json" "$OUT/linea-base.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
json.dump({"baselines": {"manifiesto": {"fingerprint": m["fingerprint_before"], "fingerprint_after": m["fingerprint_after"]}}}, open(sys.argv[2], "w"))
PY
  BASELINE_FILE="$OUT/linea-base.json"; CMS_DATA="$OUT/$BUNDLE.cms"; CMS_SEC="$OUT/$SECBUNDLE.cms"
else
for f in "$BUNDLE.oci.cms" "$BUNDLE.manifest.json"; do oci os object get --profile "$PROFILE" -ns "$OCI_NS" --bucket-name "$BUCKET" --name "backups/$f" --file "$OUT/$f"; done
"$HERE/verify-transfer.sh" "$OUT/$BUNDLE.manifest.json" "$OUT/$BUNDLE.oci.cms"
oci os object get --profile "$PROFILE" -ns "$OCI_NS" --bucket-name "$BUCKET" --name "secrets/$SECBUNDLE.oci.cms" --file "$OUT/$SECBUNDLE.oci.cms"
oci os object get --profile "$PROFILE" -ns "$OCI_NS" --bucket-name "$BUCKET" --name "secrets/$SECBUNDLE.manifest.json" --file "$OUT/$SECBUNDLE.manifest.json"
[[ "$(shasum -a 256 "$OUT/$SECBUNDLE.oci.cms" | cut -d' ' -f1)" == "$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['cms_sha256'])" "$OUT/$SECBUNDLE.manifest.json")" ]] || { echo "FALLÓ: SHA-256 del paquete de claves distinto del manifiesto" >&2; exit 3; }
CMS_DATA="$OUT/$BUNDLE.oci.cms"; CMS_SEC="$OUT/$SECBUNDLE.oci.cms"
fi
mark "paquetes de datos y de claves descargados y verificados"
stage_end
fi
if want build; then
stage_begin construccion
# 2. Preparación del paquete de la aplicación en la Mac (ruedas para la arquitectura de la VM, backend, frontend)
ARCH="$("${SSH[@]}" 'uname -m')"; case "$ARCH" in x86_64|aarch64) ;; *) echo "Arquitectura inesperada: $ARCH" >&2; exit 4;; esac
backend/.venv/bin/python -m pip download --quiet --no-deps --only-binary=:all: --python-version 3.12 --implementation cp --platform "manylinux_2_28_$ARCH" --platform "manylinux_2_17_$ARCH" --platform "manylinux2014_$ARCH" \
  -r backend/requirements-production.lock -d "$B/wheels"
# Las ~33 ruedas se envían como UN archivo (medido el 19-nov: 38 s de scp archivo por archivo a través del Bastion); en la VM se descomprimen antes de instalar.
tar -czf "$B/wheels.tgz" -C "$B" wheels && rm -rf "$B/wheels"
tar -czf "$B/backend.tgz" --exclude='__pycache__' -C backend app alembic alembic.ini requirements-production.lock
( cd frontend && npm run build >/dev/null ) && tar -czf "$B/dist.tgz" -C frontend dist
cp deploy/systemd/nexoeventos-api.service deploy/nginx/nexoeventos.conf.template "$B/"; cp "$HERE/oci-drill/"*.sh "$HERE/oci-drill/rpm-checksums.sha256" "$HERE/fingerprint.sql" "$B/"
mark "paquete de la aplicación construido en la Mac ($ARCH)"
stage_end
fi
if want copy; then
stage_begin copia
"${SSH[@]}" 'rm -rf ~/app && mkdir -p ~/app'; "${SCP[@]}" -r "$B"/. "opc@127.0.0.1:app/"; "${SCP[@]}" "$RPMS"/*.rpm "opc@127.0.0.1:app/"
mark "paquete copiado a la VM"
stage_end
fi
# 3. PostgreSQL 18 (idempotente). El usuario 'postgres' lo crea el RPM: las herramientas de restauración se instalan DESPUÉS.
if want postgres; then
stage_begin postgres
"${SSH[@]}" 'mkdir -p ~/drill/rpms && cp ~/app/postgresql18-*.rpm ~/drill/rpms/ && sudo bash ~/app/install-postgres.sh ~/drill/rpms' | tee "$OUT/postgres-version.txt"; id_postgres="$("${SSH[@]}" 'getent passwd postgres | cut -d: -f1')"; [[ "$id_postgres" == postgres ]] || { echo "FALLÓ: el usuario postgres no existe tras instalar el RPM" >&2; exit 5; }
"${SSH[@]}" 'sudo install -d -m 0755 -o postgres -g postgres /var/lib/pgsql/drill-tools && sudo install -m 0755 -o postgres -g postgres ~/app/remote-restore.sh /var/lib/pgsql/drill-tools/ && sudo install -m 0644 -o postgres -g postgres ~/app/fingerprint.sql /var/lib/pgsql/drill-tools/'
mark "PostgreSQL 18 instalado"
stage_end
fi
if want app1; then
stage_begin instalacion_app
"${SSH[@]}" 'sudo bash ~/app/install-app.sh stage1 ~/app' | tee "$OUT/stage1.txt"; mark "etapa 1: Python, Nginx, entorno virtual (ruedas locales) y frontend"
stage_end
fi
if want data; then
stage_begin datos
# 4. Restauración de los datos en la base 'nexoeventos' (frase de paso nº 1, solo en la terminal)
ask_pw; "${SSH[@]}" "$RUNPG --check'"; echo ">> Se descifrarán los datos (la frase de la clave se pide una sola vez si está protegida)"
PLAIN="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['plaintext_dump_sha256'])" "$OUT/$BUNDLE.manifest.json")"
set +e; decrypt_cms "$CMS_DATA" 2>"$OUT/openssl-datos.err" | "${SSH[@]}" "$RUNPG $PLAIN /var/lib/pgsql/drill-tools/fingerprint.sql'" | tee "$OUT/huella-restaurada.txt"; rc=("${PIPESTATUS[@]}"); set -e
[[ ${rc[0]} -eq 0 ]] || { echo "FALLÓ el descifrado local de los datos (openssl $rc)" >&2; exit 7; }; [[ ${rc[1]} -eq 0 ]] || { echo "FALLÓ la restauración remota (código ${rc[1]})" >&2; exit 8; }
python3 "$HERE/compare-fingerprint.py" "$BASELINE_FILE" "$BASELINE_KEY" "$OUT/huella-restaurada.txt" || { echo "FALLÓ: la huella restaurada NO coincide con la línea base «$BASELINE_KEY»" >&2; exit 1; }
mark "T_datos: datos restaurados y huella verificada"
stage_end
fi
if want secrets; then
stage_begin secretos
# 5. Claves de aplicación originales (frase de paso nº 2): solo a tmpfs de la VM
echo ">> Descifrando las claves de aplicación"
set +e; decrypt_cms "$CMS_SEC" 2>"$OUT/openssl-claves.err" | "${SSH[@]}" 'sudo bash ~/app/install-app-secrets.sh' | tee "$OUT/claves-instaladas.txt" | grep -v '^SHA256 '; rc=("${PIPESTATUS[@]}"); set -e
[[ ${rc[0]} -eq 0 && ${rc[1]} -eq 0 ]] || { echo "FALLÓ la entrega de las claves de aplicación (openssl=${rc[0]}, ssh=${rc[1]})" >&2; exit 9; }
if [[ "$BACKUP_KIND" == c04 ]]; then   # son las ORIGINALES: el SHA-256 de cada valor entregado debe ser el del manifiesto (que se calculó al exportarlas de AWS)
  python3 - "$OUT/$SECBUNDLE.manifest.json" "$OUT/claves-instaladas.txt" <<'PY' || { echo "FALLÓ: las claves de aplicación entregadas NO son las originales (SHA-256 distinto del manifiesto); se detiene antes de arrancar la aplicación." >&2; exit 11; }
import json, sys
want = json.load(open(sys.argv[1]))["secret_sha256"]
got = dict(l.strip().split(" ", 1)[1].split("=", 1) for l in open(sys.argv[2]) if l.startswith("SHA256 "))
sys.exit(0 if got == want else 1)
PY
  mark "claves de aplicación = originales (SHA-256 de cada valor coincide con el manifiesto firmado)"
fi
mark "claves originales entregadas a tmpfs (valores no mostrados)"
stage_end
fi
if want app2; then
stage_begin servicio
"${SCP[@]}" "$HERE/oci-drill/install-app.sh" "$HERE/oci-drill/db-permissions.sh" "opc@127.0.0.1:app/"   # versión corregida (Nginx 1.20)
# 6. Etapa 2: rol de BD, entorno, TLS efímero, systemd, Nginx
"${SSH[@]}" "sudo env RECOVERY_READONLY=${READONLY:-0} bash ~/app/install-app.sh stage2 ~/app" | tee "$OUT/stage2.txt"; mark "T_servicio: aplicación en marcha (healthz local correcto)"
stage_end
fi
if want smoke; then
stage_begin humo
# 7. Pruebas funcionales por el túnel HTTPS (sin ventas)
backend/.venv/bin/python "$HERE/oci-drill/app-smoke.py" --out "$OUT" --base "https://localhost:$HPORT" $RO_ARG ${RESET_CREDS:+--reset-creds --ssh-port "$LPORT" --ssh-key "$SSH_KEY"} | tee "$OUT/smoke.txt"; mark "T_funcional: pruebas funcionales terminadas"
"${SSH[@]}" "sudo -u postgres bash -c 'cd /var/lib/pgsql && /usr/pgsql-18/bin/psql -d nexoeventos -At -f /var/lib/pgsql/drill-tools/fingerprint.sql'" | sort > "$OUT/huella-final.txt"
diff <(sort "$OUT/huella-restaurada.txt" | grep -E '^[a-z_0-9]+=') "$OUT/huella-final.txt" > "$OUT/huella-delta.txt" || true
if [[ "${READONLY:-0}" == 1 ]]; then   # solo lectura: la base NO puede haber cambiado en absoluto (ni access_logs)
  [[ ! -s "$OUT/huella-delta.txt" ]] || { echo "FALLÓ: la base cambió durante una recuperación de SOLO LECTURA (posible escritura):" >&2; cat "$OUT/huella-delta.txt" >&2; exit 12; }
  echo "OK    huella final idéntica a la restaurada: ninguna escritura durante la prueba"
else echo "Delta de huella tras las pruebas (esperado: solo access_logs):"; cat "$OUT/huella-delta.txt"; fi
aws_writers_quiet "después de recuperar"
mark "fin; duración total desde T0: $(( $(date +%s) - T0 )) s"
stage_end
fi
echo "Evidencias en $OUT"
