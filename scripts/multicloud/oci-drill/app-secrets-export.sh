#!/usr/bin/env bash
# Exporta SOLO las dos claves de aplicación (TICKET_ENCRYPTION_KEY y SECURITY_HASH_KEY) de AWS Secrets Manager a un paquete CMS cifrado con el certificado público de recuperación de OCI.
# Separado del código y del respaldo de datos. Los valores viajan en una tubería (nunca a disco, nunca por pantalla ni registro). Requiere el laboratorio AWS activo (SOLO LECTURA).
# Uso:  app-secrets-export.sh --cert <certificado-destinatario.crt> --out <dir en work/>  [--secret-id nexoeventos/academy/backend-env] [--source aws|stdin]
#       [--kind c04 --cert-sha256 <huella> (--sign-key <clave-de-firma.pem> | --defer-sign)]   modo C-04: rechaza un certificado con otra huella, nombra el paquete <ID>.cms + .manifest.json + .manifest.json.sig
#       y guarda en el manifiesto la huella del destinatario y el SHA-256 de CADA clave (no los valores): así quien restaura comprueba que entrega las ORIGINALES, sin ver su contenido.
#   --source stdin  lee el secreto de la entrada estándar (pruebas locales con datos ficticios). Por defecto: aws.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"; SRC=aws; SID="nexoeventos/academy/backend-env"
KIND=legacy; PIN=""; SIGNK=""; DEFER=0
while [[ $# -gt 0 ]]; do case "$1" in --kind) KIND="$2"; shift 2;; --cert-sha256) PIN="$(printf %s "$2" | tr -d : | tr A-F a-f)"; shift 2;; --sign-key) SIGNK="$2"; shift 2;; --defer-sign) DEFER=1; shift;; --cert) CRT="$2"; shift 2;; --out) OUT="$2"; shift 2;; --secret-id) SID="$2"; shift 2;; --source) SRC="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
: "${CRT:?}" "${OUT:?}"
case "$(cd "$OUT" 2>/dev/null && pwd || echo x)" in "$ROOT"/work/*|"$ROOT"/work) ;; "$ROOT"/*) echo "Rechazado: salida solo en work/ (ignorado por Git) o fuera del repositorio." >&2; exit 1;; esac
grep -q 'BEGIN CERTIFICATE' "$CRT" && ! grep -q PRIVATE "$CRT" || { echo "--cert debe ser un certificado público." >&2; exit 2; }
if [[ "$KIND" == c04 ]]; then
  [[ -n "$PIN" && ( "$DEFER" == 1 || ( -n "$SIGNK" && -r "$SIGNK" ) ) ]] || { echo "Modo c04: son obligatorios --cert-sha256 y --sign-key (o --defer-sign: el manifiesto se firma después con sign-manifest-remote.sh)." >&2; exit 2; }
  [[ "$(openssl x509 -in "$CRT" -outform DER | openssl sha256 | awk '{print $NF}')" == "$PIN" ]] || { echo "El certificado NO tiene la huella SHA-256 esperada: no se exporta." >&2; exit 10; }
  SUF=.cms
else SUF=.oci.cms; fi
umask 077; mkdir -p "$OUT"; TS="$(date -u +%Y%m%dT%H%M%SZ)"; DEST="$OUT/app-secrets-$TS$SUF"; SECFP="$(mktemp)"; trap 'grep -v "^SHA256 " "$SECFP" >&2 || true; rm -f "$SECFP"' EXIT
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
    sys.stderr.write("SHA256 %s=%s\n" % (k, __import__("hashlib").sha256(v.encode()).hexdigest()))
' 2>"$SECFP" | openssl cms -encrypt -binary -aes-256-cbc -outform DER -out "$DEST" "$CRT"
sleep 0.2; [[ -s "$DEST" ]] || { rm -f "$DEST"; echo "No se generó el paquete cifrado." >&2; exit 4; }
MAN="${DEST%$SUF}.manifest.json"
python3 - "$DEST" "$TS" "$SECFP" "$PIN" "$KIND" "$(basename "${DEST%$SUF}")" <<'PY' > "$MAN"
import hashlib, json, sys
d = open(sys.argv[1], "rb").read()
sec = dict(l.strip().split(" ", 1)[1].split("=", 1) for l in open(sys.argv[3]) if l.startswith("SHA256 "))
m = {"schema": 1, "created_utc": sys.argv[2], "kind": "app-secrets", "keys": ["TICKET_ENCRYPTION_KEY", "SECURITY_HASH_KEY"],
     "cms_sha256": hashlib.sha256(d).hexdigest(), "cms_bytes": len(d), "encryption": "CMS/DER AES-256-CBC, certificado de recuperación"}
if sys.argv[5] == "c04":
    m.update({"name": sys.argv[6], "recipient_cert_sha256": sys.argv[4], "secret_sha256": sec})   # SHA-256 de cada valor (no el valor): prueba de que son las originales
print(json.dumps(m, indent=2))
PY
if [[ "$KIND" == c04 && "$DEFER" != 1 ]]; then openssl dgst -sha256 -sign "$SIGNK" -out "$MAN.sig" "$MAN"; fi
[[ "$DEFER" == 1 ]] && echo "AVISO: manifiesto SIN firmar (--defer-sign): fírmelo con sign-manifest-remote.sh antes de subirlo." >&2
echo "Listo: $DEST ($(wc -c < "$DEST" | tr -d ' ') bytes) y manifiesto (solo nombres de claves y SHA-256). Subida (perfil de carga): oci os object put --profile NEXOEVENTOS_UPLOADER -ns <ns> --bucket-name nexoeventos-recovery --name secrets/\$(basename \"$DEST\") --file \"$DEST\""
