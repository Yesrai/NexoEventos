#!/usr/bin/env bash
set -euo pipefail

: "${DUCKDNS_DOMAIN:?Falta DUCKDNS_DOMAIN}"
: "${DUCKDNS_TOKEN:?Falta DUCKDNS_TOKEN}"
if [[ ! "$DUCKDNS_DOMAIN" =~ ^[a-z0-9-]+$ ]] || [[ ! "$DUCKDNS_TOKEN" =~ ^[A-Za-z0-9-]+$ ]]; then
  echo "Configuración DuckDNS inválida." >&2
  exit 1
fi

response="$(printf '%s\n' \
  'url = "https://www.duckdns.org/update"' \
  "data = \"domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip=\"" \
  'silent' 'show-error' 'fail' | curl --config -)"
if [[ "$response" != "OK" ]]; then
  echo "DuckDNS rechazó la actualización." >&2
  exit 1
fi
echo "DuckDNS actualizado correctamente."
