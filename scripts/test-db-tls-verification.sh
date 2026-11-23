#!/usr/bin/env bash
# Prueba local (sin nube): PostgreSQL temporal con TLS y una CA propia; comprueba qué acepta cada sslmode.
# Casos: require (no valida), verify-full con la CA correcta, con otra CA, con nombre distinto y sin TLS (rechazado por hostssl).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; PY="$ROOT/backend/.venv/bin/python"
T="$(mktemp -d /private/tmp/tlsdb.XXXXXX)"; PORT=55433
cleanup() { pg_ctl -D "$T/data" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$T"; }; trap cleanup EXIT
cd "$T"
mkca() { openssl req -x509 -newkey rsa:2048 -nodes -keyout "$1.key" -out "$1.crt" -days 2 -subj "/CN=$2" >/dev/null 2>&1; }
mkca ca "CA de prueba"; mkca otraca "Otra CA"
openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/CN=localhost" >/dev/null 2>&1
printf 'subjectAltName=DNS:localhost\n' > san.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 2 -extfile san.ext >/dev/null 2>&1
chmod 600 server.key
initdb -D data -A trust >/dev/null
cat >> data/postgresql.conf <<EOF
port = $PORT
listen_addresses = 'localhost'
unix_socket_directories = '$T'
ssl = on
ssl_cert_file = '$T/server.crt'
ssl_key_file = '$T/server.key'
EOF
printf 'hostssl all all 127.0.0.1/32 trust\nhostssl all all ::1/128 trust\n' > data/pg_hba.conf
pg_ctl -D data -l log -w start >/dev/null
"$PY" - "$T" "$PORT" <<'PY'
import sys, psycopg
t, port = sys.argv[1], sys.argv[2]
def case(nombre, host, **kw):
    try:
        with psycopg.connect(host=host, port=port, dbname="postgres", connect_timeout=5, **kw) as c:
            ssl = c.execute("select ssl from pg_stat_ssl where pid = pg_backend_pid()").fetchone()[0]
            return nombre, "CONECTA", f"TLS={ssl}"
    except Exception as e:  # noqa: BLE001
        return nombre, "RECHAZA", str(e).strip().splitlines()[-1][:90]
filas = [
    case("require (sin validar certificado)", "localhost", sslmode="require"),
    case("verify-full + CA correcta", "localhost", sslmode="verify-full", sslrootcert=f"{t}/ca.crt"),
    case("verify-full + OTRA CA", "localhost", sslmode="verify-full", sslrootcert=f"{t}/otraca.crt"),
    case("verify-full + nombre no incluido (127.0.0.1)", "127.0.0.1", sslmode="verify-full", sslrootcert=f"{t}/ca.crt"),
    case("disable (sin TLS; el servidor exige hostssl)", "localhost", sslmode="disable"),
]
esperado = ["CONECTA", "CONECTA", "RECHAZA", "RECHAZA", "RECHAZA"]
for (n, r, d), e in zip(filas, esperado):
    print(f"{'OK ' if r == e else 'FALLA'} | {n:48} | {r:8} | {d}")
sys.exit(0 if all(r == e for (_, r, _), e in zip(filas, esperado)) else 1)
PY
