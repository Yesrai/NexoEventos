#!/usr/bin/env python3
"""Validación LOCAL (Docker) de Grafana: crea el origen de datos de Zabbix, activa el plugin, importa los paneles versionados y EJECUTA las consultas de cada panel contra
Zabbix para comprobar que devuelven series (usa datos de laboratorio cargados con history.push; no son evidencias). Uso: python3 scripts/observability/lab-grafana-validate.py
Requiere work/obs-lab (compose) y haber ejecutado zabbix_configure.py con el token en work/obs-lab/secrets/."""
import base64, json, pathlib, sys, time, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from zbx import Zabbix

ROOT = pathlib.Path(__file__).resolve().parents[2]; LAB = ROOT / "work/obs-lab"; GF = "http://localhost:13000"
AUTH = "Basic " + base64.b64encode(b"admin:lab-only-gf").decode()


def gf(method, path, body=None):
    req = urllib.request.Request(GF + path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json", "Authorization": AUTH}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode()[:300]}


res = []
def check(name, ok, detail=""):
    res.append(ok); print(("OK    " if ok else "FALLÓ ") + name + (f" — {detail}" if detail else ""), flush=True)


for _ in range(30):
    if "database" in (gf("GET", "/api/health") or {}):
        break
    time.sleep(3)
# datos de laboratorio en los hosts históricos
tok = (LAB / "secrets/push.token").read_text().strip(); z = Zabbix("http://localhost:18080", tok); now = int(time.time())
keys = {"aws-historico": ["nexo.hist.cpu_pct", "nexo.hist.db_cpu_pct", "nexo.hist.db_connections", "nexo.hist.alb_requests", "nexo.hist.alb_5xx", "nexo.hist.alb_target_time", "nexo.hist.asg_in_service", "nexo.hist.k6_p95_ms", "nexo.hist.k6_rps", "nexo.hist.k6_err_pct"],
        "oci-historico": ["nexo.hist.cpu_pct", "nexo.hist.mem_pct", "nexo.hist.net_in_bytes", "nexo.hist.net_out_bytes", "nexo.hist.bucket_bytes", "nexo.hist.bucket_objects"]}
rows = [{"host": h, "key": k, "value": str(20 + (i * 7 + j) % 50), "clock": now - 3600 + j * 120} for h, ks in keys.items() for i, k in enumerate(ks) for j in range(25)]
z.call("history.push", rows); time.sleep(10)
ds = gf("POST", "/api/datasources", {"name": "Zabbix", "uid": "zabbix-nexo", "type": "alexanderzobnin-zabbix-datasource", "access": "proxy", "url": "http://web:8080/api_jsonrpc.php", "isDefault": True,
        "jsonData": {"username": "grafana-ro", "trends": True, "trendsFrom": "7d", "trendsRange": "4d", "cacheTTL": "1m", "timeout": 30}, "secureJsonData": {"password": (LAB / "secrets/gf").read_text().strip()}})
if ds.get("_error") == 409:
    ds = gf("GET", "/api/datasources/uid/zabbix-nexo")
check("origen de datos de Zabbix creado (usuario de solo lectura)", "uid" in ds or "datasource" in ds or ds.get("name") == "Zabbix", str(ds)[:120] if ds.get("_error") else "")
st = gf("POST", "/api/plugins/alexanderzobnin-zabbix-app/settings", {"enabled": True, "pinned": True}); check("plugin de Zabbix activado", "_error" not in st, str(st)[:120])
h = gf("GET", "/api/datasources/uid/zabbix-nexo/health") if False else gf("POST", "/api/datasources/uid/zabbix-nexo/resources/zabbix-api", {"datasourceId": 1, "method": "apiinfo.version", "params": {}})
check("el plugin consulta la API de Zabbix (apiinfo.version)", "_error" not in h and str(h.get("result", "")).startswith("7.0"), str(h)[:100])
import re
za = Zabbix("http://localhost:18080"); za.login("Admin", (LAB / "secrets/admin").read_text().strip())   # lectura completa (el token de carga solo ve los grupos históricos)
total = ok_panels = 0
vals = {"A": 1}
for f in sorted((ROOT / "ansible/roles/monitoring_zabbix_grafana/files/grafana/dashboards").glob("*.json")):
    d = json.loads(f.read_text()); r = gf("POST", "/api/dashboards/db", {"dashboard": {**d, "id": None}, "overwrite": True, "folderUid": ""})
    check(f"panel importado: {d['title'][:60]}", "_error" not in r, str(r)[:120])
    m = re.match(r"now-(\d+)([hd])", d["time"]["from"]); span = int(m.group(1)) * (3600 if m.group(2) == "h" else 86400)   # rango del propio panel
    for p in d["panels"]:
        for t in [t for t in p.get("targets", []) if t.get("datasource", {}).get("uid") == "zabbix-nexo" and t.get("queryType") == "0"]:
            # El plugin evalúa las consultas en el navegador: se reproduce su filtro (host por nombre visible, ítem por expresión regular) contra la API de Zabbix.
            hosts = za.call("host.get", {"filter": {"name": [t["host"]["filter"]]}, "output": ["hostid"]})
            rx = re.compile(t["item"]["filter"].strip("/"))
            items = [i for i in za.call("item.get", {"hostids": [h["hostid"] for h in hosts], "output": ["itemid", "name", "value_type"]}) if rx.search(i["name"])] if hosts else []
            pts = sum(len(za.call("history.get", {"itemids": i["itemid"], "history": i["value_type"], "output": ["clock"], "time_from": int(time.time()) - span, "limit": 5})) for i in items)
            total += 1; ok_panels += 1 if pts > 0 else 0
            print(f"      · {'datos' if pts else 'SIN DATOS'} ({len(items)} ítem/s): {p['title'][:55]} ← {t['host']['filter']} {t['item']['filter'][:40]}", flush=True)
check(f"cada consulta de los paneles selecciona ítems con datos recientes ({ok_panels}/{total}; los de «en vivo» requieren las sondas en marcha)", total > 0 and ok_panels >= total - 0)
print(f"\n{sum(res)}/{len(res)} comprobaciones correctas"); sys.exit(0 if all(res) else 1)
