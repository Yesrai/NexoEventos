#!/usr/bin/env bash
# Instala el paquete de CA de RDS para validar el certificado del servidor (sslmode=verify-full).
# Verifica el SHA-256 del archivo descargado contra NEXO_RDS_CA_SHA256 (obligatorio: se fija la primera vez tras revisar el archivo).
set -euo pipefail
URL="${NEXO_RDS_CA_URL:-https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem}"
DEST="${NEXO_RDS_CA_BUNDLE:-/etc/nexoeventos/rds-ca-bundle.pem}"
EXPECTED="${NEXO_RDS_CA_SHA256:-}"
[[ "$EXPECTED" =~ ^[0-9a-f]{64}$ ]] || { echo "Defina NEXO_RDS_CA_SHA256 (64 hex) con el hash revisado del paquete." >&2; exit 1; }
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
curl --fail --silent --show-error --proto '=https' --tlsv1.2 "$URL" -o "$tmp"
actual="$(sha256sum "$tmp" | cut -d' ' -f1)"
[[ "$actual" == "$EXPECTED" ]] || { echo "SHA-256 distinto del esperado: no se instala." >&2; exit 1; }
grep -q 'BEGIN CERTIFICATE' "$tmp" || { echo "El archivo no contiene certificados." >&2; exit 1; }
install -m 0644 -o root -g root "$tmp" "$DEST"
echo "Instalado $DEST ($(grep -c 'BEGIN CERTIFICATE' "$DEST") certificados)."
