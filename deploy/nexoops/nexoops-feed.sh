#!/usr/bin/env bash
# Espejo de SOLO LECTURA del estado de ops-center para NexoOps (incidente A1: /var/lib/ops-center es 0700 opscenter y el
# recolector fuerza 0600 en cada ciclo). Corre como opscenter:nexoops; copia SOLO lo que NexoOps lee (status, audit.jsonl,
# requests/rq-*.json), nunca identities.json. NexoOps no puede escribir en ops-center ni en este espejo.
set -euo pipefail
SRC="${1:-/var/lib/ops-center}"; DST="${2:-/var/lib/nexoops-feed}"
umask 0027
install -d -m 0750 "$DST/status" "$DST/requests"
cp_ro() { [[ -f "$1" ]] || return 0; local t; t="$(mktemp "$(dirname "$2")/.tmp-XXXXXX")"; cat "$1" > "$t"; chmod 0640 "$t"; mv -f "$t" "$2"; }
cp_ro "$SRC/status/cloud-status.json" "$DST/status/cloud-status.json"
if [[ -f "$SRC/status/probe-history.jsonl" ]]; then t="$(mktemp "$DST/status/.tmp-XXXXXX")"; tail -n 500 "$SRC/status/probe-history.jsonl" > "$t"; chmod 0640 "$t"; mv -f "$t" "$DST/status/probe-history.jsonl"; fi
cp_ro "$SRC/audit.jsonl" "$DST/audit.jsonl"
shopt -s nullglob; for f in "$SRC"/requests/rq-*.json; do cp_ro "$f" "$DST/requests/$(basename "$f")"; done
for f in "$DST"/requests/rq-*.json; do [[ -f "$SRC/requests/$(basename "$f")" ]] || rm -f "$f"; done
