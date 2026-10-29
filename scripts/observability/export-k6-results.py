#!/usr/bin/env python3
"""Convierte los resultados REALES de las pruebas de carga (perf/results/*/nivel-*.json, ejecutadas contra AWS V1/V2 en octubre de 2026) en puntos para Zabbix:
latencia p95, peticiones por segundo y errores inesperados, con la hora real de cada peldaño (punto en el instante medio). Solo lectura de archivos locales.
Uso: export-k6-results.py [--results perf/results] [--out work/observability/k6-results.json]"""
import argparse, json, os, pathlib, re

ap = argparse.ArgumentParser(); ap.add_argument("--results", default="perf/results"); ap.add_argument("--out", default="work/observability/k6-results.json"); a = ap.parse_args()
RX = re.compile(r"(\d+) VUs · ([\d.]+) req/s · p50 [\d.]+ / p95 ([\d.]+) / p99 [\d.]+ ms · errores (\d+)")
points, runs = [], []
for f in sorted(pathlib.Path(a.results).glob("*/nivel-*.json")) + sorted(pathlib.Path(a.results).glob("*/*same_seat.json")):
    d = json.load(open(f))
    if "start_epoch" not in d:
        continue
    m = next((RX.search(l) for l in d.get("stdout_tail", []) if RX.search(l)), None)
    if not m:
        continue
    mid = int((d["start_epoch"] + d["end_epoch"]) / 2)
    for key, val in (("nexo.hist.k6_p95_ms", float(m.group(3))), ("nexo.hist.k6_rps", float(m.group(2))), ("nexo.hist.k6_errors", float(m.group(4)))):
        points.append({"host": "aws-historico", "key": key, "clock": mid, "value": val})
    runs.append({"archivo": str(f), "vus": int(m.group(1)), "clock": mid})
out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"schema": 1, "source": "perf/results (k6 contra AWS)", "runs": runs, "points": points}, indent=1)); os.chmod(out, 0o600)
print(f"{len(runs)} peldaños con resultados → {len(points)} puntos → {out}")
