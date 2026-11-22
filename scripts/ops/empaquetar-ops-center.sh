#!/usr/bin/env bash
# Construye LOCALMENTE el paquete de despliegue del centro de operaciones (no sube nada, no toca Azure). Salida: work/ops-center-release/ops-center-<UTC>.tar.gz + .sha256
# Contenido minimo: ops_center/ (con pruebas), backend/app + lock, scripts/multicloud/failover (config y adaptadores que importa), deploy/ops-center. Excluye work/, .env, claves, __pycache__.
set -euo pipefail; export PATH="/opt/homebrew/bin:/usr/bin:/bin"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
OUT="work/ops-center-release"; mkdir -p "$OUT"; chmod 700 "$OUT"; STAMP="$(date -u +%Y%m%dT%H%M%SZ)"; PKG="$OUT/ops-center-$STAMP.tar.gz"
LIST="$(mktemp)"; trap 'rm -f "$LIST"' EXIT
{ find ops_center deploy/ops-center backend/app scripts/multicloud/failover -type f ! -path '*/__pycache__/*' ! -name '*.pyc' ! -name '.env' ! -name '*.pem' ! -name '*.key'
  echo backend/requirements-production.lock; } | sort > "$LIST"
if grep -E 'work/|\.env$|\.pem$|id_rsa|\.tfstate' "$LIST" >/dev/null; then echo "ABORTA: la lista incluye archivos sensibles" >&2; exit 1; fi
COPYFILE_DISABLE=1 tar -czf "$PKG" -T "$LIST"
# escaneo de secretos del contenido (patrones de claves privadas y de AWS)
SC="$(mktemp -d)"; tar -xzf "$PKG" -C "$SC"
if grep -rIlE 'BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}' "$SC" --exclude-dir=tests --exclude='test_*.py' >/dev/null 2>&1; then echo "ABORTA: posible secreto en el paquete" >&2; rm -rf "$SC" "$PKG"; exit 1; fi
rm -rf "$SC"; ( cd "$OUT" && shasum -a 256 "$(basename "$PKG")" > "$(basename "$PKG").sha256" ); chmod 600 "$PKG" "$PKG.sha256"
echo "$PKG"; cat "$PKG.sha256"; echo "archivos: $(wc -l < "$LIST") · bytes: $(stat -f %z "$PKG")"
