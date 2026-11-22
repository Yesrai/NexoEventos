#!/usr/bin/env bash
# En la VM (root): crea un archivo de swap si la RAM es pequeña (E2.1.Micro: ~0,5–1 GB; sin swap, dnf/PostgreSQL provocaron OOM el 23-oct). Idempotente.
# Variables: MIN_MEM_MB (2048: por debajo se crea swap) · SWAP_MB (2048) · SWAPFILE (/swapfile) · MEMINFO (/proc/meminfo) · DRY_RUN=1 (solo imprime lo que haría)
set -euo pipefail
MIN_MEM_MB="${MIN_MEM_MB:-2048}"; SWAP_MB="${SWAP_MB:-2048}"; SWAPFILE="${SWAPFILE:-/swapfile}"; MEMINFO="${MEMINFO:-/proc/meminfo}"
mem_mb=$(awk '/^MemTotal:/ {printf "%d", $2/1024}' "$MEMINFO")
run() { if [[ "${DRY_RUN:-}" == "1" ]]; then echo "DRY: $*"; else "$@"; fi; }
if (( mem_mb >= MIN_MEM_MB )); then echo "OK    RAM ${mem_mb} MB ≥ ${MIN_MEM_MB} MB: no hace falta swap"; exit 0; fi
if [[ "${DRY_RUN:-}" != "1" ]] && swapon --show=NAME --noheadings 2>/dev/null | grep -q .; then echo "OK    ya hay swap activa"; exit 0; fi
if [[ "${DRY_RUN:-}" != "1" && -f "$SWAPFILE" ]] && grep -q "$SWAPFILE" /etc/fstab 2>/dev/null; then run swapon "$SWAPFILE" 2>/dev/null || true; echo "OK    swap existente reactivada"; exit 0; fi
echo "RAM ${mem_mb} MB < ${MIN_MEM_MB} MB: creando swap de ${SWAP_MB} MB en $SWAPFILE"
run dd if=/dev/zero of="$SWAPFILE" bs=1M count="$SWAP_MB" status=none
run chmod 600 "$SWAPFILE"; run mkswap "$SWAPFILE" >/dev/null; run swapon "$SWAPFILE"
[[ "${DRY_RUN:-}" == "1" ]] && echo "DRY: añadir «$SWAPFILE none swap sw 0 0» a /etc/fstab" || { grep -q "$SWAPFILE" /etc/fstab || echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab; }
echo "OK    swap configurada"
