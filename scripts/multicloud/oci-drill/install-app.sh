#!/usr/bin/env bash
# En la VM de contingencia (root, SIN Internet): instala y arranca la aplicación desde el paquete copiado por scp (ruedas Python, backend, dist, plantilla de Nginx).
#   install-app.sh stage1 <dir-paquete>   paquetes del SO (espejo de Oracle), usuario, venv offline, frontend, Nginx
#   install-app.sh stage2 <dir-paquete>   (tras restaurar la BD y las claves) rol de BD, entorno en tmpfs, certificado TLS efímero, systemd, Nginx, firewall
set -euo pipefail
STAGE="${1:?stage1|stage2}"; B="${2:?directorio del paquete}"; APP=/opt/nexoeventos; PGB=/usr/pgsql-18/bin
case "$STAGE" in
stage1)
  dnf -y install python3.12 nginx
  id nexoeventos >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /sbin/nologin nexoeventos
  install -d -m 0755 "$APP/backend" "$APP/frontend" /var/log/nexoeventos; chown nexoeventos:nexoeventos /var/log/nexoeventos
  tar -xzf "$B/backend.tgz" -C "$APP/backend"; rm -rf "$APP/frontend/dist"; tar -xzf "$B/dist.tgz" -C "$APP/frontend"
  [[ -d "$B/wheels" ]] || tar -xzf "$B/wheels.tgz" -C "$B"        # ruedas empaquetadas en un solo archivo por app-recovery.sh (el scp de ~33 archivos tardaba 38 s)
  python3.12 -m venv "$APP/backend/.venv"
  "$APP/backend/.venv/bin/pip" install --no-index --find-links "$B/wheels" -r "$APP/backend/requirements-production.lock"
  chmod -R u=rwX,go=rX "$APP/frontend/dist"      # el paquete se construye con umask 077: Nginx (otro usuario) no podía leerlo y devolvía 403
  chcon -R -t httpd_sys_content_t "$APP/frontend/dist" 2>/dev/null || true
  setsebool httpd_can_network_connect 1 || true
  echo "OK    stage1: $("$APP/backend/.venv/bin/python" -V), $(nginx -v 2>&1)"
  ;;
stage2)
  [[ -s /run/nexoeventos/secrets.env ]] || { echo "FALLÓ: faltan las claves de aplicación en /run/nexoeventos" >&2; exit 3; }
  APPPW="$(openssl rand -hex 24)"          # contraseña local de la BD: solo en esta VM (tmpfs), nunca se imprime
  runuser -u postgres -- "$PGB/psql" -d postgres -v ON_ERROR_STOP=1 -qAt >/dev/null <<SQL
DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='nexoeventos_app') THEN CREATE ROLE nexoeventos_app LOGIN; END IF; END \$\$;
ALTER ROLE nexoeventos_app PASSWORD '$APPPW';
GRANT CONNECT ON DATABASE nexoeventos TO nexoeventos_app;
SQL
  # Permisos de la base restaurada (db-permissions.sh): GRANT primero, solo lectura después, comprobación en sesiones nuevas. NO invertir el orden: con el ajuste ya activo, el propio GRANT falla.
  if [[ "${RECOVERY_READONLY:-0}" == 1 ]]; then bash "$B/db-permissions.sh" readonly; else bash "$B/db-permissions.sh" readwrite; fi
  PGHBA="$(runuser -u postgres -- "$PGB/psql" -d postgres -Atc 'show hba_file')"
  grep -q nexoeventos_app "$PGHBA" || sed -i '0,/^local/s//local   nexoeventos   nexoeventos_app   scram-sha-256\nlocal/' "$PGHBA"
  runuser -u postgres -- "$PGB/psql" -d postgres -qAtc 'select pg_reload_conf()' >/dev/null
  umask 077
  { cat <<ENV
APP_ENV=production
DATABASE_URL=postgresql+psycopg://nexoeventos_app:$APPPW@/nexoeventos?host=/var/run/postgresql
FRONTEND_ORIGINS=https://localhost:8443
SESSION_COOKIE_SECURE=true
SESSION_HOURS=8
LOGIN_MAX_FAILURES=5
LOGIN_WINDOW_MINUTES=15
LOGIN_BLOCK_MINUTES=15
ARGON2_MAX_CONCURRENT=2
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
ENV
    cat /run/nexoeventos/secrets.env; } > /run/nexoeventos/backend.env
  chown root:nexoeventos /run/nexoeventos/backend.env; chmod 0640 /run/nexoeventos/backend.env; chmod 0711 /run/nexoeventos
  install -m 0644 "$B/nexoeventos-api.service" /etc/systemd/system/nexoeventos-api.service
  install -d /etc/systemd/system/nexoeventos-api.service.d
  printf '[Service]\nEnvironmentFile=\nEnvironmentFile=/run/nexoeventos/backend.env\n' > /etc/systemd/system/nexoeventos-api.service.d/oci-demo.conf
  # Certificado autofirmado y clave privada EFÍMEROS: se crean aquí y desaparecen con la VM.
  install -d -m 0700 /etc/nginx/demo-tls
  openssl req -x509 -newkey rsa:3072 -nodes -days 3 -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
    -keyout /etc/nginx/demo-tls/key.pem -out /etc/nginx/demo-tls/cert.pem 2>/dev/null
  chmod 600 /etc/nginx/demo-tls/key.pem; restorecon -R /etc/nginx/demo-tls 2>/dev/null || true
  python3 - "$B/nexoeventos.conf.template" > /etc/nginx/conf.d/nexoeventos.conf <<'PY'
import os, re, sys
t = open(sys.argv[1]).read()
blocks = re.split(r'(?m)^server \{', t)          # [prefijo, bloque HTTP:80, bloque HTTPS:443]
b = '\n'.join(['server {' + blocks[-1]]).replace('${DOMAIN}', 'localhost')
b = re.sub(r'ssl_certificate\s+[^;]+;', 'ssl_certificate /etc/nginx/demo-tls/cert.pem;', b)
b = re.sub(r'ssl_certificate_key\s+[^;]+;', 'ssl_certificate_key /etc/nginx/demo-tls/key.pem;', b)
b = re.sub(r'listen \[::\]:443 ssl;\n?', '', b)
b = re.sub(r'(?m)^\s*http2 on;\n', '', b)                          # 'http2 on' exige Nginx >= 1.25.1; Oracle Linux 9 trae 1.20
b = b.replace('listen 443 ssl;', 'listen 443 ssl http2;')
if os.environ.get("RECOVERY_READONLY") == "1":      # primera capa: ningún verbo que modifique datos llega a la API desde fuera (GET/HEAD/OPTIONS solamente)
    b = b.replace("    location /api/ {\n", "    location /api/ {\n        limit_except GET HEAD OPTIONS { deny all; }\n", 1)
print(b)
PY
  rm -f /etc/nginx/conf.d/default.conf
  # El nginx.conf de Oracle Linux trae un servidor por defecto en el puerto 80: se retira (solo HTTPS, y solo desde el endpoint del Bastion).
  python3 - <<'PY'
import re
p = "/etc/nginx/nginx.conf"; t = open(p).read()
m = re.search(r'(?m)^    server \{\n(?:.*\n)*?^    \}\n', t)
if m and "listen       80;" in m.group(0):
    open(p + ".orig", "w").write(t); open(p, "w").write(t[:m.start()] + t[m.end():])
PY
  nginx -t
  systemctl daemon-reload; systemctl enable --now nexoeventos-api nginx
  firewall-cmd --add-service=https >/dev/null    # solo en tiempo de ejecución; la entrada llega solo desde el endpoint del Bastion (NSG)
  for _ in $(seq 30); do curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break; sleep 2; done
  echo "OK    stage2: /health local = $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health); HTTPS local: /livez = $(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/livez), /ready = $(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/ready), /healthz = $(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/healthz)"
  [[ "$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/livez)$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/ready)" == 200200 ]] || { echo "FALLÓ: /livez o /ready no responden 200 en la VM" >&2; exit 6; }
  ;;
*) echo "etapa desconocida" >&2; exit 2;;
esac
