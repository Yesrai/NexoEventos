#!/usr/bin/env bash
# Prepara la copia para OCI en la estación local: verifica el SHA-256 del CMS de AWS, lo DESCIFRA con la clave de AWS y lo RE-CIFRA con el certificado de
# recuperación de OCI en una sola tubería (el texto plano no toca el disco), y escribe un manifiesto con SHA-256 del original, del cifrado para OCI y del
# volcado en claro (para verificarlo tras restaurar). No sube nada ni usa nubes.
# Uso: [NEXO_AWS_KEY_PASSIN=env:VAR|file:RUTA|fd:N] prepare-oci-transfer.sh <origen-aws.cms> <clave-privada-aws.pem> <certificado-oci.crt> <directorio-salida> [sha256-esperado-del-origen]
# Si la clave de AWS está protegida con contraseña, NEXO_AWS_KEY_PASSIN indica de dónde leerla (nunca como argumento visible; «pass:» se rechaza).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-cms-key.sh"
SRC="${1:?}"; AWS_KEY="${2:?}"; OCI_CRT="${3:?}"; OUT="${4:?}"; EXPECT="${5:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
case "$(cd "$OUT" 2>/dev/null && pwd || echo x)" in "$ROOT"/work/*|"$ROOT"/work) ;; "$ROOT"/*) echo "Rechazado: la salida debe estar en work/ (ignorado por Git) o fuera del repositorio." >&2; exit 1;; esac
umask 077; mkdir -p "$OUT"
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
src_sha="$(sha "$SRC")"
[[ -z "$EXPECT" || "$src_sha" == "$EXPECT" ]] || { echo "SHA-256 del origen distinto del esperado; abortado." >&2; exit 3; }
name="$(basename "$SRC" .cms)"; dest="$OUT/$name.oci.cms"; plain_sha_file="$(mktemp)"; magic_file="$(mktemp)"; trap 'rm -f "$plain_sha_file" "$magic_file"' EXIT
if ! { cms_decrypt_key "$SRC" "$AWS_KEY" "${NEXO_AWS_KEY_PASSIN:-}" - \
  | tee >(shasum -a 256 | cut -d' ' -f1 >"$plain_sha_file") >({ head -c 5 >"$magic_file"; cat >/dev/null; }) \
  | openssl cms -encrypt -binary -aes-256-cbc -outform DER -out "$dest" "$OCI_CRT"; }; then
  rm -f "$dest"  # un descifrado fallido no debe dejar un CMS «vacío» con apariencia válida
  echo "Fallo al descifrar o re-cifrar; no se generó ninguna copia para OCI." >&2; exit 5
fi
# Las sustituciones de procesos terminan de forma asíncrona: se espera (máx. 5 s) a que el SHA-256 y la cabecera estén completos.
for _ in $(seq 1 50); do [[ "$(wc -c <"$plain_sha_file" | tr -d ' ')" -ge 64 && "$(wc -c <"$magic_file" | tr -d ' ')" -ge 5 ]] && break; sleep 0.1; done
# Una clave equivocada puede «descifrar» a basura con código 0: se exige la cabecera de un volcado de PostgreSQL (formato custom).
if [[ "$(cat "$magic_file")" != "PGDMP" ]]; then
  rm -f "$dest"; echo "Lo descifrado no es un volcado PGDMP (¿clave equivocada o archivo alterado?); no se generó ninguna copia para OCI." >&2; exit 6
fi
[[ -s "$dest" ]] || { echo "No se generó la copia cifrada para OCI." >&2; rm -f "$dest"; exit 4; }
python3 - "$name" "$src_sha" "$(sha "$dest")" "$(cat "$plain_sha_file")" "$(wc -c <"$SRC" | tr -d ' ')" "$(wc -c <"$dest" | tr -d ' ')" "$OUT/$name.manifest.json" <<'PY'
import json, sys, datetime
name, src, dst, plain, ssz, dsz, out = sys.argv[1:]
json.dump({"schema": 1, "name": name, "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "source_cms_sha256": src, "source_cms_bytes": int(ssz), "oci_cms_sha256": dst, "oci_cms_bytes": int(dsz), "plaintext_dump_sha256": plain,
           "encryption": "CMS/DER AES-256-CBC, certificado de recuperación de OCI (clave independiente de la de AWS)",
           "object_name": f"backups/{name}.oci.cms"}, open(out, "w"), indent=1)
PY
echo "Listo: $dest (sha256 $(sha "$dest" | cut -c1-12)…) y manifiesto $OUT/$name.manifest.json"
