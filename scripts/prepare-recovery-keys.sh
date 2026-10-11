#!/usr/bin/env bash
# Descifra las claves QR/hash al directorio ignorado y protegido de una ejecución.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${1:-}"
[[ "$RUN_ID" =~ ^[0-9]{8}t[0-9]{4}$ ]] || { echo "Uso: $0 AAAAMMDDtHHMM" >&2; exit 2; }
PRIVATE_KEY="${NEXO_RECOVERY_PRIVATE_KEY:-$HOME/.nexoeventos/recovery/qr-recovery-private.pem}"
ENVELOPE="${NEXO_RECOVERY_KEYS_ENVELOPE:-$HOME/.nexoeventos/recovery/nexoeventos-qr-keys.rsa}"
[[ -f "$PRIVATE_KEY" && -f "$ENVELOPE" ]] || { echo "Falta el respaldo externo de claves." >&2; exit 1; }
DESTINATION="$ROOT/work/recuperacion-completa/$RUN_ID/keys.env"
install -d -m 700 "$(dirname "$DESTINATION")"
umask 077
openssl pkeyutl -decrypt -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 \
  -inkey "$PRIVATE_KEY" -in "$ENVELOPE" -out "$DESTINATION"
chmod 600 "$DESTINATION"
python3 - "$DESTINATION" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text().splitlines()
values = dict(line.split("=", 1) for line in lines if "=" in line)
if set(values) != {"TICKET_ENCRYPTION_KEY", "SECURITY_HASH_KEY"}:
    raise SystemExit("El respaldo no contiene exactamente las dos claves esperadas.")
if not re.fullmatch(r"[A-Za-z0-9_-]{43}=", values["TICKET_ENCRYPTION_KEY"]):
    raise SystemExit("TICKET_ENCRYPTION_KEY no tiene formato Fernet.")
if not re.fullmatch(r"[A-Za-z0-9_-]{43,}", values["SECURITY_HASH_KEY"]):
    raise SystemExit("SECURITY_HASH_KEY no tiene el formato esperado.")
PY
echo "Claves de recuperación preparadas en archivo 0600 ignorado (valores no mostrados)."
