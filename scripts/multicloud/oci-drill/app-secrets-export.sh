#!/usr/bin/env bash
# Exporta SOLO las dos claves de aplicación (TICKET_ENCRYPTION_KEY y SECURITY_HASH_KEY) de AWS Secrets Manager a un paquete CMS cifrado con el certificado público de recuperación de OCI.
# Separado del código y del respaldo de datos. Los valores viajan en una tubería (nunca a disco, nunca por pantalla ni registro). Requiere el laboratorio AWS activo (SOLO LECTURA).
# Uso:  app-secrets-export.sh --cert <oci-recovery-public.crt> --out <dir en work/>  [--secret-id nexoeventos/academy/backend-env] [--source aws|stdin]
#   --source stdin  lee el secreto de la entrada estándar (pruebas locales con datos ficticios). Por defecto: aws.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"; SRC=aws; SID="nexoeventos/academy/backend-env"
while [[ $# -gt 0 ]]; do case "$1" in --cert) CRT="$2"; shift 2;; --out) OUT="$2"; shift 2;; --secret-id) SID="$2"; shift 2;; --source) SRC="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
: "${CRT:?}" "${OUT:?}"
case "$(cd "$OUT" 2>/dev/null && pwd || echo x)" in "$ROOT"/work/*|"$ROOT"/work) ;; "$ROOT"/*) echo "Rechazado: salida solo en work/ (ignorado por Git) o fuera del repositorio." >&2; exit 1;; esac
grep -q 'BEGIN CERTIFICATE' "$CRT" && ! grep -q PRIVATE "$CRT" || { echo "--cert debe ser un certificado público." >&2; exit 2; }
umask 077; mkdir -p "$OUT"; TS="$(date -u +%Y%m%dT%H%M%SZ)"; DEST="$OUT/app-secrets-$TS.oci.cms"
fetch() { if [[ "$SRC" == aws ]]; then aws secretsmanager get-secret-value --secret-id "$SID" --query SecretString --output text; else cat; fi; }
# Filtra con lista blanca: solo esas dos claves salen del secreto (acepta JSON o líneas CLAVE=VALOR). Falla si falta alguna. No imprime valores.
fetch | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
want = ("TICKET_ENCRYPTION_KEY", "SECURITY_HASH_KEY")
try:
    data = json.loads(raw); assert isinstance(data, dict)
except Exception:
    data = dict(l.split("=", 1) for l in raw.splitlines() if "=" in l and not l.lstrip().startswith("#"))
missing = [k for k in want if not str(data.get(k, "")).strip()]
if missing:
    sys.stderr.write("Faltan claves en el secreto: %s\n" % ", ".join(missing)); sys.exit(3)
for k in want:
    v = str(data[k]).strip()
    if "\n" in v or "\r" in v:
        sys.stderr.write("Valor inválido (salto de línea) en %s\n" % k); sys.exit(4)
    sys.stdout.write("%s=%s\n" % (k, v))
' | openssl cms -encrypt -binary -aes-256-cbc -outform DER -out "$DEST" "$CRT"
sleep 0.2; [[ -s "$DEST" ]] || { rm -f "$DEST"; echo "No se generó el paquete cifrado." >&2; exit 4; }
python3 - "$DEST" "$TS" <<'PY' > "${DEST%.oci.cms}.manifest.json"
import hashlib, json, sys
d = open(sys.argv[1], "rb").read()
print(json.dumps({"schema": 1, "created_utc": sys.argv[2], "kind": "app-secrets", "keys": ["TICKET_ENCRYPTION_KEY", "SECURITY_HASH_KEY"],
                  "cms_sha256": hashlib.sha256(d).hexdigest(), "cms_bytes": len(d), "encryption": "CMS/DER AES-256-CBC, certificado de recuperación de OCI"}, indent=2))
PY
echo "Listo: $DEST ($(wc -c < "$DEST" | tr -d ' ') bytes) y manifiesto (solo nombres de claves y SHA-256). Subida (perfil de carga): oci os object put --profile NEXOEVENTOS_UPLOADER -ns <ns> --bucket-name nexoeventos-recovery --name secrets/\$(basename \"$DEST\") --file \"$DEST\""
