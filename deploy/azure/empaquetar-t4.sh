#!/usr/bin/env bash
# Construye el paquete de T4 para la VM de Azure (EN LA ESTACIÓN LOCAL; no toca ninguna nube). Lista EXPLÍCITA de rutas: nada de .env, claves, work/, estados de Terraform, .venv ni evidencias.
# Salida: work/t4/paquete/ops-center-AAAAMMDDThhmmssZ.tar.gz + .sha256 (0600). Uso: deploy/azure/empaquetar-t4.sh [--con-pruebas]   (con pruebas: añade las del testigo y del centro para ejecutarlas EN la VM)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"; PRUEBAS=0; [[ "${1:-}" == "--con-pruebas" ]] && PRUEBAS=1
OUT="${T4_PKG_DIR:-$ROOT/work/t4/paquete}"; umask 077; mkdir -p "$OUT"; TS="$(date -u +%Y%m%dT%H%M%SZ)"; PKG="$OUT/ops-center-$TS.tar.gz"
INCLUDE=(backend/app backend/requirements-production.lock ops_center deploy/ops-center deploy/witness deploy/azure scripts/multicloud/witness scripts/multicloud/failover)
[[ $PRUEBAS == 1 ]] && INCLUDE+=(scripts/multicloud/tests/test_witness_azure_profile.py scripts/multicloud/tests/test_witness_service.py scripts/multicloud/tests/test_witness_hardening.py)
for p in "${INCLUDE[@]}"; do [[ -e "$p" ]] || { echo "falta $p" >&2; exit 2; }; done
tar -czf "$PKG" --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' --exclude='.env.*' --exclude='*.pem' --exclude='*.key' --exclude='*.tfstate*' --exclude='*.tfvars' --exclude='.venv' --exclude='work' --exclude='.DS_Store' \
  $( [[ $PRUEBAS == 1 ]] || echo "--exclude=ops_center/tests" ) "${INCLUDE[@]}"
( cd "$OUT" && (shasum -a 256 "$(basename "$PKG")" 2>/dev/null || sha256sum "$(basename "$PKG")") > "$(basename "$PKG").sha256" )
echo "$PKG"; cut -d' ' -f1 "$PKG.sha256"
