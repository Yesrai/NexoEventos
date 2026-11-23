#!/usr/bin/env bash
# En la VM (root): garantiza SWAP TOTAL ≥ SWAP_MB cuando la RAM es pequeña (E2.1.Micro: ~1 GB). Idempotente. Corrección del 22-nov-2026 (T3): antes se salía si «ya había swap», pero la imagen de OCI
# trae solo ~944 MB y dnf dejó la VM sin respuesta más de 20 minutos; ahora se AÑADE la diferencia hasta SWAP_MB.
# Variables: MIN_MEM_MB (2048: por debajo se garantiza swap) · SWAP_MB (2048) · SWAPFILE (/swapfile) · MEMINFO (/proc/meminfo) · SWAPS (/proc/swaps) · DRY_RUN=1 (solo imprime)
set -euo pipefail
MIN_MEM_MB="${MIN_MEM_MB:-2048}"; SWAP_MB="${SWAP_MB:-2048}"; SWAPFILE="${SWAPFILE:-/swapfile}"; MEMINFO="${MEMINFO:-/proc/meminfo}"; SWAPS="${SWAPS:-/proc/swaps}"
mem_mb=$(awk '/^MemTotal:/ {printf "%d", $2/1024}' "$MEMINFO")
have_mb=$( [[ -r "$SWAPS" ]] && awk 'NR>1 {s+=$3} END {printf "%d", s/1024}' "$SWAPS" || echo 0 )
run() { if [[ "${DRY_RUN:-}" == "1" ]]; then echo "DRY: $*"; else "$@"; fi; }
if (( mem_mb >= MIN_MEM_MB )); then echo "OK    RAM ${mem_mb} MB ≥ ${MIN_MEM_MB} MB: no hace falta swap"; exit 0; fi
if (( have_mb >= SWAP_MB )); then echo "OK    swap total ${have_mb} MB ≥ ${SWAP_MB} MB: suficiente"; exit 0; fi
if [[ "${DRY_RUN:-}" != "1" && -f "$SWAPFILE" ]] && swapon --show=NAME --noheadings 2>/dev/null | grep -qx "$SWAPFILE"; then echo "OK    $SWAPFILE ya está activo"; exit 0; fi
need_mb=$(( SWAP_MB - have_mb ))
echo "RAM ${mem_mb} MB < ${MIN_MEM_MB} MB y swap actual ${have_mb} MB < ${SWAP_MB} MB: añadiendo ${need_mb} MB en $SWAPFILE"
run dd if=/dev/zero of="$SWAPFILE" bs=1M count="$need_mb" status=none
run chmod 600 "$SWAPFILE"; run mkswap "$SWAPFILE" >/dev/null; run swapon "$SWAPFILE"
[[ "${DRY_RUN:-}" == "1" ]] && echo "DRY: añadir «$SWAPFILE none swap sw 0 0» a /etc/fstab" || { grep -q "$SWAPFILE" /etc/fstab || echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab; }
echo "OK    swap total ahora ≈ ${SWAP_MB} MB"
