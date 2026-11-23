#!/usr/bin/env python3
"""Guarda de seguridad para un `terraform plan` de la recuperación en OCI (solo LEE el JSON de `terraform show -json <plan>`; no ejecuta Terraform ni toca la nube).
Falla (código 1) si el plan contiene cualquier cambio fuera de la lista blanca de recursos TEMPORALES de la prueba, cualquier destrucción en modo `create`, cualquier alta en modo
`teardown`, una VM con IP pública o forma/tamaño inesperados, o una regla de entrada abierta a Internet.
  create:   permite SOLO  alta de instancia, alta de Bastion, alta de la regla NSG HTTPS (misma subred) y modificación de la lista de seguridad por defecto (salida 443 dentro de la subred).
  teardown: permite SOLO  baja de esos tres recursos y la modificación de la lista de seguridad (se retira la salida 443). VCN, subred, NSG, Service Gateway, bucket e IAM NO se tocan jamás.
Uso: plan_guard.py --mode create|teardown --plan-json plan.json [--max-ocpus 2] [--max-memory-gb 16] [--shape VM.Standard.E5.Flex]"""
from __future__ import annotations

import argparse
import json
import sys

TEMP = {
    "module.recovery.oci_core_instance.recovery[0]",
    "module.recovery.oci_bastion_bastion.this[0]",
    "module.network.oci_core_network_security_group_security_rule.https_from_subnet[0]",
}
SECLIST = "module.network.oci_core_default_security_list.lockdown"
# ---- Modos «-public» (T3: entrada HTTPS de PRUEBA). Los modos create/teardown de arriba NO cambian y siguen prohibiendo IP pública.
PUB = "module.public_entry."
PUBLIC_SET = {PUB + "oci_core_internet_gateway.this[0]", PUB + "oci_core_route_table.public[0]", PUB + "oci_core_security_list.public[0]", PUB + "oci_core_subnet.public[0]",
              PUB + "oci_core_network_security_group.public[0]", PUB + "oci_core_network_security_group_security_rule.ssh_from_bastion_subnet[0]",
              PUB + "oci_core_network_security_group_security_rule.https_out[0]"}
HTTPS_IN = PUB + 'oci_core_network_security_group_security_rule.https_in["'
INST_ADDR, BAS_ADDR = "module.recovery.oci_core_instance.recovery[0]", "module.recovery.oci_bastion_bastion.this[0]"
ALLOWED_SHAPES = ("VM.Standard.E2.1.Micro", "VM.Standard.A1.Flex")        # solo Always Free: E5/E4 (de pago) NO se admiten
import re as _re
_SLASH32 = _re.compile(r"^\d{1,3}(\.\d{1,3}){3}/32$")


def _port(r):
    t = (r.get("tcp_options") or [{}])[0].get("destination_port_range") or [{}]
    return t[0].get("min"), t[0].get("max")


def check_public(plan: dict, mode: str, *, shapes=ALLOWED_SHAPES, max_ocpus: float = 2, max_mem: float = 12, max_https_sources: int = 4) -> list[str]:
    """create-public: SOLO altas de la VM, el Bastion y los recursos del módulo public_entry, con reglas mínimas. teardown-public: SOLO bajas de esos mismos recursos."""
    errs: list[str] = []; creating = mode == "create-public"; ch = {c["address"]: c for c in plan.get("resource_changes", [])}
    n_in = 0; subnet_cidr = ((ch.get(PUB + "oci_core_subnet.public[0]") or {}).get("change", {}).get("after") or {}).get("cidr_block")
    for addr, c in ch.items():
        acts = c["change"]["actions"]
        if acts in (["no-op"], ["read"]): continue
        is_in = addr.startswith(HTTPS_IN); known = addr in PUBLIC_SET or addr in (INST_ADDR, BAS_ADDR) or is_in
        if not known: errs.append(f"cambio FUERA de la lista blanca: {addr} {acts}"); continue
        if creating and acts != ["create"]: errs.append(f"{addr}: en create-public solo se permite el alta (acciones {acts})"); continue
        if not creating and acts != ["delete"]: errs.append(f"{addr}: en teardown-public solo se permite la baja (acciones {acts})"); continue
        if not creating: continue
        a = c["change"].get("after") or {}
        if addr == INST_ADDR:
            if a.get("shape") not in shapes: errs.append(f"forma NO permitida (solo Always Free {', '.join(shapes)}): {a.get('shape')}")
            sc = (a.get("shape_config") or [{}])[0]
            if a.get("shape") == "VM.Standard.A1.Flex" and (float(sc.get("ocpus") or 0) > max_ocpus or float(sc.get("memory_in_gbs") or 0) > max_mem): errs.append(f"A1 por encima del tope ({sc.get('ocpus')} OCPU, {sc.get('memory_in_gbs')} GB)")
            if str((a.get("create_vnic_details") or [{}])[0].get("assign_public_ip")).lower() != "true": errs.append("la VM de la entrada pública debe tener IP pública (si no, no hay entrada)")
        elif addr == BAS_ADDR:
            lst = a.get("client_cidr_block_allow_list") or []
            if len(lst) != 1 or not _SLASH32.match(str(lst[0])): errs.append(f"el Bastion debe admitir exactamente una IP /32: {lst}")
        elif is_in:
            n_in += 1
            if a.get("direction") != "INGRESS" or str(a.get("protocol")) != "6" or not _SLASH32.match(str(a.get("source", ""))) or _port(a) != (443, 443): errs.append(f"regla de entrada no válida (solo TCP 443 desde un /32): {addr} source={a.get('source')} puertos={_port(a)}")
        elif addr.endswith("ssh_from_bastion_subnet[0]"):
            if a.get("direction") != "INGRESS" or _port(a) != (22, 22) or (subnet_cidr and a.get("source") != subnet_cidr): errs.append("SSH solo desde la propia subred pública (endpoint de Bastion), puerto 22")
        elif addr.endswith("https_out[0]"):
            if a.get("direction") != "EGRESS" or _port(a) != (443, 443): errs.append("la única salida permitida es HTTPS (443)")
        elif addr.endswith("security_list.public[0]"):
            if a.get("ingress_security_rules"): errs.append("la lista de seguridad pública no puede tener reglas de entrada")
            eg = a.get("egress_security_rules") or []
            if len(eg) != 1 or eg[0].get("destination") != subnet_cidr or (eg[0].get("tcp_options") or [{}])[0].get("min") != 22: errs.append("la lista de seguridad pública solo puede permitir SSH hacia su propia subred")
        elif addr.endswith("subnet.public[0]"):
            if a.get("prohibit_public_ip_on_vnic") is not False: errs.append("la subred pública debe admitir IP pública (prohibit_public_ip_on_vnic=false)")
    if creating:
        if n_in == 0: errs.append("no hay ninguna regla HTTPS de entrada (se exige al menos un origen /32)")
        if n_in > max_https_sources: errs.append(f"demasiados orígenes HTTPS ({n_in} > {max_https_sources})")
        for must in (INST_ADDR, BAS_ADDR, *sorted(PUBLIC_SET)):
            if must not in ch or "create" not in ch[must]["change"]["actions"]: errs.append(f"falta el alta esperada: {must}")
    return errs


def check(plan: dict, mode: str, *, shape: str, max_ocpus: float, max_mem: float) -> list[str]:
    errs: list[str] = []
    for c in plan.get("resource_changes", []):
        acts, addr = c["change"]["actions"], c["address"]
        if acts == ["no-op"] or acts == ["read"]:
            continue
        creates, deletes, updates = "create" in acts, "delete" in acts, acts == ["update"]
        if addr == SECLIST:
            if not updates:
                errs.append(f"{addr}: solo se permite una modificación in situ (acciones {acts})")
            continue
        if addr not in TEMP:
            errs.append(f"cambio FUERA de la lista blanca: {addr} {acts}")
            continue
        if mode == "create" and (deletes or not creates):
            errs.append(f"{addr}: en modo create solo se permite el alta (acciones {acts})")
        if mode == "teardown" and (creates or not deletes or "create" in acts):
            errs.append(f"{addr}: en modo teardown solo se permite la baja (acciones {acts})")
        after = c["change"].get("after") or {}
        if addr.endswith("oci_core_instance.recovery[0]") and mode == "create":
            if after.get("shape") != shape:
                errs.append(f"forma inesperada: {after.get('shape')}")
            sc = (after.get("shape_config") or [{}])[0]
            if float(sc.get("ocpus") or 0) > max_ocpus or float(sc.get("memory_in_gbs") or 0) > max_mem:
                errs.append(f"tamaño por encima del tope ({sc.get('ocpus')} OCPU, {sc.get('memory_in_gbs')} GB)")
            vn = (after.get("create_vnic_details") or [{}])[0]
            if str(vn.get("assign_public_ip")).lower() != "false":
                errs.append("la VM tendría IP pública")
        if addr.endswith("https_from_subnet[0]") and mode == "create":
            if after.get("source") in ("0.0.0.0/0", "::/0") or after.get("direction") != "INGRESS" or not str(after.get("source", "")).startswith("10."):
                errs.append("la regla HTTPS no está limitada a la subred privada")
        if addr == SECLIST:
            pass
    sl = next((c for c in plan.get("resource_changes", []) if c["address"] == SECLIST), None)
    if sl and mode == "create":
        for r in (sl["change"].get("after") or {}).get("ingress_security_rules", []) or []:
            errs.append("la lista de seguridad tendría una regla de ENTRADA")
        for r in (sl["change"].get("after") or {}).get("egress_security_rules", []) or []:
            if r.get("destination") not in ("10.30.1.0/24",) and r.get("destination_type") != "SERVICE_CIDR_BLOCK":
                errs.append(f"salida hacia un destino inesperado: {r.get('destination')}")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=("create", "teardown", "create-public", "teardown-public"), required=True); ap.add_argument("--plan-json", required=True)
    ap.add_argument("--shape", default="VM.Standard.E5.Flex"); ap.add_argument("--max-ocpus", type=float, default=2); ap.add_argument("--max-memory-gb", type=float, default=16)
    a = ap.parse_args(argv)
    try:
        plan = json.load(open(a.plan_json))
    except (OSError, ValueError):
        print("No se pudo leer el JSON del plan.", file=sys.stderr); return 2
    if a.mode.endswith("-public"):
        errs = check_public(plan, a.mode, max_ocpus=a.max_ocpus if a.max_ocpus != 2 else 2, max_mem=a.max_memory_gb if a.max_memory_gb != 16 else 12)
    else:
        errs = check(plan, a.mode, shape=a.shape, max_ocpus=a.max_ocpus, max_mem=a.max_memory_gb)
    n = sum(1 for c in plan.get("resource_changes", []) if c["change"]["actions"] not in (["no-op"], ["read"]))
    if errs:
        print(f"PLAN RECHAZADO ({a.mode}): {len(errs)} problema(s)")
        for e in errs: print("  -", e)
        return 1
    print(f"OK    plan {a.mode} dentro de la lista blanca: {n} cambio(s), 0 fuera de los recursos temporales, 0 destrucciones ajenas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
