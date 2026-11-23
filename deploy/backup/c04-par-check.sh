#!/usr/bin/env bash
# C-04: comprueba el archivo de la URL del PAR SIN imprimir la URL ni ningún fragmento (solo líneas «OK …/FALLÓ …» con resultados booleanos). EN LA EC2, como root:
#   bash /opt/nexoeventos-c04/deploy/backup/c04-par-check.sh [/etc/nexoeventos/c04/backup-par.url]
set -uo pipefail
F="${1:-/etc/nexoeventos/c04/backup-par.url}"; BUCKET="${NEXO_PAR_BUCKET:-nexoeventos-recovery}"; PREFIX="${NEXO_PAR_PREFIX:-backups/c04-20261119/}"
CFG="${NEXO_C04_CONFIG:-/etc/nexoeventos/c04/backup.json}"
fail=0; ok() { echo "OK    $1"; }; bad() { echo "FALLÓ $1"; fail=1; }
[[ -f "$F" && ! -L "$F" ]] || { echo "FALLÓ el archivo no existe o es un enlace"; exit 1; }
[[ "$(stat -c '%a %U:%G' "$F")" == "600 root:root" ]] && ok "permisos 0600 root:root" || bad "permisos distintos de 0600 root:root"
n="$(wc -c <"$F" | tr -d ' ')"; (( n > 80 && n < 600 )) && ok "tamaño plausible ($n bytes)" || bad "tamaño inesperado ($n bytes)"
[[ "$(grep -c '' "$F")" == 1 || "$(tail -c1 "$F" | wc -l)" == 0 && "$(grep -c '' "$F")" == 1 ]] && ok "una sola línea" || bad "más de una línea"
! grep -qE '[[:space:]]' <(tr -d '\n' <"$F") && ok "sin espacios ni tabuladores" || bad "contiene espacios"
grep -qE '^https://objectstorage\.sa-saopaulo-1\.oraclecloud\.com/p/' "$F" && ok "https, región São Paulo y ruta de PAR (/p/…)" || bad "esquema, anfitrión o ruta de PAR inesperados"
! grep -q '?' "$F" && ok "sin cadena de consulta" || bad "contiene «?»"
# Un PAR con prefijo puede devolver una URL que termina en «/o/» (el prefijo lo impone el servidor sobre el NOMBRE del objeto) o que ya trae el prefijo. En ambos casos el nombre
# efectivo que sube backup_cycle.py (URL + «object_prefix» + «<prefix>-<fecha>.cms») debe caer dentro del prefijo autorizado. No se imprime ni se modifica la URL.
grep -qE "^https://[^/]+/p/[A-Za-z0-9_-]{20,}/n/[A-Za-z0-9_-]+/b/${BUCKET}/o/" "$F" && ok "apunta al bucket $BUCKET (ruta /p/…/n/…/b/$BUCKET/o/…)" || bad "bucket distinto del autorizado o ruta mal formada"
tail_path="$(sed -E 's#^.*/b/[^/]+/o/##' "$F" | tr -d '\n')"
if [[ -z "$tail_path" ]]; then forma="vacia"; ok "la ruta termina en /o/ (el prefijo lo impone el servidor; el cliente debe anteponerlo al nombre)"
elif [[ "$tail_path" == "$PREFIX" ]]; then forma="igual"; ok "la ruta ya termina EXACTAMENTE en el prefijo autorizado"
else forma="otra"; bad "la ruta termina en algo distinto de /o/ o del prefijo autorizado"; fi
if [[ "$forma" == "vacia" ]]; then
  if /usr/bin/python3 - "$CFG" "$PREFIX" <<'PY'
import json, sys
p = json.load(open(sys.argv[1])).get("object_prefix", "")
sys.exit(0 if p == sys.argv[2] else 1)
PY
  then ok "el «object_prefix» del JSON es exactamente el prefijo autorizado: los objetos caen dentro del alcance del PAR"
  else bad "el «object_prefix» del JSON falta o NO es el prefijo autorizado: los PUT caerían FUERA del alcance del PAR"; fi
fi
# Identidad del certificado destinatario: el perfil debe fijar su huella SHA-256 y el archivo de certificado debe tenerla (no se confía en el nombre del archivo).
if /usr/bin/python3 - "$CFG" <<'PY'
import json, subprocess, sys, hashlib
try:
    c = json.load(open(sys.argv[1])); want = str(c.get("cert_sha256", "")).replace(":", "").lower()
    der = subprocess.run(["openssl", "x509", "-in", c["cert"], "-outform", "DER"], capture_output=True).stdout
    sys.exit(0 if len(want) == 64 and der and hashlib.sha256(der).hexdigest() == want else 1)
except Exception:
    sys.exit(1)
PY
then ok "el certificado del perfil tiene la huella SHA-256 fijada en «cert_sha256»"
else bad "el perfil no fija «cert_sha256» o el certificado NO tiene esa huella"; fi
(( fail )) && { echo "Hay fallos."; exit 1; } || echo "Archivo del PAR conforme (sin mostrar su contenido)."
