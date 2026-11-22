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
    ap.add_argument("--mode", choices=("create", "teardown"), required=True); ap.add_argument("--plan-json", required=True)
    ap.add_argument("--shape", default="VM.Standard.E5.Flex"); ap.add_argument("--max-ocpus", type=float, default=2); ap.add_argument("--max-memory-gb", type=float, default=16)
    a = ap.parse_args(argv)
    try:
        plan = json.load(open(a.plan_json))
    except (OSError, ValueError):
        print("No se pudo leer el JSON del plan.", file=sys.stderr); return 2
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
