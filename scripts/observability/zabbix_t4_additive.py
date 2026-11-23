#!/usr/bin/env python3
"""T4 — alta ADITIVA de hosts de sondas en el Zabbix existente de Azure. NUNCA actualiza ni borra lo que ya existe (plantillas, hosts, usuarios, acciones, medios): si un host ya existe, lo deja como está y lo informa.
Hosts (plantilla existente «NexoEventos HTTP Probes»; alertas y acción ya configuradas por el rol):
  aws-nexoeventos-v2        DESHABILITADO hasta T5 (balanceador ALB); --enable aws --host <DNS del ALB> lo activa y SOLO cambia ese host.
  oci-nexoeventos-recovery  DESHABILITADO hasta T6 (entrada pública de OCI); --enable oci --host <DNS|IP> lo activa.
  t4-sonda-prueba           HABILITADO, apunta a un nombre que nunca resuelve (.invalid): fuerza una alerta REAL de prueba; --remove-test lo elimina al terminar (reversión).
Uso: zabbix_t4_additive.py --url https://127.0.0.1/zabbix --insecure --admin-password-file F [--apply] [--enable aws|oci --host H] [--remove-test]
Sin --apply solo imprime el plan (lectura)."""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

PROBE_TEMPLATE = "NexoEventos HTTP Probes"
HOSTS = {
    "aws-nexoeventos-v2": {"desc": "AWS — NexoEventos V2 (ALB + ASG; T5)", "group": "NexoEventos/Producción AWS (sondas en vivo)", "probe": "pendiente-t5.invalid", "status": 1},
    "oci-nexoeventos-recovery": {"desc": "OCI — NexoEventos en recuperación (T3/T6)", "group": "NexoEventos/Recuperación OCI", "probe": "pendiente-t6.invalid", "status": 1},
    "t4-sonda-prueba": {"desc": "T4 — sonda de prueba que SIEMPRE falla (alerta real); se elimina al cerrar T4", "group": "NexoEventos/Azure observabilidad", "probe": "sonda-t4.invalid", "status": 0},
}
ENABLE = {"aws": "aws-nexoeventos-v2", "oci": "oci-nexoeventos-recovery"}
TEMPORALES = ("t4-sonda-prueba", "t4-control-positivo")      # hosts que --remove-test elimina (nada más)
CONTROL = "t4-control-positivo"                            # control POSITIVO: un destino que SÍ responde, para demostrar que las consultas/ítems funcionan cuando hay datos


def plan(z, args):
    """Lista de acciones; solo lee del Zabbix."""
    acts = []
    existing = {h["host"]: h for h in z.call("host.get", {"filter": {"host": list(HOSTS) + [CONTROL]}, "output": ["hostid", "host", "status"], "selectMacros": ["macro", "value"]})}
    if args.control and not args.remove_test:
        acts.append({"op": "skip", "host": CONTROL, "why": "ya existe"} if CONTROL in existing else {"op": "create", "host": CONTROL, "desc": "T4 — control positivo (destino que responde); se elimina al cerrar T4", "group": "NexoEventos/Azure observabilidad", "probe": args.control, "status": 0})
    if args.remove_test and CONTROL in existing:
        acts.append({"op": "delete", "host": CONTROL})
    for name, spec in HOSTS.items():
        if args.remove_test and name == "t4-sonda-prueba":
            acts.append({"op": "delete", "host": name} if name in existing else {"op": "skip", "host": name, "why": "no existe"})
        elif name in existing:
            acts.append({"op": "skip", "host": name, "why": "ya existe: no se modifica"})
        elif args.remove_test:
            acts.append({"op": "skip", "host": name, "why": "no se crea en modo de retirada"})
        else:
            acts.append({"op": "create", "host": name, **spec})
    if args.enable:
        name = ENABLE[args.enable]
        if name not in existing:
            acts.append({"op": "error", "host": name, "why": "no existe; ejecute antes el alta"})
        else:
            acts.append({"op": "enable", "host": name, "value": args.host, "hostid": existing[name]["hostid"]})
    return acts


def apply(z, acts):
    gid = lambda n: (z.call("hostgroup.get", {"filter": {"name": [n]}, "output": ["groupid"]}) or [{}])[0].get("groupid")
    tid = z.call("template.get", {"filter": {"host": [PROBE_TEMPLATE]}, "output": ["templateid"]})
    if not tid:
        raise SystemExit(f"falta la plantilla «{PROBE_TEMPLATE}» (la crea el rol existente); no se crea nada")
    out = []
    for a in acts:
        if a["op"] == "create":
            g = gid(a["group"])
            if not g:
                out.append({**a, "result": "FALLO: grupo inexistente"}); continue
            z.call("host.create", {"host": a["host"], "name": a["host"], "description": a["desc"], "status": a["status"], "groups": [{"groupid": g}], "templates": [{"templateid": tid[0]["templateid"]}],
                                   "macros": [{"macro": "{$NEXO.HOST}", "value": a["probe"]}],
                                   "interfaces": [{"type": 1, "main": 1, "useip": 1, "ip": "127.0.0.1", "dns": "", "port": "10050"}]})
            out.append({**a, "result": "creado"})
        elif a["op"] == "enable":
            z.call("host.update", {"hostid": a["hostid"], "status": 0, "macros": [{"macro": "{$NEXO.HOST}", "value": a["value"]}]})
            out.append({**a, "result": "habilitado"})
        elif a["op"] == "delete":
            h = z.call("host.get", {"filter": {"host": [a["host"]]}, "output": ["hostid"]})
            z.call("host.delete", [h[0]["hostid"]]); out.append({**a, "result": "eliminado"})
        else:
            out.append(a)
    return out


def main(argv=None, zabbix_cls=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True); ap.add_argument("--insecure", action="store_true"); ap.add_argument("--admin-password-file", required=True)
    ap.add_argument("--apply", action="store_true"); ap.add_argument("--enable", choices=sorted(ENABLE)); ap.add_argument("--host"); ap.add_argument("--remove-test", action="store_true"); ap.add_argument("--control", help="DNS de un destino que responde (control positivo)")
    a = ap.parse_args(argv)
    if a.enable and not a.host:
        ap.error("--enable requiere --host")
    if a.control and not all(c.isalnum() or c in ".-" for c in a.control):
        ap.error("--control inválido")
    if a.enable and not all(c.isalnum() or c in ".-" for c in a.host):
        ap.error("--host inválido")
    if zabbix_cls is None:
        from zbx import Zabbix as zabbix_cls
    z = zabbix_cls(a.url, insecure_tls=a.insecure)
    z.login("Admin", pathlib.Path(a.admin_password_file).read_text().strip())
    acts = plan(z, a)
    print(json.dumps({"modo": "aplicar" if a.apply else "plan (lectura)", "acciones": acts}, ensure_ascii=False, indent=1))
    if any(x["op"] == "error" for x in acts):
        return 2
    if a.apply:
        print(json.dumps(apply(z, acts), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
