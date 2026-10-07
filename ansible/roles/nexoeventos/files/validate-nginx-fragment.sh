#!/usr/bin/env bash
set -euo pipefail

CANDIDATE="${1:?falta el fragmento candidato}"
LIVE=/etc/nginx/conf.d/nexoeventos.conf
BACKUP="$(mktemp)"
HAD_LIVE=0
if [[ -f "$LIVE" ]]; then
  cp -p -- "$LIVE" "$BACKUP"
  HAD_LIVE=1
fi
restore() {
  if [[ "$HAD_LIVE" == 1 ]]; then cp -p -- "$BACKUP" "$LIVE"; else rm -f -- "$LIVE"; fi
  rm -f -- "$BACKUP"
}
trap restore EXIT
cp -- "$CANDIDATE" "$LIVE"
/usr/sbin/nginx -t
