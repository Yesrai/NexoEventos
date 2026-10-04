#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Ejecuta este instalador como root en la EC2 autorizada." >&2
  exit 1
fi

source /etc/os-release
if [[ "${ID:-}" != "amzn" || "${VERSION_ID:-}" != "2023" ]]; then
  echo "Sistema no compatible: se requiere Amazon Linux 2023." >&2
  exit 1
fi

PROJECT_ROOT="/opt/nexoeventos"
NODE_VERSION="24.21.0"
NODE_ARCHIVE="node-v${NODE_VERSION}-linux-x64.tar.xz"
NODE_SHA256="fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6"

if [[ ! -f "$PROJECT_ROOT/frontend/package-lock.json" || ! -f "$PROJECT_ROOT/backend/requirements-production.lock" ]]; then
  echo "Copia primero una revisión identificada del repositorio a $PROJECT_ROOT." >&2
  exit 1
fi

# AL2023 instala curl-minimal de forma predeterminada; pedir `curl` fuerza un
# reemplazo conflictivo. Ambos proporcionan el binario que necesita el script.
dnf install -y nginx python3.11 python3.11-pip tar xz jq postgresql18 awscli-2

if ! id nexoeventos >/dev/null 2>&1; then
  useradd --system --home-dir /opt/nexoeventos --shell /sbin/nologin nexoeventos
fi

tmp_dir="$(mktemp -d)"
cleanup() { rm -rf -- "$tmp_dir"; }
trap cleanup EXIT
curl --fail --silent --show-error --location \
  "https://nodejs.org/dist/v${NODE_VERSION}/${NODE_ARCHIVE}" --output "$tmp_dir/$NODE_ARCHIVE"
echo "$NODE_SHA256  $tmp_dir/$NODE_ARCHIVE" | sha256sum --check --status
tar -xJf "$tmp_dir/$NODE_ARCHIVE" -C /opt
ln -sfn "/opt/node-v${NODE_VERSION}-linux-x64/bin/node" /usr/local/bin/node
ln -sfn "/opt/node-v${NODE_VERSION}-linux-x64/bin/npm" /usr/local/bin/npm
ln -sfn "/opt/node-v${NODE_VERSION}-linux-x64/bin/npx" /usr/local/bin/npx

cd "$PROJECT_ROOT/frontend"
/usr/local/bin/npm ci
VITE_API_URL= /usr/local/bin/npm run build

python3.11 -m venv "$PROJECT_ROOT/backend/.venv"
"$PROJECT_ROOT/backend/.venv/bin/python" -m pip install --disable-pip-version-check \
  --requirement "$PROJECT_ROOT/backend/requirements-production.lock"
python3.11 -m venv /opt/certbot
/opt/certbot/bin/python -m pip install --disable-pip-version-check \
  --requirement "$PROJECT_ROOT/deploy/requirements-certbot.lock"
ln -sfn /opt/certbot/bin/certbot /usr/local/bin/certbot

install -d -o root -g root -m 0700 /etc/nexoeventos
install -d -o root -g nexoeventos -m 0750 /var/log/nexoeventos
install -o root -g root -m 0644 \
  "$PROJECT_ROOT/deploy/systemd/nexoeventos-api.service" \
  /etc/systemd/system/nexoeventos-api.service
install -o root -g root -m 0644 "$PROJECT_ROOT/deploy/systemd/nexoeventos-duckdns.service" \
  /etc/systemd/system/nexoeventos-duckdns.service
install -o root -g root -m 0644 "$PROJECT_ROOT/deploy/systemd/nexoeventos-duckdns.timer" \
  /etc/systemd/system/nexoeventos-duckdns.timer
install -o root -g root -m 0644 "$PROJECT_ROOT/deploy/systemd/nexoeventos-certbot-renew.service" \
  /etc/systemd/system/nexoeventos-certbot-renew.service
install -o root -g root -m 0644 "$PROJECT_ROOT/deploy/systemd/nexoeventos-certbot-renew.timer" \
  /etc/systemd/system/nexoeventos-certbot-renew.timer
install -o root -g root -m 0755 "$PROJECT_ROOT/deploy/duckdns/update.sh" \
  /usr/local/sbin/nexoeventos-duckdns-update
chown -R root:nexoeventos "$PROJECT_ROOT/backend" "$PROJECT_ROOT/frontend/dist"
chmod -R go-w "$PROJECT_ROOT/backend" "$PROJECT_ROOT/frontend/dist"
systemctl daemon-reload

echo "Base AL2023 instalada. Servicio no iniciado: carga secretos y configura DNS/TLS primero."
