#!/usr/bin/env bash
# Recuperación de la APLICACIÓN en la VM temporal de OCI (PostgreSQL 18 + FastAPI + Nginx + frontend). SE EJECUTA EN LA ESTACIÓN LOCAL de la propietaria: pide DOS veces la frase de paso de la
# clave de recuperación (datos y claves de aplicación), solo en la terminal. NO crea la VM (Terraform, con aprobación aparte). Requiere dos túneles de OCI Bastion abiertos:
# SSH (127.0.0.1:$LPORT -> VM:22) y HTTPS (127.0.0.1:$HPORT -> VM:443), y los RPM de PostgreSQL ya verificados.
# Uso: BUNDLE=<respaldo> SECBUNDLE=<app-secrets-AAAAMMDDThhmmssZ> OCI_NS=<ns> LPORT=2222 HPORT=8443 SSH_KEY=~/.ssh/nexoeventos_recovery RPMS=work/oci-drill/rpms app-recovery.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"; HERE="$ROOT/scripts/multicloud"; cd "$ROOT"
: "${BUNDLE:?}" "${SECBUNDLE:?}" "${OCI_NS:?}" "${LPORT:?}" "${HPORT:?}" "${SSH_KEY:?}" "${RPMS:?}"
BUCKET=nexoeventos-recovery; PROFILE=NEXOEVENTOS_UPLOADER; KEY="${RECOVERY_KEY:-$HOME/.nexoeventos/recovery-oci/oci-recovery-private.pem}"
OUT="$ROOT/work/oci-drill/app-$(date -u +%Y%m%dT%H%M%SZ)"; umask 077; mkdir -p "$OUT/bundle/wheels"; LOG="$OUT/tiempos.txt"; B="$OUT/bundle"
SSH=(ssh -i "$SSH_KEY" -p "$LPORT" -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes opc@127.0.0.1); SCP=(scp -i "$SSH_KEY" -P "$LPORT" -o IdentitiesOnly=yes)
mark() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$1" | tee -a "$LOG"; }; T0=$(date +%s); mark "T0 inicio de la recuperación de la aplicación"
RUNPG="sudo -u postgres env DRILL_DB=nexoeventos bash -c 'cd /var/lib/pgsql && exec bash /var/lib/pgsql/drill-tools/remote-restore.sh"
# 1. Descarga y verificación de los dos paquetes cifrados (perfil de carga)
for f in "$BUNDLE.oci.cms" "$BUNDLE.manifest.json"; do oci os object get --profile "$PROFILE" -ns "$OCI_NS" --bucket-name "$BUCKET" --name "backups/$f" --file "$OUT/$f"; done
"$HERE/verify-transfer.sh" "$OUT/$BUNDLE.manifest.json" "$OUT/$BUNDLE.oci.cms"
oci os object get --profile "$PROFILE" -ns "$OCI_NS" --bucket-name "$BUCKET" --name "secrets/$SECBUNDLE.oci.cms" --file "$OUT/$SECBUNDLE.oci.cms"
oci os object get --profile "$PROFILE" -ns "$OCI_NS" --bucket-name "$BUCKET" --name "secrets/$SECBUNDLE.manifest.json" --file "$OUT/$SECBUNDLE.manifest.json"
[[ "$(shasum -a 256 "$OUT/$SECBUNDLE.oci.cms" | cut -d' ' -f1)" == "$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['cms_sha256'])" "$OUT/$SECBUNDLE.manifest.json")" ]] || { echo "FALLÓ: SHA-256 del paquete de claves distinto del manifiesto" >&2; exit 3; }
mark "paquetes de datos y de claves descargados y verificados"
# 2. Preparación del paquete de la aplicación en la Mac (ruedas para la arquitectura de la VM, backend, frontend)
ARCH="$("${SSH[@]}" 'uname -m')"; case "$ARCH" in x86_64|aarch64) ;; *) echo "Arquitectura inesperada: $ARCH" >&2; exit 4;; esac
backend/.venv/bin/python -m pip download --quiet --no-deps --only-binary=:all: --python-version 3.12 --implementation cp --platform "manylinux_2_28_$ARCH" --platform "manylinux_2_17_$ARCH" --platform "manylinux2014_$ARCH" \
  -r backend/requirements-production.lock -d "$B/wheels"
tar -czf "$B/backend.tgz" --exclude='__pycache__' -C backend app alembic alembic.ini requirements-production.lock
( cd frontend && npm run build >/dev/null ) && tar -czf "$B/dist.tgz" -C frontend dist
cp deploy/systemd/nexoeventos-api.service deploy/nginx/nexoeventos.conf.template "$B/"; cp "$HERE/oci-drill/"*.sh "$HERE/fingerprint.sql" "$B/"
mark "paquete de la aplicación construido en la Mac ($ARCH)"
"${SSH[@]}" 'rm -rf ~/app && mkdir -p ~/app'; "${SCP[@]}" -r "$B"/. "opc@127.0.0.1:app/"; "${SCP[@]}" "$RPMS"/*.rpm "opc@127.0.0.1:app/"
"${SSH[@]}" 'sudo install -d -m 0755 -o postgres -g postgres /var/lib/pgsql/drill-tools && sudo install -m 0755 -o postgres -g postgres ~/app/remote-restore.sh /var/lib/pgsql/drill-tools/ && sudo install -m 0644 -o postgres -g postgres ~/app/fingerprint.sql /var/lib/pgsql/drill-tools/'
mark "paquete copiado a la VM"
# 3. PostgreSQL 18 (idempotente) y aplicación (etapa 1)
"${SSH[@]}" 'mkdir -p ~/drill/rpms && cp ~/app/postgresql18-*.rpm ~/drill/rpms/ && sudo bash ~/app/install-postgres.sh ~/drill/rpms' | tee "$OUT/postgres-version.txt"; mark "PostgreSQL 18 instalado"
"${SSH[@]}" 'sudo bash ~/app/install-app.sh stage1 ~/app' | tee "$OUT/stage1.txt"; mark "etapa 1: Python, Nginx, entorno virtual (ruedas locales) y frontend"
# 4. Restauración de los datos en la base 'nexoeventos' (frase de paso nº 1, solo en la terminal)
"${SSH[@]}" "$RUNPG --check'"; echo ">> Frase de paso (1/2: datos)"
PLAIN="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['plaintext_dump_sha256'])" "$OUT/$BUNDLE.manifest.json")"
set +e; openssl cms -decrypt -binary -inform DER -in "$OUT/$BUNDLE.oci.cms" -inkey "$KEY" 2>"$OUT/openssl-datos.err" | "${SSH[@]}" "$RUNPG $PLAIN /var/lib/pgsql/drill-tools/fingerprint.sql'" | tee "$OUT/huella-restaurada.txt"; rc=("${PIPESTATUS[@]}"); set -e
[[ ${rc[0]} -eq 0 ]] || { echo "FALLÓ el descifrado local de los datos (openssl $rc)" >&2; exit 7; }; [[ ${rc[1]} -eq 0 ]] || { echo "FALLÓ la restauración remota (código ${rc[1]})" >&2; exit 8; }
python3 - "$ROOT/docs/multicloud/baseline-restauracion.json" "0008-estado-20261022" "$OUT/huella-restaurada.txt" <<'PY'
import json, sys
base = json.load(open(sys.argv[1]))["baselines"][sys.argv[2]]["fingerprint"]; now = dict(l.strip().split("=", 1) for l in open(sys.argv[3]) if "=" in l)
diff = {k: (base[k], now.get(k)) for k in base if base[k] != now.get(k)}
if diff: print("FALLÓ huella:", diff); sys.exit(1)
print(f"OK    huella idéntica a la línea base ({len(base)} claves)")
PY
mark "T_datos: datos restaurados y huella verificada"
# 5. Claves de aplicación originales (frase de paso nº 2): solo a tmpfs de la VM
echo ">> Frase de paso (2/2: claves de aplicación)"
set +e; openssl cms -decrypt -binary -inform DER -in "$OUT/$SECBUNDLE.oci.cms" -inkey "$KEY" 2>"$OUT/openssl-claves.err" | "${SSH[@]}" 'sudo bash ~/app/install-app-secrets.sh'; rc=("${PIPESTATUS[@]}"); set -e
[[ ${rc[0]} -eq 0 && ${rc[1]} -eq 0 ]] || { echo "FALLÓ la entrega de las claves de aplicación (openssl=${rc[0]}, ssh=${rc[1]})" >&2; exit 9; }
mark "claves originales entregadas a tmpfs (valores no mostrados)"
# 6. Etapa 2: rol de BD, entorno, TLS efímero, systemd, Nginx
"${SSH[@]}" 'sudo bash ~/app/install-app.sh stage2 ~/app' | tee "$OUT/stage2.txt"; mark "T_servicio: aplicación en marcha (healthz local correcto)"
# 7. Pruebas funcionales por el túnel HTTPS (sin ventas)
backend/.venv/bin/python "$HERE/oci-drill/app-smoke.py" --out "$OUT" --base "https://localhost:$HPORT" | tee "$OUT/smoke.txt"; mark "T_funcional: pruebas funcionales terminadas"
"${SSH[@]}" "sudo -u postgres bash -c 'cd /var/lib/pgsql && /usr/pgsql-18/bin/psql -d nexoeventos -At -f /var/lib/pgsql/drill-tools/fingerprint.sql'" | sort > "$OUT/huella-final.txt"
diff <(sort "$OUT/huella-restaurada.txt" | grep -E '^[a-z_0-9]+=') "$OUT/huella-final.txt" > "$OUT/huella-delta.txt" || true; echo "Delta de huella tras las pruebas (esperado: solo access_logs):"; cat "$OUT/huella-delta.txt"
mark "fin; duración total desde T0: $(( $(date +%s) - T0 )) s"; echo "Evidencias en $OUT"
