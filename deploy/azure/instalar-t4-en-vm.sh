#!/usr/bin/env bash
# T4 — instalación ADITIVA en la VM de Azure (se ejecuta EN la VM, con sudo, SOLO con autorización específica). Por defecto imprime el plan y NO cambia nada.
# NO reinstala ni reconfigura Grafana, Zabbix, PostgreSQL ni UFW; solo AÑADE: usuario opscenter/nexowitness, /opt/nexoeventos, 3 unidades systemd (centro, testigo, recolector+timer) y un include de Nginx.
# Antes de tocar Nginx hace copia con SHA-256 en /var/backups/nexo-t4/; si `nginx -t` falla restaura la copia y sale con error.
# Uso: instalar-t4-en-vm.sh --paquete ops-center-AAAAMMDD.tar.gz --sha256 <64 hex> [--aplicar "INSTALAR T4 EN LA VM DE AZURE"]
set -euo pipefail
PKG=""; SHA=""; FRASE=""; ROOT="${NEXO_ROOT:-}"          # NEXO_ROOT solo para pruebas en un directorio simulado
while [[ $# -gt 0 ]]; do case "$1" in --paquete) PKG="$2"; shift 2;; --sha256) SHA="$2"; shift 2;; --aplicar) FRASE="$2"; shift 2;; *) echo "Opción desconocida: $1" >&2; exit 2;; esac; done
[[ -f "$PKG" && ${#SHA} -eq 64 ]] || { echo "Falta --paquete o --sha256 (64 hex)" >&2; exit 2; }
ACTUAL="$( (sha256sum "$PKG" 2>/dev/null || shasum -a 256 "$PKG") | cut -d' ' -f1)"; [[ "$ACTUAL" == "$SHA" ]] || { echo "SHA-256 distinto: no se instala" >&2; exit 2; }
PLAN=(
  "copia de seguridad con SHA-256 de /etc/nginx (solo lectura del resto) en /var/backups/nexo-t4/"
  "crear usuarios de sistema opscenter y nexowitness (sin shell, sin sudo) y /var/lib/ops-center, /var/lib/witness, /etc/ops-center, /etc/witness (0700)"
  "extraer el paquete en /opt/nexoeventos y crear /opt/nexoeventos/venv (requirements-production.lock); si falta, instalar SOLO el paquete python3-venv"
  "generar identidades del centro si no existen (NO se sobrescriben); los 3 tokens se guardan en /root/.nexo-t4-tokens-centro (0600) para que SOLO la propietaria los lea y destruya el archivo"
  "instalar el script de alertas nexo-alert-azure.py en el directorio de alertas de Zabbix (0750, grupo zabbix)"
  "instalar ops-center.service, witness.service y ops-collector.service/.timer (el testigo y el recolector solo arrancan si existen sus archivos de configuración)"
  "crear /etc/nginx/snippets/nexo-ops.conf (rutas /ops/ y /witness/) e incluirlo UNA vez en el server HTTPS existente; nginx -t; si falla, restaurar la copia"
  "verificar: /ops/healthz, collect --once y verify-audit; Grafana, Zabbix, PostgreSQL y UFW quedan intactos (se comparan sus huellas antes/después)"
)
echo "Plan (SHA-256 del paquete verificado: $ACTUAL):"; printf ' - %s\n' "${PLAN[@]}"
[[ "$FRASE" == "INSTALAR T4 EN LA VM DE AZURE" ]] || { echo "Modo plan: no se cambió nada."; exit 0; }
[[ $EUID -eq 0 || -n "$ROOT" ]] || { echo "Requiere sudo" >&2; exit 1; }
B="$ROOT/var/backups/nexo-t4/$(date -u +%Y%m%dT%H%M%SZ)"; install -d -m 0700 "$B"
tar -czf "$B/nginx.tgz" -C "$ROOT/" etc/nginx; (cd "$B" && sha256sum nginx.tgz > nginx.tgz.sha256)
HUELLAS() { for f in "$ROOT"/etc/grafana/grafana.ini "$ROOT"/etc/zabbix/zabbix_server.conf "$ROOT"/etc/ufw/user.rules; do [[ -f "$f" ]] && sha256sum "$f"; done; true; }
HUELLAS > "$B/huellas-antes.txt"
id opscenter >/dev/null 2>&1 || { [[ -n "$ROOT" ]] || useradd --system --home /var/lib/ops-center --shell /usr/sbin/nologin opscenter; }
id nexowitness >/dev/null 2>&1 || { [[ -n "$ROOT" ]] || useradd --system --home /var/lib/witness --shell /usr/sbin/nologin nexowitness; }
for d in var/lib/ops-center etc/ops-center var/lib/witness etc/witness; do install -d -m 0700 "$ROOT/$d"; done
install -d -m 0755 "$ROOT/opt/nexoeventos"; tar -xzf "$PKG" -C "$ROOT/opt/nexoeventos" --no-same-owner
if [[ -z "$ROOT" ]]; then
  # Ubuntu 24.04 no trae ensurepip: sin python3-venv `python3 -m venv` deja un entorno SIN pip. Único paquete del SO que se añade (y solo si falta); no actualiza nada más.
  python3 -c "import ensurepip" 2>/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-venv
  [[ -x /opt/nexoeventos/venv/bin/pip ]] || { rm -rf /opt/nexoeventos/venv; python3 -m venv /opt/nexoeventos/venv; }     # solo el venv propio, nunca otra ruta
  /opt/nexoeventos/venv/bin/pip install --no-cache-dir -r /opt/nexoeventos/backend/requirements-production.lock
  chown -R opscenter:opscenter /var/lib/ops-center /etc/ops-center; chown -R nexowitness:nexowitness /var/lib/witness /etc/witness
  [[ -f /var/lib/ops-center/identities.json ]] || sudo -u opscenter env PYTHONPATH=/opt/nexoeventos:/opt/nexoeventos/backend OPS_CENTER_STATE_DIR=/var/lib/ops-center /opt/nexoeventos/venv/bin/python -m ops_center init-identities --dir /var/lib/ops-center > /root/.nexo-t4-tokens-centro 2>&1; chmod 600 /root/.nexo-t4-tokens-centro   # los tokens NO salen por la sesión de instalación: solo la propietaria los lee (cat + shred) en su terminal
fi
install -d "$ROOT/etc/systemd/system"
for u in ops-center.service ops-collector.service ops-collector.timer; do install -m 0644 "$ROOT/opt/nexoeventos/deploy/ops-center/$u" "$ROOT/etc/systemd/system/$u"; done
install -m 0644 "$ROOT/opt/nexoeventos/deploy/witness/witness.service" "$ROOT/etc/systemd/system/witness.service"
AS="$ROOT/usr/lib/zabbix/alertscripts"; install -d "$AS"; install -m 0750 "$ROOT/opt/nexoeventos/deploy/azure/nexo-alert-azure.py" "$AS/nexo-alert-azure.py"
[[ -n "$ROOT" ]] || chgrp zabbix "$AS/nexo-alert-azure.py"
SN="$ROOT/etc/nginx/snippets/nexo-ops.conf"; install -d "$(dirname "$SN")"
cat "$ROOT/opt/nexoeventos/deploy/ops-center/nginx-ops.conf" "$ROOT/opt/nexoeventos/deploy/witness/nginx-witness.conf" > "$SN"
SITE="$(grep -l "listen 443" "$ROOT"/etc/nginx/sites-enabled/* "$ROOT"/etc/nginx/conf.d/*.conf 2>/dev/null | head -1 || true)"
if [[ -n "$SITE" ]] && ! grep -q "snippets/nexo-ops.conf" "$SITE"; then
  cp -p "$SITE" "$B/$(basename "$SITE").orig"; python3 - "$SITE" <<'PY'
import re, sys
p = sys.argv[1]; t = open(p).read()
# cierre del server{} que escucha en 443 (cuenta de llaves): el archivo puede tener otros bloques después (p. ej. un `map`)
m = None
for m in re.finditer(r"(?m)^server\s*\{", t):
    depth, i = 0, m.end() - 1
    while i < len(t):
        depth += (t[i] == "{") - (t[i] == "}")
        if depth == 0: break
        i += 1
    if "listen 443" in t[m.start():i]: break
else:
    raise SystemExit("no se encontró el server HTTPS")
open(p, "w").write(t[:i] + "    include snippets/nexo-ops.conf;\n" + t[i:])
PY
fi
if [[ -z "$ROOT" ]]; then
  if ! nginx -t; then echo "nginx -t FALLÓ: se restaura la copia" >&2; [[ -n "$SITE" && -f "$B/$(basename "$SITE").orig" ]] && cp -p "$B/$(basename "$SITE").orig" "$SITE"; rm -f "$SN"; nginx -t || true; exit 3; fi
  systemctl daemon-reload; systemctl enable --now ops-center
  [[ -f /etc/ops-center/targets.json ]] && systemctl enable --now ops-collector.timer || echo "AVISO: falta /etc/ops-center/targets.json; el recolector no arranca (ver targets.example.json)"
  [[ -s /etc/witness/reporters.json && -s /etc/witness/invokers.json ]] && systemctl enable --now witness || echo "AVISO: faltan /etc/witness/reporters.json e invokers.json; el testigo no arranca"
  systemctl reload nginx
fi
HUELLAS > "$B/huellas-despues.txt"; cmp -s "$B/huellas-antes.txt" "$B/huellas-despues.txt" && echo "OK    Grafana, Zabbix y UFW intactos (huellas iguales)" || { echo "ALERTA: cambió una configuración protegida" >&2; exit 4; }
echo "ROLLBACK: systemctl disable --now ops-collector.timer witness ops-center; rm /etc/systemd/system/{ops-center,witness,ops-collector}.service /etc/systemd/system/ops-collector.timer /etc/nginx/snippets/nexo-ops.conf; restaurar $B/*.orig y nginx -t; recargar. (/var/lib/* se conserva como auditoría)"
