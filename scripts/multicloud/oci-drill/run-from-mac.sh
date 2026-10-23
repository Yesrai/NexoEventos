#!/usr/bin/env bash
# Orquestador del simulacro de restauración en la VM de OCI. SE EJECUTA EN LA ESTACIÓN LOCAL de la propietaria (pide la frase de paso de la clave de recuperación en la terminal).
# NO crea la VM (eso es Terraform, con aprobación aparte). Requiere: VM y Bastion creados, sesión Bastion de reenvío de puerto abierta hacia 127.0.0.1:$LPORT
# (ver docs/multicloud/07-simulacro-oci.md), RPM PGDG en $RPMS ya verificados, y el perfil NEXOEVENTOS_UPLOADER para leer el bucket.
# Uso: BUNDLE=nexoeventos-alembic0008-20261023T150946Z LPORT=2222 SSH_KEY=~/.ssh/nexoeventos_recovery RPMS=work/oci-drill/rpms run-from-mac.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"; HERE="$ROOT/scripts/multicloud"
: "${BUNDLE:?}" "${LPORT:?}" "${SSH_KEY:?}" "${RPMS:?}"
NS="${OCI_NS:?namespace de Object Storage}"; BUCKET=nexoeventos-recovery; PROFILE=NEXOEVENTOS_UPLOADER
OUT="$ROOT/work/oci-drill/run-$(date -u +%Y%m%dT%H%M%SZ)"; umask 077; mkdir -p "$OUT"; LOG="$OUT/tiempos.txt"
SSH=(ssh -i "$SSH_KEY" -p "$LPORT" -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes opc@127.0.0.1)
SCP=(scp -i "$SSH_KEY" -P "$LPORT" -o IdentitiesOnly=yes)
mark() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$1" | tee -a "$LOG"; }
t0=$(date +%s); mark "inicio (T0 del RTO de esta fase: vm ya creada)"
for f in oci.cms manifest.json; do oci os object get --profile "$PROFILE" -ns "$NS" --bucket-name "$BUCKET" --name "backups/$BUNDLE.$f" --file "$OUT/$BUNDLE.$f"; done
mark "descargado desde OCI con el perfil de carga"
"$HERE/verify-transfer.sh" "$OUT/$BUNDLE.manifest.json" "$OUT/$BUNDLE.oci.cms"; mark "SHA-256 del cifrado = manifiesto"
PLAIN="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['plaintext_dump_sha256'])" "$OUT/$BUNDLE.manifest.json")"
"${SSH[@]}" 'mkdir -p ~/drill/rpms'; "${SCP[@]}" "$RPMS"/*.rpm "opc@127.0.0.1:drill/rpms/"; "${SCP[@]}" "$HERE/oci-drill/"*.sh "$HERE/fingerprint.sql" "opc@127.0.0.1:drill/"
# /home/opc es 0700: el usuario postgres no puede leer ~opc; las herramientas van a un directorio propio (sin datos).
"${SSH[@]}" 'sudo install -d -m 0755 -o postgres -g postgres /var/lib/pgsql/drill-tools && sudo install -m 0755 -o postgres -g postgres ~/drill/remote-restore.sh /var/lib/pgsql/drill-tools/ && sudo install -m 0644 -o postgres -g postgres ~/drill/fingerprint.sql /var/lib/pgsql/drill-tools/'
mark "RPM y scripts copiados a la VM"
"${SSH[@]}" 'sudo bash ~/drill/install-postgres.sh ~/drill/rpms' | tee "$OUT/postgres-version.txt"; mark "PostgreSQL 18 instalado (solo socket Unix)"
# Comprobación remota ANTES de pedir la frase de paso (si falla, no se solicita nada). El 'cd' va DENTRO del sudo: /var/lib/pgsql es 0700 postgres y el usuario SSH (opc) no puede entrar.
RUN="sudo -u postgres bash -c 'cd /var/lib/pgsql && exec bash /var/lib/pgsql/drill-tools/remote-restore.sh"
"${SSH[@]}" "$RUN --check'" | tee "$OUT/preflight-remoto.txt" || { echo "FALLÓ la comprobación remota; no se pidió la frase de paso." >&2; exit 6; }
mark "comprobación remota correcta"
echo ">> Se pedirá la frase de paso de la clave de recuperación (solo en esta terminal)."
set +e
openssl cms -decrypt -binary -inform DER -in "$OUT/$BUNDLE.oci.cms" -inkey "${RECOVERY_KEY:-$HOME/.nexoeventos/recovery-oci/oci-recovery-private.pem}" 2>"$OUT/openssl.err" \
  | "${SSH[@]}" "$RUN $PLAIN /var/lib/pgsql/drill-tools/fingerprint.sql'" | tee "$OUT/huella-restaurada.txt"
rc=("${PIPESTATUS[@]}"); set -e
if [[ ${rc[0]} -ne 0 ]]; then echo "FALLÓ el descifrado local (openssl código ${rc[0]}); el volcado no se restauró. Detalle (sin datos): $(head -c 300 "$OUT/openssl.err")" >&2; exit 7; fi
if [[ ${rc[1]} -ne 0 ]]; then echo "FALLÓ la restauración remota (ssh/remote-restore código ${rc[1]}); revise la salida anterior." >&2; exit 8; fi
mark "volcado descifrado localmente, transmitido por SSH y restaurado"
python3 - "$ROOT/docs/multicloud/baseline-restauracion.json" "0008-estado-20261022" "$OUT/huella-restaurada.txt" <<'PY'
import json, sys
base = json.load(open(sys.argv[1]))["baselines"][sys.argv[2]]["fingerprint"]
now = dict(l.strip().split("=", 1) for l in open(sys.argv[3]) if "=" in l)
diff = {k: (base[k], now.get(k)) for k in base if base[k] != now.get(k)}
if diff:
    print("FALLÓ huella (esperado, obtenido):", diff); sys.exit(1)
print(f"OK    huella idéntica a la línea base ({len(base)} claves)")
PY
mark "huella verificada; duración de la fase: $(( $(date +%s) - t0 )) s"
