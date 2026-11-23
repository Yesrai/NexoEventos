#!/usr/bin/env bash
# Instala el centro de operaciones EN la VM de Azure. Se ejecuta EN LA VM, con sudo, SOLO tras autorizacion especifica.
# Por defecto NO hace nada: imprime el plan. Para aplicar: --aplicar "INSTALAR CENTRO DE OPERACIONES EN LA VM"
# Uso:  instalar-en-vm.sh --paquete ops-center-AAAAMMDD.tar.gz --sha256 <hash esperado> [--aplicar "<frase>"]
set -euo pipefail
PKG=""; SHA=""; FRASE=""
while [[ $# -gt 0 ]]; do case "$1" in --paquete) PKG="$2"; shift 2;; --sha256) SHA="$2"; shift 2;; --aplicar) FRASE="$2"; shift 2;; *) echo "Opcion desconocida: $1" >&2; exit 2;; esac; done
[[ -f "$PKG" && ${#SHA} -eq 64 ]] || { echo "Falta --paquete o --sha256 (64 hex)" >&2; exit 2; }
if command -v sha256sum >/dev/null; then ACTUAL="$(sha256sum "$PKG" | cut -d' ' -f1)"; else ACTUAL="$(shasum -a 256 "$PKG" | cut -d' ' -f1)"; fi; [[ "$ACTUAL" == "$SHA" ]] || { echo "SHA-256 distinto: no se instala" >&2; exit 1; }
PLAN=(
  "crear usuario de sistema opscenter (sin shell, sin sudo) y /var/lib/ops-center (0700)"
  "extraer el paquete en /opt/nexoeventos (propietario root, solo lectura para opscenter)"
  "crear /opt/nexoeventos/venv e instalar backend/requirements-production.lock"
  "ejecutar: python -m ops_center init-identities --dir /var/lib/ops-center (los 3 tokens se muestran UNA vez en este terminal)"
  "instalar ops-center.service y habilitarlo (arranca en 127.0.0.1:8750)"
  "anadir nginx-ops.conf al server HTTPS existente, nginx -t y recargar"
  "verificar: curl -fsS https://127.0.0.1/ops/healthz (-k, certificado autofirmado) y python -m ops_center verify-audit"
)
echo "Plan (SHA-256 del paquete verificado: $ACTUAL):"; printf ' - %s\n' "${PLAN[@]}"
[[ "$FRASE" == "INSTALAR CENTRO DE OPERACIONES EN LA VM" ]] || { echo "Modo plan: no se cambio nada."; exit 0; }
[[ $EUID -eq 0 ]] || { echo "Requiere sudo" >&2; exit 1; }
id opscenter >/dev/null 2>&1 || useradd --system --home /var/lib/ops-center --shell /usr/sbin/nologin opscenter
install -d -m 0700 -o opscenter -g opscenter /var/lib/ops-center /etc/ops-center
install -d -m 0755 /opt/nexoeventos; tar -xzf "$PKG" -C /opt/nexoeventos --no-same-owner
python3 -m venv /opt/nexoeventos/venv; /opt/nexoeventos/venv/bin/pip install --no-cache-dir -r /opt/nexoeventos/backend/requirements-production.lock
[[ -f /var/lib/ops-center/identities.json ]] || sudo -u opscenter env PYTHONPATH=/opt/nexoeventos:/opt/nexoeventos/backend OPS_CENTER_STATE_DIR=/var/lib/ops-center /opt/nexoeventos/venv/bin/python -m ops_center init-identities --dir /var/lib/ops-center
install -m 0644 /opt/nexoeventos/deploy/ops-center/ops-center.service /etc/systemd/system/ops-center.service
systemctl daemon-reload; systemctl enable --now ops-center
echo "Servicio activo. Falta anadir /opt/nexoeventos/deploy/ops-center/nginx-ops.conf al server HTTPS (a mano, con nginx -t) y verificar."
echo "ROLLBACK: systemctl disable --now ops-center; rm /etc/systemd/system/ops-center.service; quitar el bloque /ops/ de nginx y recargar; (estado en /var/lib/ops-center se conserva para auditoria)."
