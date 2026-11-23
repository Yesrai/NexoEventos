#!/usr/bin/env python3
"""Validación LOCAL (Docker) de las plantillas de Zabbix: importa las dos plantillas, crea un host con un servicio simulado (contenedor 'nexo-mock', HTTPS con certificado
autofirmado) y comprueba (1) valores en vivo de las sondas, (2) que un fallo real (parar el contenedor) dispara el trigger y que se recupera, (3) la carga histórica con history.push
conservando la marca de tiempo. No usa nubes. Requiere el laboratorio de work/obs-lab (docker compose) y 'docker' en el PATH.
Uso: python3 scripts/observability/lab-validate.py [--url http://localhost:18080] [--skip-outage]"""
import argparse, pathlib, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from zbx import Zabbix

ap = argparse.ArgumentParser(); ap.add_argument("--url", default="http://localhost:18080"); ap.add_argument("--skip-outage", action="store_true"); a = ap.parse_args()
ROOT = pathlib.Path(__file__).resolve().parents[2]; TPL = ROOT / "ansible/roles/monitoring_zabbix_grafana/files/zabbix"
RULES = {"template_groups": {"createMissing": True, "updateExisting": True}, "templates": {"createMissing": True, "updateExisting": True},
         "items": {"createMissing": True, "updateExisting": True, "deleteMissing": True}, "triggers": {"createMissing": True, "updateExisting": True, "deleteMissing": True}}
res = []


def check(name, ok, detail=""):
    res.append(ok); print(("OK    " if ok else "FALLÓ ") + name + (f" — {detail}" if detail else ""), flush=True)


_pwf = ROOT / "work/obs-lab/secrets/admin"
z = Zabbix(a.url); z.login("Admin", _pwf.read_text().strip() if _pwf.exists() else "zabbix")   # laboratorio: la contraseña la fija zabbix_configure.py
for f in ("template_nexoeventos_probes.yaml", "template_nexoeventos_historical.yaml"):
    z.call("configuration.import", {"format": "yaml", "source": (TPL / f).read_text(), "rules": RULES})
check("plantillas importadas (probes + historical)", True)
tp = {t["host"]: t["templateid"] for t in z.call("template.get", {"filter": {"host": ["NexoEventos HTTP Probes", "NexoEventos Historical Metrics"]}, "output": ["host"]})}
grp = z.call("hostgroup.get", {"filter": {"name": ["NexoEventos/Lab"]}})
gid = grp[0]["groupid"] if grp else z.call("hostgroup.create", {"name": "NexoEventos/Lab"})["groupids"][0]
for h in z.call("host.get", {"filter": {"host": ["lab-aws-v1", "lab-hist"]}, "output": ["hostid"]}):
    z.call("host.delete", [h["hostid"]])
iface = {"type": 1, "main": 1, "useip": 0, "ip": "", "dns": "agent", "port": "10050"}
z.call("host.create", {"host": "lab-aws-v1", "name": "LAB — servicio simulado", "groups": [{"groupid": gid}], "interfaces": [iface], "templates": [{"templateid": tp["NexoEventos HTTP Probes"]}],
                       "macros": [{"macro": "{$NEXO.HOST}", "value": "mock"}]})
z.call("host.create", {"host": "lab-hist", "name": "LAB — histórico", "groups": [{"groupid": gid}], "templates": [{"templateid": tp["NexoEventos Historical Metrics"]}]})


def latest(key):
    it = z.call("item.get", {"host": "lab-aws-v1", "search": {"key_": key}, "output": ["lastvalue", "lastclock", "state", "error"]})
    return it[0] if it else None


def wait(cond, timeout, step=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = cond()
        if v:
            return v
        time.sleep(step)
    return None


ok = wait(lambda: (latest("nexo.http.healthz.code") or {}).get("lastvalue") == "200" and (latest("nexo.tls.not_after") or {}).get("lastvalue") not in (None, "", "0"), 420)
c = latest("nexo.http.healthz.code"); e = latest("nexo.http.events.code"); p = latest("web.page.perf"); t = latest("nexo.tls.not_after")
check("healthz = 200 con el servicio simulado", c and c["lastvalue"] == "200", f"valor={c and c['lastvalue']}")
check("catálogo /api/events = 200", e and e["lastvalue"] == "200", f"valor={e and e['lastvalue']}")
check("latencia medida por el agente", p and p["state"] == "0" and float(p["lastvalue"] or 0) >= 0, f"{p and p['lastvalue']} s (estado {p and p['state']})")
check("vencimiento TLS leído (dependiente)", t and int(t["lastvalue"] or 0) > time.time(), f"días restantes ≈ {(int(t['lastvalue'] or 0) - time.time()) / 86400:.0f}" if t else "")
problems = lambda: z.call("problem.get", {"hostids": z.call("host.get", {"filter": {"host": ["lab-aws-v1"]}, "output": ["hostid"]})[0]["hostid"], "output": ["name", "severity", "clock"]})
check("sin problemas activos antes del fallo", len(problems()) == 0, f"{len(problems())}")
if not a.skip_outage:
    subprocess.run(["docker", "stop", "nexo-mock"], capture_output=True)
    t_fail = time.time()
    pr = wait(lambda: [x for x in problems() if "no disponible" in x["name"]], 420)
    check("el fallo real dispara el trigger «NexoEventos no disponible» (severidad alta)", bool(pr) and pr[0]["severity"] == "4", f"detección en {time.time() - t_fail:.0f} s" if pr else "no se detectó en 7 min")
    c = latest("nexo.http.healthz.code"); check("sin respuesta → valor 0 (no «no soportado»)", c and c["lastvalue"] == "0", f"valor={c and c['lastvalue']} estado={c and c['state']} {c and c['error'][:60]}")
    subprocess.run(["docker", "start", "nexo-mock"], capture_output=True); t_rec = time.time()
    rec = wait(lambda: not [x for x in problems() if "no disponible" in x["name"]], 420)
    check("recuperación: el problema se resuelve al volver el servicio", bool(rec), f"recuperado en {time.time() - t_rec:.0f} s")
# histórico: history.push con marca de tiempo original
base = int(time.time()) - 6 * 3600
rows = [{"host": "lab-hist", "key": "nexo.hist.cpu_pct", "value": str(10 + i), "clock": base + i * 60} for i in range(5)]
z.call("history.push", rows); time.sleep(8)
it = z.call("item.get", {"host": "lab-hist", "search": {"key_": "nexo.hist.cpu_pct"}, "output": ["itemid"]})[0]["itemid"]
h = z.call("history.get", {"itemids": it, "history": 0, "output": ["clock", "value"], "sortfield": "clock", "sortorder": "ASC"})
check("history.push conserva valor y marca de tiempo original (5/5)", len(h) == 5 and int(h[0]["clock"]) == base and h[-1]["value"].startswith("14"), f"{len(h)} puntos; primer reloj {h[0]['clock'] if h else '-'}")
print(f"\n{sum(res)}/{len(res)} comprobaciones correctas"); sys.exit(0 if all(res) else 1)
