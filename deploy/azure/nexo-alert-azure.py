#!/usr/bin/env python3
"""Tipo de medio de Zabbix (script) → correo REAL reutilizando Azure Monitor: publica la métrica personalizada NexoEventos/sondas_fallidas de ESTA VM con su identidad administrada (token de IMDS; SIN secretos,
sin SMTP). Una regla de métricas (`alerta-nexo-sonda`) sobre esa métrica dispara el grupo de acción `ag-nexoeventos-obs` ya existente, que envía el correo.
Parámetros de Zabbix: sendto subject message host value  (value: 1 = problema, 0 = recuperación; solo los problemas publican la métrica). Siempre deja una línea JSON en el registro local (sin secretos).
Variables solo para pruebas: NEXO_IMDS_URL, NEXO_METRICS_BASE (http local permitido únicamente con NEXO_ALLOW_HTTP=1), NEXO_ALERT_LOG. Salida ≠ 0 si la publicación falla (Zabbix lo registra como alerta fallida)."""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

IMDS = os.environ.get("NEXO_IMDS_URL", "http://169.254.169.254")
LOG = os.environ.get("NEXO_ALERT_LOG", "/var/log/zabbix/alertas-nexoeventos-azure.log")
NS, METRIC = "NexoEventos", "sondas_fallidas"


def clean(v, n=100):
    return re.sub(r"[^A-Za-z0-9._ -]", "_", str(v))[:n] or "desconocido"


def get(url, headers=None, data=None, timeout=10):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:        # noqa: S310 (IMDS fijo; el destino de métricas se valida abajo)
        return json.loads(r.read(65536) or b"{}")


def log(rec):
    rec = {"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **rec}
    try:
        fd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
        with os.fdopen(fd, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def build_body(host, evento, now=None):
    t = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S")
    return {"time": t, "data": {"baseData": {"metric": METRIC, "namespace": NS, "dimNames": ["host", "evento"], "series": [{"dimValues": [clean(host), clean(evento, 60)], "min": 1, "max": 1, "sum": 1, "count": 1}]}}}


def main(argv):
    sendto, subject, message, host, value = (argv + [""] * 5)[:5]
    if value.strip() != "1":
        log({"accion": "sin_publicar", "motivo": "no es un problema nuevo", "host": clean(host), "asunto": clean(subject, 120)}); return 0
    try:
        meta = get(IMDS + "/metadata/instance?api-version=2021-02-01", {"Metadata": "true"})["compute"]
        tok = get(IMDS + "/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fmonitor.azure.com%2F", {"Metadata": "true"})["access_token"]
        base = os.environ.get("NEXO_METRICS_BASE") or f"https://{meta['location']}.monitoring.azure.com"
        if not base.startswith("https://") and os.environ.get("NEXO_ALLOW_HTTP") != "1":
            raise ValueError("el destino de métricas debe ser https")
        rid = f"/subscriptions/{meta['subscriptionId']}/resourceGroups/{meta['resourceGroupName']}/providers/Microsoft.Compute/virtualMachines/{meta['name']}"
        get(base + rid + "/metrics", {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}, json.dumps(build_body(host, subject)).encode())
        log({"accion": "publicada", "metrica": f"{NS}/{METRIC}", "host": clean(host), "asunto": clean(subject, 120)}); return 0
    except Exception as e:  # noqa: BLE001
        log({"accion": "FALLO", "error": type(e).__name__, "host": clean(host), "asunto": clean(subject, 120)}); print("fallo al publicar la métrica: " + type(e).__name__, file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
