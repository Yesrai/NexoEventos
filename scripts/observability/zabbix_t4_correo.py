#!/usr/bin/env python3
"""T4 — canal de correo ADITIVO en Zabbix: crea (solo si no existen) el tipo de medio «NexoEventos → Azure Monitor (correo)», el grupo/usuario «alertas-azure» (sin interfaz web, solo lectura) y la acción
«T4 — notificar vía Azure Monitor». NO toca el medio «Registro local de alertas», el usuario Admin ni la acción existente (siguen registrando en el log local). `--retirar` borra SOLO lo creado aquí.
Uso: zabbix_t4_correo.py --url https://127.0.0.1/zabbix --insecure --admin-password-file F [--apply | --retirar]   (sin flags: plan de lectura)"""
import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
MT, UG, USR, ACT = "NexoEventos → Azure Monitor (correo)", "Alertas Azure (T4)", "alertas-azure", "T4 — notificar vía Azure Monitor"
SCRIPT = "nexo-alert-azure.py"
PARAMS = ["{ALERT.SENDTO}", "{ALERT.SUBJECT}", "{ALERT.MESSAGE}", "{HOST.NAME}", "{EVENT.VALUE}"]


def existing(z):
    g = lambda m, f, k: z.call(m, {"filter": f, "output": [k]})
    return {"mt": g("mediatype.get", {"name": [MT]}, "mediatypeid"), "ug": g("usergroup.get", {"name": [UG]}, "usrgrpid"), "usr": g("user.get", {"username": [USR]}, "userid"), "act": g("action.get", {"name": [ACT]}, "actionid")}


def apply(z):
    ex = existing(z); out = []
    if ex["mt"]:
        mt = ex["mt"][0]["mediatypeid"]; out.append("tipo de medio: ya existe (no se modifica)")
    else:
        mt = z.call("mediatype.create", {"name": MT, "type": 1, "exec_path": SCRIPT, "parameters": [{"sortorder": i, "value": v} for i, v in enumerate(PARAMS)], "status": 0, "maxattempts": 3,
              "message_templates": [{"eventsource": 0, "recovery": r, "subject": s, "message": "{EVENT.DATE} {EVENT.TIME} | {HOST.NAME} | severidad {EVENT.SEVERITY} | {EVENT.NAME} | id {EVENT.ID}"}
                                    for r, s in ((0, "PROBLEMA: {EVENT.NAME}"), (1, "RESUELTO: {EVENT.NAME}"), (2, "ACTUALIZADO: {EVENT.NAME}"))]})["mediatypeids"][0]; out.append("tipo de medio: creado")
    if ex["ug"]:
        ug = ex["ug"][0]["usrgrpid"]; out.append("grupo: ya existe")
    else:
        groups = [x["groupid"] for x in z.call("hostgroup.get", {"search": {"name": "NexoEventos/"}, "startSearch": True, "output": ["groupid"]})]
        ug = z.call("usergroup.create", {"name": UG, "gui_access": 3, "hostgroup_rights": [{"id": g, "permission": 2} for g in groups]})["usrgrpids"][0]; out.append("grupo: creado (lectura, sin interfaz web)")
    if ex["usr"]:
        out.append("usuario: ya existe")
    else:
        role = z.call("role.get", {"filter": {"name": ["User role"]}, "output": ["roleid"]})[0]["roleid"]
        z.call("user.create", {"username": USR, "passwd": os.urandom(24).hex(), "roleid": role, "usrgrps": [{"usrgrpid": ug}],
                               "medias": [{"mediatypeid": mt, "sendto": ["azure-monitor"], "active": 0, "severity": 60, "period": "1-7,00:00-24:00"}]}); out.append("usuario: creado (contraseña aleatoria, no se guarda ni se muestra)")
    if ex["act"]:
        out.append("acción: ya existe")
    else:
        z.call("action.create", {"name": ACT, "eventsource": 0, "status": 0, "esc_period": "1h", "pause_suppressed": 1, "notify_if_canceled": 1,
              "filter": {"evaltype": 0, "conditions": [{"conditiontype": 4, "operator": 5, "value": "2"}]},
              "operations": [{"operationtype": 0, "esc_step_from": 1, "esc_step_to": 1, "opmessage": {"default_msg": 1, "mediatypeid": mt}, "opmessage_grp": [{"usrgrpid": ug}]}],
              "recovery_operations": [{"operationtype": 11, "opmessage": {"default_msg": 1}}]}); out.append("acción: creada")
    return out


def retirar(z):
    ex = existing(z); out = []
    if ex["act"]: z.call("action.delete", [ex["act"][0]["actionid"]]); out.append("acción eliminada")
    if ex["usr"]: z.call("user.delete", [ex["usr"][0]["userid"]]); out.append("usuario eliminado")
    if ex["ug"]: z.call("usergroup.delete", [ex["ug"][0]["usrgrpid"]]); out.append("grupo eliminado")
    if ex["mt"]: z.call("mediatype.delete", [ex["mt"][0]["mediatypeid"]]); out.append("tipo de medio eliminado")
    return out or ["nada que retirar"]


def main(argv=None, zabbix_cls=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--url", required=True); ap.add_argument("--insecure", action="store_true"); ap.add_argument("--admin-password-file", required=True)
    g = ap.add_mutually_exclusive_group(); g.add_argument("--apply", action="store_true"); g.add_argument("--retirar", action="store_true")
    a = ap.parse_args(argv)
    if zabbix_cls is None:
        from zbx import Zabbix as zabbix_cls
    z = zabbix_cls(a.url, insecure_tls=a.insecure); z.login("Admin", pathlib.Path(a.admin_password_file).read_text().strip())
    if a.retirar: print(json.dumps(retirar(z), ensure_ascii=False)); return 0
    if a.apply: print(json.dumps(apply(z), ensure_ascii=False)); return 0
    ex = existing(z); print(json.dumps({"modo": "plan (lectura)", "ya_existe": {k: bool(v) for k, v in ex.items()}}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    sys.exit(main())
