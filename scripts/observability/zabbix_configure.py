#!/usr/bin/env python3
"""Configura Zabbix de forma idempotente por API (se ejecuta en la VM de monitoreo, o contra el laboratorio local):
 - cambia la contraseña inicial de Admin; importa las dos plantillas de NexoEventos;
 - crea grupos y hosts (producción AWS vigilada con sondas en vivo, AWS e OCI históricos, la propia VM de Azure);
 - usuarios de mínimo privilegio: «grafana-ro» (solo lectura, sin acceso a la interfaz) y «history-push» (lectura/escritura solo en los grupos históricos; con token de API);
 - medio de alerta «Registro local de alertas» (script) y acción para problemas de severidad ≥ Warning; Email solo si se define SMTP.
Las contraseñas se leen de archivos (0600); nunca se imprimen. Salida: resumen JSON sin secretos.
Uso: zabbix_configure.py --url https://127.0.0.1/zabbix [--insecure] --admin-password-file F --grafana-password-file F --token-out F [--probe-host DNS] [--smtp-server ...]"""
from __future__ import annotations
import argparse, json, os, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from zbx import Zabbix

ap = argparse.ArgumentParser()
ap.add_argument("--url", required=True); ap.add_argument("--insecure", action="store_true")
ap.add_argument("--admin-password-file", required=True); ap.add_argument("--grafana-password-file", required=True)
ap.add_argument("--token-out", required=True); ap.add_argument("--templates-dir", default=str(pathlib.Path(__file__).parent))
ap.add_argument("--probe-host", default="nexoeventos-demo.duckdns.org"); ap.add_argument("--agent-dns", default="127.0.0.1")
ap.add_argument("--default-admin-password", default="zabbix"); ap.add_argument("--alert-script", default="nexo-alert-log.sh")
ap.add_argument("--smtp-server", default=""); ap.add_argument("--smtp-from", default=""); ap.add_argument("--alert-email", default=""); ap.add_argument("--smtp-env", default="")
a = ap.parse_args()
rd = lambda p: pathlib.Path(p).read_text().strip()
admin_pw, gf_pw = rd(a.admin_password_file), rd(a.grafana_password_file)
z = Zabbix(a.url, insecure_tls=a.insecure)
for _ in range(60):
    try:
        z.call("apiinfo.version", auth=False); break
    except Exception:
        time.sleep(5)
else:
    sys.exit("La API de Zabbix no responde")
summary = {"zabbix": z.call("apiinfo.version", auth=False)}
try:
    z.login("Admin", admin_pw)
except RuntimeError:                                   # primera ejecución: contraseña inicial de fábrica
    z.login("Admin", a.default_admin_password)
    uid = z.call("user.get", {"filter": {"username": "Admin"}, "output": ["userid"]})[0]["userid"]
    z.call("user.update", {"userid": uid, "passwd": admin_pw, "current_passwd": a.default_admin_password})
    z.login("Admin", admin_pw)
    summary["admin_password_changed"] = True
RULES = {"template_groups": {"createMissing": True, "updateExisting": True}, "templates": {"createMissing": True, "updateExisting": True},
         "items": {"createMissing": True, "updateExisting": True, "deleteMissing": True}, "triggers": {"createMissing": True, "updateExisting": True, "deleteMissing": True}}
for f in sorted(pathlib.Path(a.templates_dir).glob("template_nexoeventos_*.yaml")):
    z.call("configuration.import", {"format": "yaml", "source": f.read_text(), "rules": RULES})
summary["templates"] = sorted(t["host"] for t in z.call("template.get", {"search": {"host": "NexoEventos"}, "output": ["host"]}))


def group(name):
    g = z.call("hostgroup.get", {"filter": {"name": [name]}, "output": ["groupid"]})
    return g[0]["groupid"] if g else z.call("hostgroup.create", {"name": name})["groupids"][0]


def tpl(name):
    return z.call("template.get", {"filter": {"host": [name]}, "output": ["templateid"]})[0]["templateid"]


def ensure_host(host, desc, groups, templates, interfaces=None, macros=None):
    # Nombre visible = nombre técnico: el plugin de Grafana filtra por el nombre visible y así los paneles no dependen de textos largos.
    cur = z.call("host.get", {"filter": {"host": [host]}, "output": ["hostid"]})
    base = {"host": host, "name": host, "description": desc, "groups": [{"groupid": g} for g in groups], "templates": [{"templateid": t} for t in templates]}
    if macros:
        base["macros"] = macros
    if cur:
        z.call("host.update", {"hostid": cur[0]["hostid"], **base}); return cur[0]["hostid"]
    if interfaces:
        base["interfaces"] = interfaces
    return z.call("host.create", base)["hostids"][0]


G = {n: group(n) for n in ("NexoEventos/Producción AWS (sondas en vivo)", "NexoEventos/Recuperación OCI", "NexoEventos/Histórico (datos reales importados)", "NexoEventos/Azure observabilidad")}
agent_if = [{"type": 1, "main": 1, "useip": 1, "ip": a.agent_dns, "dns": "", "port": "10050"}] if a.agent_dns.replace(".", "").isdigit() else [{"type": 1, "main": 1, "useip": 0, "ip": "", "dns": a.agent_dns, "port": "10050"}]
ensure_host("aws-nexoeventos-v1", "AWS — NexoEventos V1 (sondas externas en vivo)", [G["NexoEventos/Producción AWS (sondas en vivo)"]], [tpl("NexoEventos HTTP Probes")], agent_if, [{"macro": "{$NEXO.HOST}", "value": a.probe_host}])
ensure_host("aws-historico", "AWS — métricas históricas reales (CloudWatch y pruebas de carga)", [G["NexoEventos/Histórico (datos reales importados)"]], [tpl("NexoEventos Historical Metrics")])
ensure_host("oci-historico", "OCI — métricas históricas reales (OCI Monitoring)", [G["NexoEventos/Histórico (datos reales importados)"], G["NexoEventos/Recuperación OCI"]], [tpl("NexoEventos Historical Metrics")])
selfs = [tpl(n) for n in ("Linux by Zabbix agent", "Zabbix server health") if z.call("template.get", {"filter": {"host": [n]}, "output": ["templateid"]})]
ensure_host("azure-obs", "Azure — VM de monitoreo (Zabbix + Grafana)", [G["NexoEventos/Azure observabilidad"]], selfs, agent_if)
summary["hosts"] = sorted(h["host"] for h in z.call("host.get", {"output": ["host"], "groupids": list(G.values())}))

# --- usuarios de mínimo privilegio ---
role = z.call("role.get", {"filter": {"name": ["User role"]}, "output": ["roleid"]})[0]["roleid"]


def ensure_group(name, rights, gui=3):
    g = z.call("usergroup.get", {"filter": {"name": [name]}, "output": ["usrgrpid"]})
    p = {"name": name, "gui_access": gui, "hostgroup_rights": [{"id": i, "permission": perm} for i, perm in rights]}
    if g:
        z.call("usergroup.update", {"usrgrpid": g[0]["usrgrpid"], **p}); return g[0]["usrgrpid"]
    return z.call("usergroup.create", p)["usrgrpids"][0]


def ensure_user(name, pw, ugid):
    u = z.call("user.get", {"filter": {"username": [name]}, "output": ["userid"]})
    if u:
        z.call("user.update", {"userid": u[0]["userid"], "passwd": pw, "usrgrps": [{"usrgrpid": ugid}], "roleid": role}); return u[0]["userid"]
    return z.call("user.create", {"username": name, "passwd": pw, "roleid": role, "usrgrps": [{"usrgrpid": ugid}]})["userids"][0]


all_ids = list(G.values())
ro_ug = ensure_group("Grafana — solo lectura", [(i, 2) for i in all_ids], gui=3)           # 3 = interfaz web deshabilitada; solo API
ensure_user("grafana-ro", gf_pw, ro_ug)
hist_ids = [G["NexoEventos/Histórico (datos reales importados)"], G["NexoEventos/Recuperación OCI"]]
push_ug = ensure_group("Carga histórica — escritura acotada", [(i, 3) for i in hist_ids], gui=3)
push_pw = os.urandom(24).hex()
push_uid = ensure_user("history-push", push_pw, push_ug)
summary["usuarios"] = ["Admin", "grafana-ro (lectura, sin interfaz web)", "history-push (escritura solo en grupos históricos, sin interfaz web)"]
tok_path = pathlib.Path(a.token_out)
if not tok_path.exists() or not z.call("token.get", {"filter": {"name": ["history-push"]}, "output": ["tokenid"]}):
    for t in z.call("token.get", {"filter": {"name": ["history-push"]}, "output": ["tokenid"]}):
        z.call("token.delete", [t["tokenid"]])
    tid = z.call("token.create", {"name": "history-push", "userid": push_uid})["tokenids"][0]
    tok = z.call("token.generate", [tid])[0]["token"]
    fd = os.open(tok_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600); os.write(fd, tok.encode()); os.close(fd)
    summary["token_historico"] = f"generado y guardado en {tok_path} (0600; no se muestra)"

# --- alertas: medio «Registro local de alertas» (script) + acción; Email si hay SMTP ---
mt = z.call("mediatype.get", {"filter": {"name": ["Registro local de alertas"]}, "output": ["mediatypeid"]})
mparams = {"name": "Registro local de alertas", "type": 1, "exec_path": a.alert_script, "parameters": [{"sortorder": 0, "value": "{ALERT.SENDTO}"}, {"sortorder": 1, "value": "{ALERT.SUBJECT}"}, {"sortorder": 2, "value": "{ALERT.MESSAGE}"}], "status": 0,
           # Sin plantillas de mensaje Zabbix 7.0 descarta la alerta («No message defined for media type»): se definen para problema, recuperación y actualización.
           "message_templates": [{"eventsource": 0, "recovery": r, "subject": sub, "message": "{EVENT.DATE} {EVENT.TIME} | {HOST.NAME} | severidad {EVENT.SEVERITY} | {EVENT.NAME} | id {EVENT.ID}"}
                                 for r, sub in ((0, "PROBLEMA: {EVENT.NAME}"), (1, "RESUELTO: {EVENT.NAME}"), (2, "ACTUALIZADO: {EVENT.NAME}"))]}
mtid = mt[0]["mediatypeid"] if mt else z.call("mediatype.create", mparams)["mediatypeids"][0]
if mt:
    z.call("mediatype.update", {"mediatypeid": mtid, **mparams})
medias = [{"mediatypeid": mtid, "sendto": ["registro-local"], "active": 0, "severity": 60, "period": "1-7,00:00-24:00"}]   # Warning(4)+Average(8)+High(16)+Disaster(32)
if a.smtp_server and a.alert_email:
    env = dict(l.split("=", 1) for l in pathlib.Path(a.smtp_env).read_text().splitlines() if "=" in l) if a.smtp_env and pathlib.Path(a.smtp_env).exists() else {}
    em = z.call("mediatype.get", {"filter": {"name": ["Email"]}, "output": ["mediatypeid"]})[0]["mediatypeid"]
    z.call("mediatype.update", {"mediatypeid": em, "status": 0, "smtp_server": a.smtp_server, "smtp_port": "587", "smtp_email": a.smtp_from, "smtp_security": 1, "smtp_authentication": 1 if env else 0,
                                "username": env.get("SMTP_USER", ""), "passwd": env.get("SMTP_PASSWORD", "")})
    medias.append({"mediatypeid": em, "sendto": [a.alert_email], "active": 0, "severity": 60, "period": "1-7,00:00-24:00"})
    summary["email"] = "configurado (credenciales SMTP desde archivo local; no se muestran)"
admin_id = z.call("user.get", {"filter": {"username": ["Admin"]}, "output": ["userid"]})[0]["userid"]
z.call("user.update", {"userid": admin_id, "medias": medias})
ug_admin = z.call("usergroup.get", {"filter": {"name": ["Zabbix administrators"]}, "output": ["usrgrpid"]})[0]["usrgrpid"]
act_name = "NexoEventos — notificar problemas y recuperaciones"
ops = {"esc_period": "1h", "eventsource": 0, "status": 0, "name": act_name, "pause_suppressed": 1, "notify_if_canceled": 1,
       "filter": {"evaltype": 0, "conditions": [{"conditiontype": 4, "operator": 5, "value": "2"}]},       # severidad ≥ Warning
       "operations": [{"operationtype": 0, "esc_step_from": 1, "esc_step_to": 1, "opmessage": {"default_msg": 1, "mediatypeid": "0"}, "opmessage_grp": [{"usrgrpid": ug_admin}]}],
       "recovery_operations": [{"operationtype": 11, "opmessage": {"default_msg": 1}}]}
cur = z.call("action.get", {"filter": {"name": [act_name]}, "output": ["actionid"]})
(z.call("action.update", {"actionid": cur[0]["actionid"], **ops}) if cur else z.call("action.create", ops))
summary["accion_de_alertas"] = act_name
print(json.dumps(summary, ensure_ascii=False, indent=2))
