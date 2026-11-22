#!/usr/bin/env bash
# En la VM (root): recibe por stdin SOLO las dos claves de aplicación (llegan descifradas por el túnel SSH desde la Mac de la propietaria) y las deja en tmpfs (0600).
# No imprime ni registra valores. Se borran al reiniciar o al destruir la VM.
set -euo pipefail
SD="${NEXO_SECRETS_DIR:-/run/nexoeventos}"
install -d -m 0700 "$SD"
umask 077; T="$(mktemp $SD/.sec.XXXXXX)"; trap 'shred -u "$T" 2>/dev/null || rm -f "$T"' EXIT
cat > "$T"
[[ "$(grep -cE '^(TICKET_ENCRYPTION_KEY|SECURITY_HASH_KEY)=.{16,}$' "$T")" == 2 && "$(wc -l < "$T" | tr -d ' ')" == 2 ]] || { echo "FALLÓ: se esperaban exactamente las dos claves de aplicación" >&2; exit 3; }
install -m 0600 "$T" "$SD/secrets.env"
echo "OK    claves de aplicación instaladas en tmpfs (2 variables; valores no mostrados)"
# SHA-256 de cada VALOR (no el valor): el orquestador lo compara con el del manifiesto para comprobar que son las claves ORIGINALES
for k in TICKET_ENCRYPTION_KEY SECURITY_HASH_KEY; do printf 'SHA256 %s=%s\n' "$k" "$(sed -n "s/^$k=//p" "$T" | tr -d '\n' | { command -v sha256sum >/dev/null && sha256sum || shasum -a 256; } | cut -d' ' -f1)"; done
