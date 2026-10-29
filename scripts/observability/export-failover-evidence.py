#!/usr/bin/env python3
"""Convierte la evidencia REAL de la prueba de failover Multi-AZ de la RDS (23-oct-2026; sondeo de /healthz cada 1 s) en puntos para Zabbix:
código HTTP (0 = sin respuesta) y latencia por muestra. Solo lectura de archivos locales (docs/evidencias/multicloud/aws/20261023-rds-multiaz/failover/healthz-1s.json).
Uso: export-failover-evidence.py [--in ...] [--out work/observability/failover.json]"""
import argparse, datetime as dt, json, os, pathlib

ap = argparse.ArgumentParser(); ap.add_argument("--in", dest="src", default="docs/evidencias/multicloud/aws/20261023-rds-multiaz/failover/healthz-1s.json")
ap.add_argument("--out", default="work/observability/failover.json"); a = ap.parse_args()
pts = []
for r in json.load(open(a.src)):
    c = int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp())
    code = int(r["code"]); pts += [{"host": "aws-historico", "key": "nexo.hist.failover_healthz_code", "clock": c, "value": 0 if code == 0 else code},
                                    {"host": "aws-historico", "key": "nexo.hist.failover_healthz_s", "clock": c, "value": float(r["s"])}]
out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"schema": 1, "source": "evidencia del failover Multi-AZ (23-oct-2026)", "points": pts}, indent=1)); os.chmod(out, 0o600)
print(f"{len(pts)} puntos → {out}")
