#!/usr/bin/env python3
"""Carga en Zabbix (history.push) los puntos históricos reales exportados, conservando su marca de tiempo original. Los ítems son de tipo «trapper» de la plantilla
«NexoEventos Historical Metrics». El token de API es el del usuario «history-push» (escritura solo en los grupos históricos); se lee de un archivo 0600 y nunca se imprime.
Uso: push-history.py --url https://<vm>/zabbix --token-file work/ansible-secrets/monitoring/history_push_token [--insecure] --in a.json [--in b.json ...] [--dry-run]"""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from zbx import Zabbix

ap = argparse.ArgumentParser(); ap.add_argument("--url", required=True); ap.add_argument("--token-file", required=True); ap.add_argument("--insecure", action="store_true")
ap.add_argument("--in", dest="inputs", action="append", required=True); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
def load_points(f):
    d = json.load(open(f))
    return d["points_derivados"]["points"] if d.get("schema") == 2 else d["points"]   # esquema 2 de export-cloudwatch.py: los puntos DERIVADOS van aparte de las series originales


points = [p for f in a.inputs for p in load_points(f)]
by = {}
for p in points:
    by.setdefault((p["host"], p["key"]), 0); by[(p["host"], p["key"])] += 1
for (h, k), n in sorted(by.items()):
    print(f"  {h:15s} {k:34s} {n:6d} puntos")
if a.dry_run:
    sys.exit(f"[dry-run] {len(points)} puntos; no se envió nada")
z = Zabbix(a.url, pathlib.Path(a.token_file).read_text().strip(), a.insecure)
# Comprobación previa: cada (host, clave) debe existir como ítem trapper (si la plantilla se acaba de importar, el servidor tarda hasta ~1 min en cargar su caché de configuración).
missing = []
for (h, k) in by:
    it = z.call("item.get", {"host": h, "filter": {"key_": k}, "output": ["itemid", "type"]})
    if not it or it[0]["type"] != "2":
        missing.append((h, k))
if missing:
    sys.exit("Faltan ítems trapper en Zabbix (¿plantilla sin importar o host sin vincular?): " + ", ".join(f"{h}/{k}" for h, k in missing[:5]))
sent = 0
for i in range(0, len(points), 500):
    batch = [{"host": p["host"], "key": p["key"], "value": str(p["value"]), "clock": int(p["clock"])} for p in points[i:i + 500]]
    res = z.call("history.push", batch)
    bad = [r for r in (res.get("data", []) if isinstance(res, dict) else res) if isinstance(r, dict) and r.get("error")]
    if res.get("response") != "success" or bad:
        sys.exit(f"history.push rechazó puntos ({len(bad)} errores): {(bad[0]['error'] if bad else str(res))[:160]}")
    sent += len(batch)
print(f"{sent} puntos cargados con su marca de tiempo original")
