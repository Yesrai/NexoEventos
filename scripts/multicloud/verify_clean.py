#!/usr/bin/env python3
"""B-17 · Verificador de recursos residuales y costos (SOLO LECTURA).

Responde, tras una prueba o una ventana de nube: «¿queda algo encendido que siga cobrando?». No crea, modifica, detiene ni elimina nada.
Dos fuentes de datos:
  --fixture ARCHIVO.json   inventario simulado (pruebas; NO se conecta a ninguna nube)
  --live                   ejecuta SOLO consultas de lectura (oci … list, aws … describe-*), con una lista blanca de comandos; hace falta --oci-compartment/--oci-ad (OCI) o --aws.
Códigos de salida (FAIL-CLOSED):  0 limpio · 1 hay recursos residuales/inesperados o se excedió el tope · 2 NO verificable (una consulta falló o un estado es desconocido: no se afirma «limpio»).
Salida: tabla legible o --json. Los identificadores se enmascaran (últimos 4–6 caracteres); no se imprimen cuentas, claves ni OCID completos.
Costos: estimaciones con tarifas públicas (ver PRICES; las marcadas «sin verificar» no están confirmadas con la facturación del proveedor).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

# USD por hora (volúmenes: USD por GB-mes → se convierte con /730). verified=False: tarifa no confirmada con la facturación real.
PRICES = {
    "oci.instance.E5.Flex": dict(ocpu=0.03, gb_ram=0.002, verified=True, src="docs/multicloud/08 (lista pública de Oracle, 23-oct)"),
    "oci.instance.A1.Flex": dict(ocpu=0.0, gb_ram=0.0, verified=False, src="Always Free hasta 4 OCPU/24 GB; fuera de eso, tarifa no verificada"),
    "oci.instance.E2.1.Micro": dict(flat=0.0, verified=True, src="Always Free"),
    "oci.volume_gb_month": dict(flat=0.0255, vpu_gb_month=0.0017, verified=True, src="docs/multicloud/08"),
    "oci.nat_gateway": dict(flat=0.0, verified=False, src="sin verificar"),
    "oci.load_balancer": dict(flat=0.0, verified=False, src="sin verificar (el LB flexible de 10 Mbps es Always Free)"),
    "oci.public_ip_reserved": dict(flat=0.0, verified=False, src="sin verificar"),
    "oci.bastion": dict(flat=0.0, verified=True, src="sin cargo"),
    "aws.ec2.t3.small": dict(flat=0.0208 + 0.005, verified=True, src="docs/operacion (t3.small + IPv4)"),
    "aws.alb": dict(flat=0.04, verified=True, src="informes 09–10 (horas + 2 IPv4)"),
    "aws.rds.multiaz.db.t3.micro": dict(flat=0.042, verified=True, src="informes 08–10"),
    "aws.rds.single.db.t3.micro": dict(flat=0.021, verified=False, src="sin verificar"),
    "aws.nat_gateway": dict(flat=0.045, verified=False, src="tarifa pública, sin verificar"),
    "aws.eip_unassociated": dict(flat=0.005, verified=True, src="IPv4 pública"),
    "aws.ebs_gb_month": dict(flat=0.08, verified=False, src="gp3 público, sin verificar"),
}
HOURS_PER_MONTH = 730.0


@dataclass
class Resource:
    provider: str
    kind: str
    ident: str                    # ya enmascarado
    state: str
    detail: str = ""
    hourly: float = 0.0
    age_h: float | None = None
    status: str = "RESIDUAL"      # RESIDUAL | ESPERADO | PENDIENTE (en borrado) | DESCONOCIDO
    price_verified: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def accrued(self) -> float | None:
        return None if self.age_h is None else round(self.hourly * self.age_h, 4)


def mask(value: str | None) -> str:
    v = str(value or "?")
    return v if len(v) <= 8 else f"…{v[-6:]}"


def parse_time(text: str | None, now: datetime) -> float | None:
    if not text:
        return None
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max((now - t).total_seconds() / 3600.0, 0.0)
    except ValueError:
        return None


class Unverifiable(Exception):
    """Una consulta falló o devolvió algo que no se puede interpretar: no se puede afirmar «limpio»."""


# ---------------------------------------------------------------- normalizadores (puros: reciben el JSON de cada consulta)
def _data(obj, what):
    if obj is None:
        raise Unverifiable(f"sin datos de {what}")
    if isinstance(obj, dict) and "data" in obj:       # formato de la CLI de OCI
        obj = obj["data"]
    if obj is None:
        obj = []
    if not isinstance(obj, list):
        raise Unverifiable(f"formato inesperado en {what}")
    return obj


def oci_instances(raw, now, baseline) -> list[Resource]:
    out = []
    for r in _data(raw, "instancias OCI"):
        state = str(r.get("lifecycle-state", "")).upper()
        shape = str(r.get("shape", ""))
        if state == "TERMINATED":
            continue
        cfg = r.get("shape-config") or {}
        p = PRICES.get(f"oci.instance.{shape}", None)
        ver = bool(p and p.get("verified"))
        if p and "flat" in p:
            hourly = p["flat"]
        elif p:
            hourly = (cfg.get("ocpus") or 0) * p["ocpu"] + (cfg.get("memory-in-gbs") or 0) * p["gb_ram"]
        else:
            hourly, ver = 0.0, False
        res = Resource("oci", "instancia", mask(r.get("id")), state, f"{shape} {cfg.get('ocpus','')}×OCPU {cfg.get('memory-in-gbs','')} GB".strip(),
                       hourly, parse_time(r.get("time-created"), now), "RESIDUAL", ver)
        if state in {"TERMINATING"}:
            res.status = "PENDIENTE"
        if state not in {"RUNNING", "STOPPED", "STARTING", "STOPPING", "PROVISIONING", "CREATING_IMAGE", "MOVING", "TERMINATING"}:
            res.status = "DESCONOCIDO"
        out.append(res)
    return out


def _volume(provider_kind, r, now) -> Resource | None:
    state = str(r.get("lifecycle-state", "")).upper()
    if state == "TERMINATED":
        return None
    gb = r.get("size-in-gbs") or 0
    vpu = r.get("vpus-per-gb") or 10
    p = PRICES["oci.volume_gb_month"]
    hourly = gb * (p["flat"] + vpu * p["vpu_gb_month"]) / HOURS_PER_MONTH
    res = Resource("oci", provider_kind, mask(r.get("id")), state, f"{gb} GB", hourly, parse_time(r.get("time-created"), now), "RESIDUAL", True)
    if state == "TERMINATING":
        res.status = "PENDIENTE"
    elif state not in {"AVAILABLE", "PROVISIONING", "RESTORING", "FAULTY"}:
        res.status = "DESCONOCIDO"
    return res


def oci_volumes(boot, block, now) -> list[Resource]:
    out = []
    for r in _data(boot, "volúmenes de arranque OCI"):
        x = _volume("volumen de arranque", r, now)
        if x: out.append(x)
    for r in _data(block, "volúmenes de bloque OCI"):
        x = _volume("volumen de bloque", r, now)
        if x: out.append(x)
    return out


def oci_simple(raw, now, kind, price_key, active_states, what) -> list[Resource]:
    out = []
    for r in _data(raw, what):
        state = str(r.get("lifecycle-state", "")).upper()
        if state in {"TERMINATED", "DELETED"}:
            continue
        p = PRICES[price_key]
        res = Resource("oci", kind, mask(r.get("id")), state, str(r.get("display-name") or r.get("name") or ""), p["flat"], parse_time(r.get("time-created"), now), "RESIDUAL", p["verified"])
        if state in {"TERMINATING", "DELETING"}:
            res.status = "PENDIENTE"
        elif state not in active_states:
            res.status = "DESCONOCIDO"
        out.append(res)
    return out


def oci_public_ips(raw, now) -> list[Resource]:
    out = []
    for r in _data(raw, "IP públicas OCI"):
        if str(r.get("lifetime", "")).upper() != "RESERVED":
            continue                                        # las efímeras viven y mueren con su VNIC
        state = str(r.get("lifecycle-state", "")).upper()
        if state in {"TERMINATED"}:
            continue
        p = PRICES["oci.public_ip_reserved"]
        out.append(Resource("oci", "IP pública reservada", mask(r.get("id")), state, str(r.get("display-name") or ""), p["flat"], parse_time(r.get("time-created"), now), "RESIDUAL", p["verified"]))
    return out


def aws_resources(data: dict, now, baseline) -> list[Resource]:
    out = []
    for res in (data.get("instances") or []):
        for i in (res.get("Instances") or []):
            state = (i.get("State") or {}).get("Name", "")
            if state in {"terminated", "shutting-down"}:
                continue
            name = next((t["Value"] for t in i.get("Tags", []) if t.get("Key") == "Name"), "")
            p = PRICES["aws.ec2.t3.small"] if i.get("InstanceType") == "t3.small" else dict(flat=0.0, verified=False)
            r = Resource("aws", "instancia EC2", mask(i.get("InstanceId")), state, f"{i.get('InstanceType')} {name}", p["flat"] if state == "running" else 0.0, parse_time(i.get("LaunchTime"), now), "RESIDUAL", p["verified"])
            if state == "stopped" and name in baseline.get("aws_stopped_ec2_names", []):
                r.status, r.notes = "ESPERADO", ["detenida (línea base); Academy puede reiniciarla al abrir el laboratorio"]
            elif state == "stopped":
                r.notes = ["detenida pero no está en la línea base"]
            elif state not in {"running", "pending", "stopping", "stopped"}:
                r.status = "DESCONOCIDO"
            out.append(r)
    for lb in (data.get("load_balancers") or []):
        p = PRICES["aws.alb"]
        out.append(Resource("aws", "balanceador", mask(lb.get("LoadBalancerArn")), (lb.get("State") or {}).get("Code", ""), str(lb.get("LoadBalancerName", "")), p["flat"], parse_time(lb.get("CreatedTime"), now), "RESIDUAL", p["verified"]))
    for db in (data.get("rds") or []):
        status = str(db.get("DBInstanceStatus", ""))
        multi = bool(db.get("MultiAZ"))
        p = PRICES["aws.rds.multiaz.db.t3.micro" if multi else "aws.rds.single.db.t3.micro"]
        r = Resource("aws", "RDS", mask(db.get("DBInstanceIdentifier")), status, f"{db.get('DBInstanceClass')} {'Multi-AZ' if multi else 'Single-AZ'}", p["flat"] if status in {"available", "starting", "stopping", "backing-up", "modifying"} else 0.0, None, "RESIDUAL", p["verified"])
        if status == "stopped":
            r.status = "ESPERADO"
            r.notes = ["detenida: AWS la reinicia sola a los 7 días (anotar la fecha de parada); almacenamiento y copias siguen cobrando"]
        elif status not in {"available", "starting", "stopping", "backing-up", "modifying", "stopped"}:
            r.status = "DESCONOCIDO"
        out.append(r)
    for n in (data.get("nat_gateways") or []):
        if str(n.get("State", "")) in {"deleted", "deleting"}:
            continue
        p = PRICES["aws.nat_gateway"]
        out.append(Resource("aws", "NAT Gateway", mask(n.get("NatGatewayId")), str(n.get("State", "")), "", p["flat"], parse_time(n.get("CreateTime"), now), "RESIDUAL", p["verified"]))
    for a in (data.get("addresses") or []):
        if a.get("AssociationId") or a.get("InstanceId") or a.get("NetworkInterfaceId"):
            continue
        p = PRICES["aws.eip_unassociated"]
        out.append(Resource("aws", "IP elástica sin asociar", mask(a.get("AllocationId")), "unassociated", "", p["flat"], None, "RESIDUAL", p["verified"]))
    for v in (data.get("volumes") or []):
        if str(v.get("State", "")) != "available":        # 'in-use' pertenece a una instancia; 'available' = huérfano
            continue
        p = PRICES["aws.ebs_gb_month"]
        out.append(Resource("aws", "volumen EBS huérfano", mask(v.get("VolumeId")), "available", f"{v.get('Size')} GB", (v.get("Size") or 0) * p["flat"] / HOURS_PER_MONTH, parse_time(v.get("CreateTime"), now), "RESIDUAL", p["verified"]))
    return out


# ---------------------------------------------------------------- fuentes
# Comandos de lectura permitidos en modo --live. Cualquier otro se rechaza ANTES de ejecutarse.
ALLOWED = {
    ("oci", "compute", "instance", "list"), ("oci", "bv", "boot-volume", "list"), ("oci", "bv", "volume", "list"), ("oci", "bastion", "bastion", "list"),
    ("oci", "network", "public-ip", "list"), ("oci", "network", "nat-gateway", "list"), ("oci", "lb", "load-balancer", "list"), ("oci", "iam", "availability-domain", "list"),
    ("aws", "ec2", "describe-instances"), ("aws", "elbv2", "describe-load-balancers"), ("aws", "rds", "describe-db-instances"),
    ("aws", "ec2", "describe-nat-gateways"), ("aws", "ec2", "describe-addresses"), ("aws", "ec2", "describe-volumes"),
}
FORBIDDEN_FLAGS = re.compile(r"^--(force|delete|terminate|stop|start|create|update|remove|yes|auto-approve)\b")


def guarded_run(argv: list[str], runner=None) -> object:
    key = tuple(argv[: 4 if argv[0] == "oci" else 3])
    if key not in ALLOWED:
        raise PermissionError(f"comando no permitido (solo lectura): {' '.join(argv[:4])}")
    if any(FORBIDDEN_FLAGS.match(a) for a in argv):
        raise PermissionError("bandera de modificación rechazada")
    run = runner or (lambda a: subprocess.run(a, capture_output=True, text=True, timeout=60))
    try:
        cp = run(argv)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unverifiable(f"no se pudo ejecutar «{argv[0]}»: {type(e).__name__}")
    if cp.returncode != 0:
        first = (cp.stderr or cp.stdout or "").strip().splitlines()[:1]
        raise Unverifiable(f"{' '.join(argv[:3])} devolvió código {cp.returncode}: {re.sub(r'[0-9]{12}', '<cuenta>', re.sub(r'[A-Za-z0-9+/=_-]{32,}', '<oculto>', first[0] if first else ''))[:140]}")
    if not cp.stdout.strip():
        # La CLI de OCI no imprime nada cuando una lista está vacía (código 0). La de AWS siempre imprime JSON: salida vacía = no verificable.
        if argv[0] == "oci":
            return {"data": []}
        raise Unverifiable(f"{' '.join(argv[:3])}: salida vacía")
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError:
        raise Unverifiable(f"{' '.join(argv[:3])}: salida no es JSON")


def _key(obj, name):
    if not isinstance(obj, dict) or not isinstance(obj.get(name), list):
        raise Unverifiable(f"respuesta de AWS sin la lista «{name}»")
    return obj[name]


def collect_live(args, runner=None) -> tuple[dict, list[str]]:
    """Devuelve (inventario, problemas). Cada proveedor se consulta por separado: si uno falla, el otro SE INFORMA igualmente y el veredicto global es «no verificable» (2)."""
    inv: dict = {}
    problems: list[str] = []
    if args.oci_compartment:
        try:
            c, ad = args.oci_compartment, args.oci_ad
            if not ad:
                raise Unverifiable("falta --oci-ad (las consultas de volúmenes de arranque lo exigen)")
            q = lambda *a: guarded_run(["oci", *a, "--output", "json"], runner)
            inv["oci"] = dict(
                instances=q("compute", "instance", "list", "--compartment-id", c, "--all"),
                boot=q("bv", "boot-volume", "list", "--compartment-id", c, "--availability-domain", ad, "--all"),
                block=q("bv", "volume", "list", "--compartment-id", c, "--all"),
                bastions=q("bastion", "bastion", "list", "--compartment-id", c, "--all"),
                public_ips=q("network", "public-ip", "list", "--compartment-id", c, "--scope", "REGION", "--all"),
                nat=q("network", "nat-gateway", "list", "--compartment-id", c, "--all"),
                lbs=q("lb", "load-balancer", "list", "--compartment-id", c, "--all"),
            )
        except Unverifiable as e:
            problems.append(f"OCI no verificable: {e}")
    if args.aws:
        try:
            q = lambda *a: guarded_run(["aws", *a, "--output", "json"], runner)
            inv["aws"] = dict(
                instances=_key(q("ec2", "describe-instances"), "Reservations"),
                load_balancers=_key(q("elbv2", "describe-load-balancers"), "LoadBalancers"),
                rds=_key(q("rds", "describe-db-instances"), "DBInstances"),
                nat_gateways=_key(q("ec2", "describe-nat-gateways"), "NatGateways"),
                addresses=_key(q("ec2", "describe-addresses"), "Addresses"),
                volumes=_key(q("ec2", "describe-volumes"), "Volumes"),
            )
        except Unverifiable as e:
            problems.append(f"AWS no verificable: {e}")
    if not args.oci_compartment and not args.aws:
        problems.append("modo --live sin proveedor: indica --oci-compartment/--oci-ad y/o --aws")
    return inv, problems


def evaluate(inv: dict, now: datetime, baseline: dict, max_age_min: float | None) -> tuple[list[Resource], list[str]]:
    resources: list[Resource] = []
    problems: list[str] = []
    try:
        if "oci" in inv:
            o = inv["oci"]
            resources += oci_instances(o.get("instances"), now, baseline)
            resources += oci_volumes(o.get("boot"), o.get("block"), now)
            resources += oci_simple(o.get("bastions"), now, "Bastion", "oci.bastion", {"ACTIVE", "CREATING", "UPDATING"}, "Bastion OCI")
            resources += oci_public_ips(o.get("public_ips"), now)
            resources += oci_simple(o.get("nat"), now, "NAT Gateway", "oci.nat_gateway", {"AVAILABLE", "PROVISIONING"}, "NAT OCI")
            resources += oci_simple(o.get("lbs"), now, "Balanceador", "oci.load_balancer", {"ACTIVE", "CREATING", "UPDATING"}, "balanceadores OCI")
        if "aws" in inv:
            resources += aws_resources(inv["aws"], now, baseline)
    except Unverifiable as e:
        problems.append(str(e))
    if max_age_min is not None:
        for r in resources:
            if r.status == "RESIDUAL" and r.age_h is not None and r.age_h * 60 > max_age_min and r.kind in {"instancia", "instancia EC2"}:
                r.notes.append(f"EXCEDE el tope de {max_age_min:g} min (lleva {r.age_h*60:.0f} min)")
    return resources, problems


def verdict(resources: list[Resource], problems: list[str]) -> int:
    if problems or any(r.status == "DESCONOCIDO" for r in resources):
        return 2
    if any(r.status in {"RESIDUAL", "PENDIENTE"} for r in resources):
        return 1
    return 0


def render(resources, problems, code, until_h=None, consulted=()) -> str:
    lines = ["Resultado: " + {0: "LIMPIO (sin recursos residuales)", 1: "HAY RECURSOS RESIDUALES O PENDIENTES", 2: "NO VERIFICABLE (fail-closed: no se afirma «limpio»)"}[code]]
    for prov in sorted(consulted):
        n = sum(1 for r in resources if r.provider == prov and r.status in {"RESIDUAL", "PENDIENTE", "DESCONOCIDO"})
        lines.append(f"  · {prov.upper()}: consultado; {n} recurso(s) residual(es)/pendiente(s)")
    for p in problems:
        lines.append(f"  ! {p}")
    if resources:
        lines.append(f"{'Estado':<10} {'Proveedor':<9} {'Tipo':<24} {'Id':<12} {'Situación':<14} {'USD/h':>7} {'Acum.USD':>9}  Detalle")
    burn = 0.0
    for r in resources:
        burn += r.hourly if r.status in {"RESIDUAL", "PENDIENTE", "DESCONOCIDO"} else 0.0
        acc = "-" if r.accrued is None else f"{r.accrued:.3f}"
        flag = "" if r.price_verified else " (precio sin verificar)"
        lines.append(f"{r.status:<10} {r.provider:<9} {r.kind:<24} {r.ident:<12} {r.state:<14} {r.hourly:>7.4f} {acc:>9}  {r.detail}{flag}" + ("".join(f" [{n}]" for n in r.notes)))
    lines.append(f"Gasto residual estimado{' SOLO de lo consultado (hay proveedores sin verificar: NO es el gasto total)' if problems else ''}: {burn:.4f} USD/h ({burn*24:.3f} USD/día)" + (f"; hasta el final del plazo ({until_h:g} h): {burn*until_h:.2f} USD" if until_h else ""))
    expected = [r for r in resources if r.status == "ESPERADO"]
    if expected:
        lines.append(f"Esperados (línea base, no cuentan como residuo): {len(expected)}")
    return "\n".join(lines)


def main(argv=None, runner=None, now=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--fixture"); src.add_argument("--live", action="store_true")
    ap.add_argument("--oci-compartment"); ap.add_argument("--oci-ad"); ap.add_argument("--aws", action="store_true")
    ap.add_argument("--baseline", help="JSON con recursos esperados (p. ej. {\"aws_stopped_ec2_names\": [\"nexoeventos-academy-app\"]})")
    ap.add_argument("--max-age-min", type=float, help="tope de vida de una instancia de prueba (se señala si lo excede)")
    ap.add_argument("--until-hours", type=float, help="horas hasta el fin del plazo para proyectar el gasto")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    baseline = {}
    if a.baseline:
        with open(a.baseline) as fh:
            baseline = json.load(fh)
    problems: list[str] = []
    try:
        if a.fixture:
            with open(a.fixture) as fh:
                inv = json.load(fh)
        else:
            inv, problems = collect_live(a, runner)
    except Unverifiable as e:
        inv, problems = {}, [str(e)]
    except (OSError, json.JSONDecodeError) as e:
        inv, problems = {}, [f"no se pudo leer el inventario: {type(e).__name__}"]
    resources, more = evaluate(inv, now, baseline, a.max_age_min) if inv else ([], [])
    problems += more
    if not inv and not problems:
        problems.append("inventario vacío")
    code = verdict(resources, problems)
    if a.json:
        print(json.dumps({"codigo": code, "problemas": problems, "recursos": [dict(r.__dict__, acumulado=r.accrued) for r in resources]}, ensure_ascii=False, indent=1))
    else:
        print(render(resources, problems, code, a.until_hours, consulted=tuple(inv)))
    return code


if __name__ == "__main__":
    sys.exit(main())
