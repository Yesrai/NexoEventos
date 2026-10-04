#!/usr/bin/env bash
# Se ejecuta EN LA EC2 como root mediante SSM. No imprime URLs, credenciales,
# identificadores de usuarios, reservas, entradas ni tokens QR.
#
#   verify-restore.sh baseline
#   verify-restore.sh verify <host-restaurado> <baseline-base64>
#
# baseline obtiene el punto lógico esperado antes de declarar el incidente.
# verify exige coincidencia exacta de conteos, revisión Alembic y huella lógica;
# además descifra todas las entradas y verifica su hash sin mostrar el token.
set -euo pipefail
MODE="${1:-}"
[[ "$MODE" == "baseline" || "$MODE" == "verify" ]] || { echo "Modo inválido." >&2; exit 2; }
[[ "$(id -u)" == "0" ]] || { echo "Ejecutar como root." >&2; exit 2; }

BACKEND_ENV=/etc/nexoeventos/backend.env
MIGRATION_ENV=/etc/nexoeventos/migration.env
APP=/opt/nexoeventos/backend
[[ -r "$BACKEND_ENV" && -r "$MIGRATION_ENV" ]] || { echo "Faltan archivos protegidos de aplicación/migración." >&2; exit 1; }

set -a
source "$BACKEND_ENV"
source "$MIGRATION_ENV"
set +a
cd "$APP"

if [[ "$MODE" == "verify" ]]; then
  RESTORED_HOST="${2:-}"
  EXPECTED_BASELINE="${3:-}"
  [[ "$RESTORED_HOST" =~ ^nexoeventos-academy-restore-[a-z0-9-]+\.[a-z0-9.-]+\.rds\.amazonaws\.com$ ]] \
    || { echo "Host restaurado inválido." >&2; exit 2; }
  [[ "$EXPECTED_BASELINE" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Baseline inválido." >&2; exit 2; }
  export RESTORED_HOST EXPECTED_BASELINE
fi

"$APP/.venv/bin/python" - "$MODE" <<'PY'
import base64
import hashlib
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text

from app.ticket_tokens import reveal_ticket_secret, token_hash

TABLES = (
    "users", "events", "reservations", "operator_event_assignments", "tickets", "access_logs"
)


def target_url(url: str, host: str | None) -> str:
    if not host:
        return url
    src = urlsplit(url)
    userinfo, sep, hostport = src.netloc.rpartition("@")
    if not sep:
        raise SystemExit("URL de migración inválida.")
    port = hostport.rsplit(":", 1)[1] if ":" in hostport else "5432"
    return urlunsplit((src.scheme, f"{userinfo}@{host}:{port}", src.path, src.query, src.fragment))


def normalized(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return base64.urlsafe_b64encode(bytes(value)).decode("ascii")
    return str(value)


def inspect(url: str) -> dict:
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
    digest = hashlib.sha256()
    counts = {}
    qr_total = 0
    qr_valid = 0
    with engine.connect() as conn:
        conn.execute(text("SET ROLE nexoeventos_owner"))
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        for table in TABLES:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = conn.execute(text(f"SELECT * FROM {quoted} ORDER BY 1"))
            count = 0
            for row in rows:
                payload = [normalized(value) for value in row]
                digest.update(table.encode()); digest.update(b"\0")
                digest.update(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
                digest.update(b"\n")
                count += 1
            counts[table] = count
        for stored_hash, ciphertext in conn.execute(text("SELECT token_hash, token_ciphertext FROM tickets")):
            qr_total += 1
            try:
                qr_valid += token_hash(reveal_ticket_secret(ciphertext)) == stored_hash
            except Exception:
                pass
        orphan_reservations = conn.execute(text(
            "SELECT count(*) FROM reservations r LEFT JOIN users u ON u.id=r.user_id "
            "WHERE r.user_id IS NOT NULL AND u.id IS NULL"
        )).scalar_one()
    engine.dispose()
    return {"revision": revision, "counts": counts, "fingerprint": digest.hexdigest(),
            "qr_total": qr_total, "qr_valid": qr_valid, "orphan_reservations": orphan_reservations}


mode = sys.argv[1]
host = os.environ.get("RESTORED_HOST") if mode == "verify" else None
actual = inspect(target_url(os.environ["MIGRATION_DATABASE_URL"], host))
if actual["orphan_reservations"] != 0:
    raise SystemExit("Hay reservas con propietario inexistente.")
if actual["qr_total"] < 1 or actual["qr_valid"] != actual["qr_total"]:
    raise SystemExit("La validación criptográfica de entradas QR no fue completa.")

encoded = base64.urlsafe_b64encode(json.dumps(actual, sort_keys=True).encode()).decode().rstrip("=")
if mode == "baseline":
    print(f"BASELINE_B64={encoded}")
    print(f"BASELINE_OK revision={actual['revision']} tablas={len(TABLES)} entradas_qr={actual['qr_total']}")
else:
    raw = os.environ["EXPECTED_BASELINE"]
    expected = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    if actual != expected:
        safe_expected = {"revision": expected.get("revision"), "counts": expected.get("counts"),
                         "qr_total": expected.get("qr_total"), "qr_valid": expected.get("qr_valid")}
        safe_actual = {"revision": actual["revision"], "counts": actual["counts"],
                       "qr_total": actual["qr_total"], "qr_valid": actual["qr_valid"]}
        print("BASELINE_NO_COINCIDE=" + json.dumps({"esperado": safe_expected, "restaurado": safe_actual}, sort_keys=True))
        raise SystemExit(1)
    print(f"RESTAURACION_COINCIDE revision={actual['revision']} tablas={len(TABLES)} entradas_qr={actual['qr_total']}")
    print("VERIFICACION_RESTAURACION=OK")
PY
