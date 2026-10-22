#!/usr/bin/env bash
# Prueba LOCAL de extremo a extremo (sin nubes, con claves DESECHABLES creadas en un directorio temporal fuera del repositorio):
# base local con reservas reales de ensayo → pg_dump → CMS con una clave «AWS» de prueba → prepare-oci-transfer (re-cifrado con una clave «OCI»
# independiente) → verify-transfer → restore-drill en PostgreSQL 18 desechable (Docker) comparando la huella. Incluye casos negativos (archivo alterado,
# clave equivocada, línea base distinta, hash esperado distinto, claves dentro del repositorio). Uso: scripts/multicloud/test-restore-pipeline.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"; H=scripts/multicloud
export PATH=/usr/bin:/opt/homebrew/bin:$PATH
DB=nexoeventos_mctest; T="$(mktemp -d)"; PY=backend/.venv/bin/python; PORT=8041; KEY="$($PY -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
cleanup() { pkill -f "uvicorn app.main:app --host 127.0.0.1 --port $PORT" 2>/dev/null || true; psql postgres -q -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" 2>/dev/null || true; docker rm -f nexo-restore-drill >/dev/null 2>&1 || true; rm -rf "$T"; }
trap cleanup EXIT
pass=0; failn=0; ok() { echo "OK    $*"; pass=$((pass+1)); }; bad() { echo "FALLÓ $*"; failn=$((failn+1)); }
expect_fail() { local name="$1"; shift; if "$@" >"$T/out.txt" 2>&1; then bad "$name (debía fallar)"; else ok "$name (falla como se espera)"; fi; }

echo "== 1) Base local con reservas de ensayo"
psql postgres -q -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" -c "CREATE DATABASE $DB OWNER nexoeventos_owner" -c "GRANT CONNECT ON DATABASE $DB TO nexoeventos_app"
(cd backend && MIGRATION_DATABASE_URL="postgresql+psycopg:///$DB" .venv/bin/alembic upgrade head >/dev/null 2>&1)
$PY scripts/seed-demo-catalog.py --database-url "postgresql+psycopg:///$DB" >/dev/null
(cd backend && DATABASE_URL="postgresql+psycopg://nexoeventos_app@/$DB" TICKET_ENCRYPTION_KEY="$KEY" FRONTEND_ORIGINS=http://localhost:5173 APP_ENV=development nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT >/dev/null 2>&1 &)
for _ in $(seq 40); do curl -sf "http://127.0.0.1:$PORT/ready" >/dev/null && break; sleep 0.5; done
$PY scripts/rehearsal/phase.py seed "http://127.0.0.1:$PORT" "$T/state.json" | sed 's/^/      /'
pkill -f "uvicorn app.main:app --host 127.0.0.1 --port $PORT"; sleep 1
psql "$DB" -At <$H/fingerprint.sql | sort >"$T/base.txt"
$PY - "$T/base.txt" "$T/baseline.json" <<'PY'
import json, sys
fp = dict(l.strip().split("=", 1) for l in open(sys.argv[1]) if "=" in l)
json.dump({"schema": 1, "baselines": {"prueba": {"fingerprint": fp}}}, open(sys.argv[2], "w"))
PY
ok "huella de origen calculada ($(wc -l <"$T/base.txt" | tr -d ' ') claves; $(grep ^reservations= "$T/base.txt"))"

echo "== 2) Respaldo cifrado «AWS» (clave de prueba) y transferencia preparada para «OCI» (clave independiente)"
mkdir -p "$T/aws" "$T/ocikeys" "$T/out"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/aws/aws-private.pem" -out "$T/aws/aws-public.crt" -days 2 -subj "/CN=test aws" 2>/dev/null
pg_dump --format=custom --no-owner --no-acl "$DB" >"$T/aws/test.dump"
dump_sha="$(shasum -a 256 "$T/aws/test.dump" | cut -d' ' -f1)"
openssl cms -encrypt -binary -aes-256-cbc -in "$T/aws/test.dump" -out "$T/aws/test.cms" -outform DER "$T/aws/aws-public.crt"
NEXO_OCI_KEYDIR="$T/ocikeys" NEXO_TEST_NO_PASSPHRASE=1 $H/oci-recovery-keygen.sh >/dev/null && ok "par de claves independiente de OCI generado fuera del repositorio"
[[ "$(openssl x509 -in $T/aws/aws-public.crt -noout -fingerprint -sha256)" != "$(openssl x509 -in $T/ocikeys/oci-recovery-public.crt -noout -fingerprint -sha256)" ]] && ok "las claves de AWS y OCI son distintas"
src_sha="$(shasum -a 256 "$T/aws/test.cms" | cut -d' ' -f1)"
$H/prepare-oci-transfer.sh "$T/aws/test.cms" "$T/aws/aws-private.pem" "$T/ocikeys/oci-recovery-public.crt" "$T/out" "$src_sha" >/dev/null && ok "descifrado + re-cifrado en tubería y manifiesto"
[[ "$(python3 -c "import json;print(json.load(open('$T/out/test.manifest.json'))['plaintext_dump_sha256'])")" == "$dump_sha" ]] && ok "el manifiesto registra el SHA-256 del volcado en claro"
ls "$T/out" | grep -qv "\.dump$" && ! ls "$T/out" | grep -q "dump" && ok "no quedó ningún volcado en claro en la salida"
$H/verify-transfer.sh "$T/out/test.manifest.json" "$T/out/test.oci.cms" >/dev/null && ok "verify-transfer: hash y tamaño correctos"

echo "== 3) Simulacro de restauración aislado (PostgreSQL 18 desechable)"
$H/restore-drill.sh --manifest "$T/out/test.manifest.json" --cms "$T/out/test.oci.cms" --key "$T/ocikeys/oci-recovery-private.pem" --baseline "$T/baseline.json" --baseline-key prueba --mode docker | sed 's/^/      /' && ok "restauración verificada con huella idéntica"
docker ps --format '{{.Names}}' | grep -q nexo-restore-drill && bad "el contenedor del simulacro no se destruyó" || ok "contenedor y material temporal destruidos"

echo "== 4) Casos negativos"
cp "$T/out/test.oci.cms" "$T/out/tampered.oci.cms"; printf 'X' | dd of="$T/out/tampered.oci.cms" bs=1 seek=100 conv=notrunc 2>/dev/null
expect_fail "archivo alterado: verify-transfer" $H/verify-transfer.sh "$T/out/test.manifest.json" "$T/out/tampered.oci.cms"
expect_fail "archivo alterado: simulacro" $H/restore-drill.sh --manifest "$T/out/test.manifest.json" --cms "$T/out/tampered.oci.cms" --key "$T/ocikeys/oci-recovery-private.pem" --baseline "$T/baseline.json" --baseline-key prueba --mode docker
expect_fail "clave equivocada (la de AWS)" $H/restore-drill.sh --manifest "$T/out/test.manifest.json" --cms "$T/out/test.oci.cms" --key "$T/aws/aws-private.pem" --baseline "$T/baseline.json" --baseline-key prueba --mode docker
python3 - "$T/baseline.json" "$T/baseline-mala.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["baselines"]["prueba"]["fingerprint"]["reservations"] = "999"; json.dump(d, open(sys.argv[2], "w"))
PY
expect_fail "línea base distinta" $H/restore-drill.sh --manifest "$T/out/test.manifest.json" --cms "$T/out/test.oci.cms" --key "$T/ocikeys/oci-recovery-private.pem" --baseline "$T/baseline-mala.json" --baseline-key prueba --mode docker
expect_fail "SHA-256 esperado del origen distinto" $H/prepare-oci-transfer.sh "$T/aws/test.cms" "$T/aws/aws-private.pem" "$T/ocikeys/oci-recovery-public.crt" "$T/out2" 0000
expect_fail "claves dentro del repositorio" env NEXO_OCI_KEYDIR="$ROOT/work/claves-prueba" NEXO_TEST_NO_PASSPHRASE=1 $H/oci-recovery-keygen.sh
expect_fail "salida de la transferencia dentro del repositorio (fuera de work/)" $H/prepare-oci-transfer.sh "$T/aws/test.cms" "$T/aws/aws-private.pem" "$T/ocikeys/oci-recovery-public.crt" "$ROOT/docs"
echo; echo "Resultado: $pass correctas, $failn fallidas"; [[ $failn -eq 0 ]]
