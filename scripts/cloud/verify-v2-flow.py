#!/usr/bin/env python3
"""Prueba funcional breve de AWS V2 contra el ALB: ejecuta verify-controlled-flow.py con el dominio autorizado resuelto a la IP del ALB
(mismo nombre y certificado, sin tocar DNS), una conexión nueva por solicitud (para repartir entre instancias) y, al terminar, resume el reparto
de solicitudes entre las instancias a partir del log de Nginx de cada una. Los datos ficticios se preparan y limpian con la identidad migradora de la
EC2 de V1 (encendida temporalmente); no se copian credenciales privilegiadas a V2.
Requiere NEXO_ALLOW_CLOUD_CHANGES=YES. Uso: python3 scripts/cloud/verify-v2-flow.py --out docs/evidencias/validacion-v2-AAAAMMDD
"""
import argparse
import importlib.util
import json
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = "nexoeventos-demo.duckdns.org"


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    alb = subprocess.check_output(["terraform", "output", "-raw", "alb_dns_name"], cwd=ROOT / "infra" / "aws-v2", text=True).strip()
    alb_ip = sorted({a[4][0] for a in socket.getaddrinfo(alb, 443, socket.AF_INET)})[0]
    real_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **k: real_getaddrinfo(alb_ip if host == DOMAIN else host, *a, **k)
    original_init = httpx.Client.__init__

    def init(self, *a, **k):  # una conexión nueva por solicitud: el ALB elige instancia en cada una
        headers = dict(k.pop("headers", None) or {})
        headers["Connection"] = "close"
        original_init(self, *a, headers=headers, **k)

    httpx.Client.__init__ = init
    flow = load("flow", "scripts/cloud/verify-controlled-flow.py")
    measure = load("v2m", "scripts/cloud/v2-measure.py")
    start = datetime.now(timezone.utc)
    sys.argv = ["verify-controlled-flow.py", "--out", args.out, "--skip-ui"]
    code = 0
    try:
        flow.main()
    except SystemExit as exit_:
        code = int(exit_.code or 0)
    end = datetime.now(timezone.utc) + timedelta(seconds=5)
    window = (start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ"))
    dist = {}
    for instance in sorted(measure.target_health()):
        log = measure.ssm_output(instance, "cat /var/log/nginx/nexoeventos-access.log")
        dist[instance[-6:]] = {"api": measure.count_requests(log, *window), "session": measure.count_requests(log, *window, prefix="/api/auth/session"),
                               "reservations": measure.count_requests(log, *window, prefix="/api/events/9010")}
    total = sum(v["api"]["requests"] for v in dist.values()) or 1
    summary = {"window_utc": window, "target": "ALB de V2 (dominio autorizado resuelto a la IP del ALB, una conexión por solicitud)", "distribution": dist,
               "share_pct": {k: round(100 * v["api"]["requests"] / total) for k, v in dist.items()}}
    (Path(args.out) / "reparto-instancias.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Reparto entre instancias:", {k: f"{v['api']['requests']} solicitudes /api ({summary['share_pct'][k]} %), {v['session']['requests']} lecturas de sesión, 5xx {v['api']['errors_5xx']}" for k, v in dist.items()})
    sys.exit(code)


if __name__ == "__main__":
    main()
