#!/usr/bin/env bash
# Lo ejecuta LA USUARIA en la VM (sudo). Pide los secretos por terminal sin eco; nada pasa por argumentos, historial ni chat.
set -euo pipefail
ENVF=/etc/nexoops/nexoops.env; PY=/opt/nexoeventos/venv/bin/python
run() { (cd /opt/nexoeventos && sudo -u nexoops env NEXOOPS_ENV=production NEXOOPS_ENV_FILE=$ENVF PYTHONPATH=/opt/nexoeventos "$PY" -m nexoops "$@"); }
setkey() { local k="$1" v; read -rsp "$2 (no se muestra; Enter vacío = omitir): " v; echo; [[ -z "$v" ]] && return 0
  sudo -u nexoops sed -i "/^$k=/d" "$ENVF"; printf '%s=%s\n' "$k" "$v" | sudo -u nexoops tee -a "$ENVF" >/dev/null; echo "  $k guardado"; }
echo "1/4 · SMTP de Gmail (contraseña de aplicación de 16 caracteres)"; run configure-smtp
echo "2/4 · Token de Grafana (cuenta de servicio con rol Viewer)"; setkey GRAFANA_TOKEN "GRAFANA_TOKEN"
echo "3/4 · Token de API de Zabbix (usuario de solo lectura)"; setkey ZABBIX_TOKEN "ZABBIX_TOKEN"
echo "4/4 · Administrador SUPER_ADMIN_TI"; run create-admin
sudo -u nexoops stat -c '%a %U %n' "$ENVF"; echo "Listo. Avisa a Claude para habilitar el servicio y verificar."
