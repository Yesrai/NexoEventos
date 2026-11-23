#!/usr/bin/env bash
# Prueba LOCAL y AISLADA del orquestador scripts/multicloud/oci-drill/run-from-mac.sh, SIN nubes: sustituye `oci`, `ssh` y `scp` por simuladores en un directorio temporal;
# la «VM» es un contenedor PostgreSQL 18 DESECHABLE nuevo (nexo-rfm-test; no toca ningún contenedor ni volumen existente) y las claves/datos son de prueba.
# Verifica: parámetros obligatorios, línea base configurable, comprobaciones previas antes de pedir la frase, fallos con su código, known_hosts por ejecución y que PREFLIGHT_ONLY no usa red.
# Uso: scripts/multicloud/test-run-from-mac.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"; H=scripts/multicloud
export PATH=/usr/bin:/opt/homebrew/bin:$PATH
DB=nexoeventos_rfmtest; C=nexo-rfm-test; PY=backend/.venv/bin/python
T="$(mktemp -d)"; chmod 700 "$T"
cleanup() { docker rm -f "$C" >/dev/null 2>&1 || true; psql postgres -q -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" >/dev/null 2>&1 || true; rm -rf "$T"; }
trap cleanup EXIT
pass=0; failn=0; ok() { echo "OK    $*"; pass=$((pass+1)); }; bad() { echo "FALLÓ $*"; failn=$((failn+1)); }

echo "== 1) Datos y claves de prueba"
psql postgres -q -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" -c "CREATE DATABASE $DB OWNER nexoeventos_owner" -c "GRANT CONNECT ON DATABASE $DB TO nexoeventos_app"
(cd backend && MIGRATION_DATABASE_URL="postgresql+psycopg:///$DB" .venv/bin/alembic upgrade head >/dev/null 2>&1)
$PY scripts/seed-demo-catalog.py --database-url "postgresql+psycopg:///$DB" >/dev/null
psql "$DB" -At <$H/fingerprint.sql | sort >"$T/base.txt"
$PY - "$T/base.txt" "$T/baseline.json" <<'PY'
import json, sys
fp = dict(l.strip().split("=", 1) for l in open(sys.argv[1]) if "=" in l)
json.dump({"schema": 1, "baselines": {"prueba": {"fingerprint": fp}}}, open(sys.argv[2], "w"))
PY
mkdir -p "$T/aws" "$T/ocikeys" "$T/bundle" "$T/rpms" "$T/shim" "$T/out"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/aws/k.pem" -out "$T/aws/c.crt" -days 2 -subj "/CN=test aws" 2>/dev/null
pg_dump --format=custom --no-owner --no-acl "$DB" >"$T/aws/test.dump"
openssl cms -encrypt -binary -aes-256-cbc -in "$T/aws/test.dump" -out "$T/aws/test.cms" -outform DER "$T/aws/c.crt"
NEXO_OCI_KEYDIR="$T/ocikeys" NEXO_TEST_NO_PASSPHRASE=1 $H/oci-recovery-keygen.sh >/dev/null
$H/prepare-oci-transfer.sh "$T/aws/test.cms" "$T/aws/k.pem" "$T/ocikeys/oci-recovery-public.crt" "$T/bundle" >/dev/null
echo x >"$T/rpms/postgresql18-prueba.rpm"; echo x >"$T/sshkey"; chmod 600 "$T/sshkey"
(cd "$T/rpms" && shasum -a 256 postgresql18-prueba.rpm >"$T/rpm-sums.sha256")
ok "base, volcado, cifrado «AWS» y re-cifrado «OCI» de prueba ($(wc -l <"$T/base.txt" | tr -d ' ') claves de huella)"

echo "== 2) «VM» desechable (contenedor nuevo) y simuladores de oci/ssh/scp"
docker run -d --rm --name "$C" -e POSTGRES_PASSWORD=drill-only postgres:18 >/dev/null
for _ in $(seq 60); do docker logs "$C" 2>&1 | grep -q "init process complete" && docker exec "$C" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
cat >"$T/shim/oci" <<'EOF'
#!/usr/bin/env bash
name=""; file=""; a=("$@")
for i in "${!a[@]}"; do [[ "${a[$i]}" == "--name" ]] && name="${a[$((i+1))]}"; [[ "${a[$i]}" == "--file" ]] && file="${a[$((i+1))]}"; done
echo "oci: $name" >> "$SHIM_LOG"; cp "$SHIM_BUNDLE_DIR/$(basename "$name")" "$file"
EOF
cat >"$T/shim/scp" <<'EOF'
#!/usr/bin/env bash
echo "scp: $*" >> "$SHIM_LOG"
EOF
cat >"$T/shim/ssh" <<'EOF'
#!/usr/bin/env bash
cmd="${@: -1}"; echo "ssh-args: $*" >> "$SHIM_LOG"
case "$cmd" in
  *"--check"*) echo "LISTO: PostgreSQL simulado (contenedor desechable)" ;;
  *"exec bash /var/lib/pgsql/drill-tools/remote-restore.sh"*)
    plain="$(sed -E 's/.*remote-restore.sh ([0-9a-f]{64}).*/\1/' <<<"$cmd")"; f="$SHIM_TMP/dump.$$"; cat >"$f"
    got="$(shasum -a 256 "$f" | cut -d' ' -f1)"
    if [[ "$got" != "$plain" ]]; then echo "FALLÓ: SHA-256 del volcado en claro distinto del manifiesto" >&2; rm -f "$f"; exit 4; fi
    docker exec "$SHIM_CONTAINER" psql -U postgres -qc "DROP DATABASE IF EXISTS drill" -c "CREATE DATABASE drill" >/dev/null
    docker exec -i "$SHIM_CONTAINER" pg_restore -U postgres -d drill --no-owner --no-acl --exit-on-error <"$f" || { rm -f "$f"; exit 5; }
    docker exec -i "$SHIM_CONTAINER" psql -U postgres -d drill -At <"$SHIM_ROOT/scripts/multicloud/fingerprint.sql"; rm -f "$f" ;;
  *install-postgres*) echo "PostgreSQL 18.6 (simulado)" ;;
esac
EOF
chmod +x "$T/shim/"*
export SHIM_LOG="$T/shim.log" SHIM_BUNDLE_DIR="$T/bundle" SHIM_TMP="$T" SHIM_CONTAINER="$C" SHIM_ROOT="$ROOT"
BASE_ENV=(env RPM_CHECKSUMS="$T/rpm-sums.sha256" PATH="$T/shim:$PATH" OCI_NS=nsprueba LPORT=2222 SSH_KEY="$T/sshkey" RPMS="$T/rpms" OUT_BASE="$T/out" RECOVERY_KEY="$T/ocikeys/oci-recovery-private.pem")
RUNNER=("$H/oci-drill/run-from-mac.sh")
reset_log() { : >"$SHIM_LOG"; }
ok "simuladores y contenedor «$C» listos"

echo "== 3) Casos"
reset_log
"${BASE_ENV[@]}" BUNDLE=test BASELINE_KEY=prueba BASELINE_FILE="$T/baseline.json" "${RUNNER[@]}" >"$T/r1.txt" 2>&1 && rc=0 || rc=$?
[[ $rc -eq 0 ]] && grep -q "huella idéntica" "$T/r1.txt" && ok "caso éxito: línea base y respaldo parametrizados, huella idéntica, código 0" || { bad "caso éxito (código $rc)"; tail -5 "$T/r1.txt"; }
grep -q "UserKnownHostsFile=$T/out/run-" "$SHIM_LOG" && ok "known_hosts por ejecución (no se usa ~/.ssh/known_hosts)" || bad "no se usó known_hosts por ejecución"
reset_log
"${BASE_ENV[@]}" BUNDLE=test BASELINE_KEY=inexistente BASELINE_FILE="$T/baseline.json" "${RUNNER[@]}" >"$T/r2.txt" 2>&1 && rc=0 || rc=$?
[[ $rc -eq 2 && ! -s "$SHIM_LOG" ]] && ok "clave de línea base inexistente: código 2 ANTES de usar red o pedir la frase (sin llamadas a oci/ssh)" || bad "línea base inexistente (código $rc; log: $(wc -l <"$SHIM_LOG"))"
reset_log; "${BASE_ENV[@]}" BUNDLE=test BASELINE_FILE="$T/baseline.json" env -u BASELINE_KEY "${RUNNER[@]}" >"$T/r3.txt" 2>&1 && rc=0 || rc=$?
[[ $rc -ne 0 && ! -s "$SHIM_LOG" ]] && ok "sin BASELINE_KEY: se rechaza (no hay valor por defecto)" || bad "sin BASELINE_KEY (código $rc)"
$PY - "$T/baseline.json" "$T/baseline-mala.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); fp = d["baselines"]["prueba"]["fingerprint"]; k = "events" if "events" in fp else next(iter(fp)); fp[k] = "999999"; json.dump(d, open(sys.argv[2], "w"))
PY
reset_log; "${BASE_ENV[@]}" BUNDLE=test BASELINE_KEY=prueba BASELINE_FILE="$T/baseline-mala.json" "${RUNNER[@]}" >"$T/r4.txt" 2>&1 && rc=0 || rc=$?
[[ $rc -eq 1 ]] && ok "línea base distinta: falla con código 1" || bad "línea base distinta (código $rc)"
reset_log; "${BASE_ENV[@]}" RECOVERY_KEY="$T/aws/k.pem" BUNDLE=test BASELINE_KEY=prueba BASELINE_FILE="$T/baseline.json" "${RUNNER[@]}" >"$T/r5.txt" 2>&1 && rc=0 || rc=$?
[[ $rc -eq 7 ]] && ok "clave privada equivocada: falla con código 7 (descifrado local)" || bad "clave equivocada (código $rc)"
mkdir -p "$T/bundle2"; cp "$T/bundle/test.oci.cms" "$T/bundle2/test.oci.cms"; cp "$T/bundle/test.manifest.json" "$T/bundle2/test.manifest.json"; printf 'X' | dd of="$T/bundle2/test.oci.cms" bs=1 seek=100 conv=notrunc 2>/dev/null
reset_log; "${BASE_ENV[@]}" SHIM_BUNDLE_DIR="$T/bundle2" BUNDLE=test BASELINE_KEY=prueba BASELINE_FILE="$T/baseline.json" "${RUNNER[@]}" >"$T/r6.txt" 2>&1 && rc=0 || rc=$?
[[ $rc -ne 0 ]] && ! grep -q "ssh-args" "$SHIM_LOG" && ok "archivo alterado: se detiene en verify-transfer antes de tocar la VM" || bad "archivo alterado (código $rc)"
mkdir -p "$T/bundle3"; cp "$T/bundle/test.oci.cms" "$T/bundle3/otro.oci.cms"; cp "$T/bundle/test.manifest.json" "$T/bundle3/otro.manifest.json"
reset_log; "${BASE_ENV[@]}" SHIM_BUNDLE_DIR="$T/bundle3" BUNDLE=otro BASELINE_KEY=prueba BASELINE_FILE="$T/baseline.json" "${RUNNER[@]}" >"$T/r7.txt" 2>&1 && rc=0 || rc=$?
[[ $rc -eq 3 ]] && ok "manifiesto de otro respaldo (nombre distinto de BUNDLE): código 3" || bad "manifiesto distinto (código $rc)"
reset_log; "${BASE_ENV[@]}" RPMS="$T/vacio" BUNDLE=test BASELINE_KEY=prueba BASELINE_FILE="$T/baseline.json" "${RUNNER[@]}" >"$T/r8.txt" 2>&1 && rc=0 || rc=$?
[[ $rc -eq 2 && ! -s "$SHIM_LOG" ]] && ok "sin RPM: código 2 antes de usar red" || bad "sin RPM (código $rc)"
echo "alterado" >"$T/rpms/postgresql18-prueba.rpm"
reset_log; "${BASE_ENV[@]}" BUNDLE=test BASELINE_KEY=prueba BASELINE_FILE="$T/baseline.json" "${RUNNER[@]}" >"$T/r10.txt" 2>&1 && rc=0 || rc=$?
[[ $rc -eq 2 && ! -s "$SHIM_LOG" ]] && ok "RPM alterado respecto a la lista fijada: código 2 antes de usar red" || bad "RPM alterado (código $rc)"
echo x >"$T/rpms/postgresql18-prueba.rpm"
before=$(ls "$T/out" | wc -l | tr -d ' '); reset_log
"${BASE_ENV[@]}" BUNDLE=test BASELINE_KEY=prueba BASELINE_FILE="$T/baseline.json" PREFLIGHT_ONLY=1 "${RUNNER[@]}" >"$T/r9.txt" 2>&1 && rc=0 || rc=$?
[[ $rc -eq 0 && ! -s "$SHIM_LOG" && "$(ls "$T/out" | wc -l | tr -d ' ')" == "$before" ]] && ok "PREFLIGHT_ONLY=1: código 0, sin red y sin crear directorios" || bad "PREFLIGHT_ONLY (código $rc)"
grep -q -i -E "passphrase|BEGIN .*PRIVATE" "$T"/r*.txt && bad "una salida contiene claves o frases" || ok "ninguna salida contiene claves ni frases de paso"
echo; echo "Resultado: $pass correctas, $failn fallidas"; [[ $failn -eq 0 ]]
