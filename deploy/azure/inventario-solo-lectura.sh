#!/usr/bin/env bash
# Inventario de SOLO LECTURA de la VM de Azure (se ejecuta EN la VM, tras encenderla con autorización): qué hay instalado y configurado, para decidir qué NO se debe tocar. No modifica nada; no lee secretos
# (solo huellas SHA-256 y metadatos de archivos de configuración; nunca su contenido). Salida a stdout. Uso: sudo bash inventario-solo-lectura.sh > inventario-azure.txt
set -uo pipefail
echo "utc=$(date -u +%FT%TZ) host=$(hostname) kernel=$(uname -r) uptime=$(uptime -p)"
echo "== memoria/disco"; free -m | sed -n 1,3p; df -h / /var 2>/dev/null | sed -n 1,3p
echo "== versiones"; for p in grafana zabbix-server-pgsql zabbix-frontend-php zabbix-agent2 nginx postgresql python3; do printf '%s=%s\n' "$p" "$(dpkg-query -W -f='${Version}' "$p" 2>/dev/null || echo no-instalado)"; done
echo "== servicios"; for u in grafana-server zabbix-server zabbix-agent2 nginx postgresql ops-center witness ssh; do printf '%s=%s/%s\n' "$u" "$(systemctl is-enabled "$u" 2>&1 | head -1)" "$(systemctl is-active "$u" 2>&1 | head -1)"; done
echo "== puertos en escucha"; ss -ltnH | awk '{print $4}' | sort -u
echo "== nginx (solo rutas, sin secretos)"; nginx -T 2>/dev/null | grep -E "^\s*(listen|server_name|location)\b" | sed 's/^ *//' | sort -u
echo "== huellas SHA-256 de configuraciones (no contenido)"; for f in /etc/grafana/grafana.ini /etc/zabbix/zabbix_server.conf /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf /etc/ufw/user.rules; do [ -f "$f" ] && printf '%s  %s %s\n' "$(sha256sum "$f" | cut -c1-16)" "$(stat -c '%a %U' "$f")" "$f"; done
echo "== usuarios del SO de interés"; for u in opscenter nexowitness zabbix grafana; do id "$u" >/dev/null 2>&1 && echo "$u=existe" || echo "$u=no-existe"; done
echo "== directorios de estado"; for d in /opt/nexoeventos /var/lib/ops-center /var/lib/witness /etc/ops-center /etc/witness; do [ -e "$d" ] && echo "$d=existe $(stat -c '%a %U' "$d")" || echo "$d=no-existe"; done
echo "== apagado automático / cloud-init"; systemctl list-timers --no-pager 2>/dev/null | grep -E "dnf|apt|unattended" | head -5 | cut -c1-120
echo "FIN (solo lectura)"
