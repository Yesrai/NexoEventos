#!/usr/bin/env bash
# Instala NexoOps EN la VM de Azure. Se ejecuta EN LA VM con sudo y SOLO tras autorización específica.
# Por defecto solo imprime el plan. Para aplicar: --aplicar "INSTALAR NEXOOPS EN LA VM"
# Uso: instalar-en-vm.sh --paquete nexoops-AAAAMMDD.tar.gz --sha256 <hash> [--aplicar "<frase>"]
set -euo pipefail
PKG=""; SHA=""; FRASE=""
while [[ $# -gt 0 ]]; do case "$1" in --paquete) PKG="$2"; shift 2;; --sha256) SHA="$2"; shift 2;; --aplicar) FRASE="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
[[ -f "$PKG" && ${#SHA} -eq 64 ]] || { echo "Falta --paquete o --sha256 (64 hex)" >&2; exit 2; }
ACTUAL="$(sha256sum "$PKG" 2>/dev/null | cut -d' ' -f1 || shasum -a 256 "$PKG" | cut -d' ' -f1)"; [[ "$ACTUAL" == "$SHA" ]] || { echo "SHA-256 distinto: no se instala" >&2; exit 1; }
TS="$(date -u +%Y%m%dT%H%M%SZ)"; BK="/var/backups/nexoops-$TS"
PLAN=(
  "respaldar configuración actual: /etc/nginx (tar) y unidades systemd en $BK"
  "crear usuario de sistema nexoops (sin shell ni sudo), /var/lib/nexoops (0700) y /etc/nexoops (0750 root:nexoops)"
  "extraer el paquete en /opt/nexoeventos/nexoops (root, solo lectura para nexoops) y reutilizar /opt/nexoeventos/venv"
  "el operador ejecuta EN LA VM: sudo -u nexoops env NEXOOPS_ENV=production NEXOOPS_ENV_FILE=/etc/nexoops/nexoops.env python -m nexoops configure-smtp (archivo 0600 de nexoops): OTP secret, SMTP Gmail, GRAFANA_TOKEN Viewer, ZABBIX_TOKEN solo lectura (nunca por chat)"
  "el operador ejecuta en la VM: python -m nexoops create-admin (contraseña por getpass)"
  "instalar el espejo de solo lectura (nexoops-feed.service/.timer, /var/lib/nexoops-feed 0750 opscenter:nexoops) y nexoops.service, y habilitarlo (127.0.0.1:8770)"
  "insertar nginx-nexoops.conf en el server HTTPS existente, nginx -t y recargar (si nginx -t falla: no se recarga)"
  "verificar: curl -fsS https://<host>/nexoops/healthz, login OTP real, check-integrations"
)
echo "Plan (SHA-256 verificado: $ACTUAL):"; printf ' - %s\n' "${PLAN[@]}"
echo "ROLLBACK: systemctl disable --now nexoops; rm /etc/systemd/system/nexoops.service; restaurar /etc/nginx desde $BK; nginx -t && systemctl reload nginx; /var/lib/nexoops se conserva (auditoría)."
[[ "$FRASE" == "INSTALAR NEXOOPS EN LA VM" ]] || { echo "Modo plan: no se cambió nada."; exit 0; }
[[ $EUID -eq 0 ]] || { echo "Requiere sudo" >&2; exit 1; }
install -d -m 0700 "$BK"; tar -czf "$BK/etc-nginx.tgz" -C / etc/nginx; cp -a /etc/systemd/system/*.service "$BK/" 2>/dev/null || true
id nexoops >/dev/null 2>&1 || useradd --system --home /var/lib/nexoops --shell /usr/sbin/nologin nexoops
install -d -m 0700 -o nexoops -g nexoops /var/lib/nexoops; install -d -m 0700 -o nexoops -g nexoops /etc/nexoops
tar -xzf "$PKG" -C /opt/nexoeventos --no-same-owner
[[ -x /opt/nexoeventos/venv/bin/python ]] || python3 -m venv /opt/nexoeventos/venv
/opt/nexoeventos/venv/bin/pip install --no-cache-dir -r /opt/nexoeventos/nexoops/requirements.txt
install -m 0644 /opt/nexoeventos/deploy/nexoops/nexoops.service /etc/systemd/system/nexoops.service
chmod 0755 /opt/nexoeventos/deploy/nexoops/nexoops-feed.sh
install -d -m 0750 -o opscenter -g nexoops /var/lib/nexoops-feed
install -m 0644 /opt/nexoeventos/deploy/nexoops/nexoops-feed.service /etc/systemd/system/nexoops-feed.service
install -m 0644 /opt/nexoeventos/deploy/nexoops/nexoops-feed.timer /etc/systemd/system/nexoops-feed.timer
systemctl daemon-reload
[[ -f /etc/nexoops/nexoops.env ]] || { echo "Falta /etc/nexoops/nexoops.env: créalo con configure-smtp (0600, propietario nexoops) y vuelve a ejecutar. No se habilita el servicio."; exit 3; }
systemctl enable --now nexoops-feed.timer
systemctl enable --now nexoops
echo "Servicio activo en 127.0.0.1:8770. Falta insertar deploy/nexoops/nginx-nexoops.conf en el server HTTPS (nginx -t antes de recargar)."
