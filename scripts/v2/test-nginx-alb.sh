#!/usr/bin/env bash
# Prueba LOCAL (Docker, sin AWS) de la configuración de Nginx para el ALB: sintaxis, health check y manejo seguro de la IP real.
# Casos: (a) X-Forwarded-For de una red de confianza se respeta; (b) un valor falsificado a la izquierda se ignora; (c) desde una red NO
# confiable el encabezado se descarta; (d) /healthz llega a /ready; (e) cabeceras de seguridad. Uso: scripts/v2/test-nginx-alb.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
PY="${PYTHON:-python3}"
TMP="$(mktemp -d)"; trap 'docker rm -f nx-v2-up nx-v2-web >/dev/null 2>&1 || true; rm -rf "$TMP"' EXIT
render() { # la plantilla solo usa dos variables simples: se sustituyen sin depender de jinja2
"$PY" - "$1" <<'PY'
import sys
t = open("ansible/roles/nexoeventos/templates/nexoeventos-nginx-alb.conf.j2").read()
print(t.replace("{{ nexoeventos_alb_cidr }}", sys.argv[1]).replace("{{ nexoeventos_release_root }}", "/usr/share/nginx/html-x"))
PY
}
cat >"$TMP/fake_api.py" <<'PY'
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"path": self.path, "xff": self.headers.get("X-Forwarded-For"), "real_ip": self.headers.get("X-Real-IP"), "proto": self.headers.get("X-Forwarded-Proto")}).encode()
        self.send_response(200 if self.path in ("/ready", "/health", "/api/x") else 404); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", 8000), H).serve_forever()
PY
docker rm -f nx-v2-up nx-v2-web >/dev/null 2>&1 || true
docker run -d --rm --name nx-v2-up -v /dev/null:/dev/null python:3.12-slim python -u -c "$(cat "$TMP/fake_api.py")" >/dev/null
run_nginx() { # $1 = CIDR de confianza
  docker rm -f nx-v2-web >/dev/null 2>&1 || true
  render "$1" >"$TMP/alb.conf"
  docker run -d --rm --name nx-v2-web --network container:nx-v2-up nginx:stable sh -c 'cat > /etc/nginx/conf.d/default.conf <<"EOF2"
'"$(cat "$TMP/alb.conf")"'
EOF2
nginx -t && exec nginx -g "daemon off;"' >/dev/null
  for _ in $(seq 30); do docker exec nx-v2-up python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1/healthz',timeout=1)" >/dev/null 2>&1 && return; sleep 0.5; done
  echo "Nginx no arrancó:"; docker logs nx-v2-web 2>&1 | tail -5; exit 1
}
get() { docker exec -i nx-v2-up python - "$@" <<'PY'
import sys, json, urllib.request
path, xff = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
req = urllib.request.Request("http://127.0.0.1" + path, headers={"Host": "10.20.1.15", **({"X-Forwarded-For": xff} if xff else {})})
r = urllib.request.urlopen(req, timeout=5)
print(json.dumps({"status": r.status, "csp": "default-src" in (r.headers.get("Content-Security-Policy") or ""), "hsts": bool(r.headers.get("Strict-Transport-Security")), "body": json.loads(r.read() or b"{}") if path != "/" else {}}))
PY
}
fail=0; ok() { echo "OK    $1"; }; bad() { echo "FALLÓ $1 — $2"; fail=1; }
run_nginx "127.0.0.1/32"
r="$(get /healthz)"; [[ "$(jq -r .body.path <<<"$r")" == "/ready" && "$(jq -r .status <<<"$r")" == 200 ]] && ok "/healthz llega a /ready (200) con el host de la IP de la instancia" || bad "/healthz" "$r"
r="$(get /livez)"; [[ "$(jq -r .body.path <<<"$r")" == "/health" && "$(jq -r .status <<<"$r")" == 200 ]] && ok "/livez llega a /health (liveness sin base de datos)" || bad "/livez" "$r"
r="$(get /api/x 198.51.100.9)"; [[ "$(jq -r .body.xff <<<"$r")" == 198.51.100.9 && "$(jq -r .body.real_ip <<<"$r")" == 198.51.100.9 ]] && ok "(a) red de confianza: se usa la IP real del cliente" || bad "(a)" "$r"
r="$(get /api/x '10.9.9.9, 198.51.100.9')"; [[ "$(jq -r .body.xff <<<"$r")" == 198.51.100.9 ]] && ok "(b) valor falsificado a la izquierda ignorado (gana la dirección que añadió el ALB)" || bad "(b)" "$r"
[[ "$(jq -r .body.proto <<<"$r")" == https && "$(jq -r .csp <<<"$r")" == true && "$(jq -r .hsts <<<"$r")" == true ]] && ok "(e) X-Forwarded-Proto https y cabeceras de seguridad presentes" || bad "(e)" "$r"
run_nginx "192.0.2.0/24"
r="$(get /api/x 198.51.100.9)"; [[ "$(jq -r .body.xff <<<"$r")" == 127.0.0.1 ]] && ok "(c) red NO confiable: X-Forwarded-For descartado (se ve 127.0.0.1)" || bad "(c)" "$r"
((fail)) && { echo "Hay fallos."; exit 1; } || echo "Nginx para ALB: todo OK"
