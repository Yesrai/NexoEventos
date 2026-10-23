#!/usr/bin/env bash
# En la VM (root): recibe por stdin SOLO las dos claves de aplicación (llegan descifradas por el túnel SSH desde la Mac de la propietaria) y las deja en tmpfs (0600).
# No imprime ni registra valores. Se borran al reiniciar o al destruir la VM.
set -euo pipefail
install -d -m 0700 /run/nexoeventos
umask 077; T="$(mktemp /run/nexoeventos/.sec.XXXXXX)"; trap 'shred -u "$T" 2>/dev/null || rm -f "$T"' EXIT
cat > "$T"
[[ "$(grep -cE '^(TICKET_ENCRYPTION_KEY|SECURITY_HASH_KEY)=.{16,}$' "$T")" == 2 && "$(wc -l < "$T")" == 2 ]] || { echo "FALLÓ: se esperaban exactamente las dos claves de aplicación" >&2; exit 3; }
install -m 0600 "$T" /run/nexoeventos/secrets.env
echo "OK    claves de aplicación instaladas en tmpfs (2 variables; valores no mostrados)"
