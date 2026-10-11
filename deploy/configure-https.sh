#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 || $# -ne 1 ]]; then
  echo "Uso como root: $0 <subdominio.duckdns.org>" >&2
  exit 2
fi
DOMAIN="$1"
PROJECT_ROOT="/opt/nexoeventos"
NGINX_CONFIG="/etc/nginx/conf.d/nexoeventos.conf"
if [[ "$DOMAIN" =~ ^[a-z0-9-]+\.duckdns\.org$ ]]; then
  USES_DUCKDNS=YES
elif [[ "$DOMAIN" =~ ^nexoeventos-recovery-[0-9-]+\.sslip\.io$ ]]; then
  USES_DUCKDNS=NO
else
  echo "El dominio debe ser DuckDNS o el hostname sslip.io temporal de recuperación." >&2
  exit 1
fi
if [[ "$USES_DUCKDNS" == YES && ! -f /etc/nexoeventos/duckdns.env ]]; then
  echo "Falta la configuración DuckDNS protegida." >&2
  exit 1
fi

render() {
  local template="$1"
  local target="$2"
  DOMAIN="$DOMAIN" python3.11 - "$template" "$target" <<'PY'
import os
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).read_text()
pathlib.Path(sys.argv[2]).write_text(source.replace("${DOMAIN}", os.environ["DOMAIN"]))
PY
}

render "$PROJECT_ROOT/deploy/nginx/nexoeventos-http-bootstrap.conf.template" "$NGINX_CONFIG"
nginx -t
systemctl enable --now nginx
if [[ "$USES_DUCKDNS" == YES ]]; then
  systemctl enable --now nexoeventos-duckdns.timer
  systemctl start nexoeventos-duckdns.service
else
  resolved="$(getent ahostsv4 "$DOMAIN" | awk 'NR==1 {print $1}')"
  [[ -n "$resolved" ]] || { echo "El hostname temporal no resuelve; HTTPS cancelado." >&2; exit 1; }
  echo "Hostname temporal sslip.io resuelto; no se configuró actualización DNS."
fi

certbot_args=(
  certonly
  --webroot
  --webroot-path "$PROJECT_ROOT/frontend/dist"
  --domain "$DOMAIN"
)
if [[ "${NEXO_CERTBOT_NONINTERACTIVE:-NO}" == "YES" ]]; then
  certbot_args+=(--non-interactive --agree-tos --register-unsafely-without-email)
  echo "Solicitud ACME no interactiva autorizada, sin registrar correo."
else
  echo "Comprueba que $DOMAIN resuelva a esta EC2. Certbot solicitará correo y aceptación directamente."
fi
/usr/local/bin/certbot "${certbot_args[@]}"

render "$PROJECT_ROOT/deploy/nginx/nexoeventos.conf.template" "$NGINX_CONFIG"
nginx -t
systemctl reload nginx
systemctl enable --now nexoeventos-certbot-renew.timer
echo "HTTPS configurado. Verifica desde otro equipo antes de declararlo operativo."
