#!/usr/bin/env bash
# Verifica un archivo contra su manifiesto: SHA-256 y tamaño del cifrado para OCI. Sirve para cada salto (estación local, objeto descargado de OCI, VM).
# Uso: verify-transfer.sh <manifiesto.json> <archivo.oci.cms>
set -euo pipefail
M="${1:?}"; F="${2:?}"
want="$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(d['oci_cms_sha256'],d['oci_cms_bytes'])" "$M")"
got="$({ command -v sha256sum >/dev/null 2>&1 && sha256sum "$F" || shasum -a 256 "$F"; } | cut -d' ' -f1) $(wc -c <"$F" | tr -d ' ')"
[[ "$want" == "$got" ]] && { echo "OK: SHA-256 y tamaño coinciden con el manifiesto."; exit 0; }
echo "FALLÓ: esperado '$want', obtenido '$got'." >&2; exit 1
