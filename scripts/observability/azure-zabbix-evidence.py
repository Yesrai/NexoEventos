#!/usr/bin/env python3
"""Evidencia del estado REAL de Zabbix en la VM de Azure, leída por su API (solo lectura). Distingue MEDICIONES EN VIVO (hosts con agente/sondas de esta ventana)
de DATOS HISTÓRICOS cargados (hosts «hist-*»: AWS/OCI/k6/failover de ejecuciones anteriores). No imprime contraseñas, tokens, IPs ni correos.
Uso: azure-zabbix-evidence.py --url https://<fqdn>/zabbix --password-file work/ansible-secrets/monitoring/zabbix_admin [--out archivo.json] [--fqdn <fqdn>]"""
import argparse, json, pathlib, re, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from zbx import Zabbix

ap = argparse.ArgumentParser(); ap.add_argument("--url", required=True); ap.add_argument("--password-file", required=True); ap.add_argument("--out"); ap.add_argument("--fqdn", default="")
a = ap.parse_args()
z = Zabbix(a.url, insecure_tls=True)   # certificado autofirmado: su huella se verifica aparte (acceso-https-y-puertos.txt)
z.login("Admin", pathlib.Path(a.password_file).read_text().strip())
mask = lambda s: re.sub(r"\d{1,3}(\.\d{1,3}){3}", "<ip>", s.replace(a.fqdn, "<fqdn>") if a.fqdn else s)
out = {"version_api": z.call("apiinfo.version", auth=False), "hora_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
hosts = z.call("host.get", {"output": ["hostid", "host", "status"], "selectParentTemplates": ["host"], "selectInterfaces": ["available", "type"]})
rows = []
for h in sorted(hosts, key=lambda x: x["host"]):
    items = z.call("item.get", {"hostids": h["hostid"], "output": ["itemid", "key_", "state", "status", "lastvalue", "lastclock", "value_type", "units"]})
    act = [i for i in items if i["status"] == "0"]
    rows.append({"host": h["host"], "tipo_datos": "HISTÓRICO (cargado)" if h["host"].endswith("-historico") else "EN VIVO (medido en esta ventana)",
                 "habilitado": h["status"] == "0", "plantillas": sorted(t["host"] for t in h["parentTemplates"]),
                 "interfaz_agente_disponible": [i["available"] for i in h["interfaces"]], "items_activos": len(act),
                 "items_no_soportados": sum(1 for i in act if i["state"] == "1"), "items_con_valor": sum(1 for i in act if i["lastclock"] != "0")})
for r in rows:   # los datos históricos cargados con history.push conservan su marca de tiempo antigua: «último valor» no se actualiza, se cuentan con history.get
    if r["tipo_datos"].startswith("HIST"):
        hid = [x for x in hosts if x["host"] == r["host"]][0]["hostid"]; tot = 0; claves = {}
        for i in z.call("item.get", {"hostids": hid, "output": ["itemid", "key_", "value_type"]}):
            n = int(z.call("history.get", {"itemids": i["itemid"], "history": int(i["value_type"]), "countOutput": True}))
            if n: claves[i["key_"]] = n; tot += n
        r["puntos_historicos_cargados"] = tot; r["series_con_datos"] = len(claves); r["puntos_por_serie"] = claves
out["hosts"] = rows
trg = z.call("trigger.get", {"output": ["description", "priority", "value", "status"], "filter": {"status": "0"}, "expandDescription": True, "selectHosts": ["host"], "monitored": True})
out["triggers_activos"] = len(trg); out["triggers_en_problema"] = sorted(f'{t["hosts"][0]["host"]}: {t["description"]}' for t in trg if t["value"] == "1")
out["problemas_actuales"] = [{"nombre": p["name"], "severidad": p["severity"], "desde_utc": time.strftime("%H:%M:%SZ", time.gmtime(int(p["clock"])))} for p in z.call("problem.get", {"output": ["name", "severity", "clock"], "recent": False})]
out["usuarios"] = sorted(u["username"] for u in z.call("user.get", {"output": ["username"]}))
out["tipos_de_medio"] = sorted(m["name"] for m in z.call("mediatype.get", {"output": ["name"]}))
out["acciones"] = sorted(x["name"] for x in z.call("action.get", {"output": ["name"]}))
out["plantillas_nexo"] = sorted(t["host"] for t in z.call("template.get", {"search": {"host": "NexoEventos"}, "output": ["host"]}))
live = [r for r in rows if r["tipo_datos"].startswith("EN VIVO")]
vals = []
for h in live:
    hid = [x for x in hosts if x["host"] == h["host"]][0]["hostid"]
    for i in z.call("item.get", {"hostids": hid, "output": ["name", "key_", "lastvalue", "lastclock", "units"], "search": {"key_": "nexo."}}) [:12]:
        if i["lastclock"] != "0": vals.append({"host": h["host"], "item": i["name"], "valor": i["lastvalue"][:60], "unidad": i["units"], "hace_s": int(time.time()) - int(i["lastclock"])})
out["valores_en_vivo_nexo"] = vals
txt = mask(json.dumps(out, indent=2, ensure_ascii=False))
if a.out: pathlib.Path(a.out).write_text(txt + "\n")
print(txt)
