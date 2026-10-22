#!/usr/bin/env python3
"""Coherencia de docs/multicloud con las redes y estados reales (solo lectura local, sin nubes).
Comprueba: CIDR de AWS (variables Terraform y, si existe, el estado local), CIDR propuestos de OCI/Azure (variables por defecto), no solape entre nubes,
subredes dentro de su red, rutas de estados/raíces Terraform citadas, etapas 0–11 contiguas y región de Azure permitida. Uso: python3 scripts/multicloud/check-coherence.py"""
import ipaddress
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
errors: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("OK    " if ok else "FALLÓ ") + msg)
    if not ok:
        errors.append(msg)


def default(file: str, name: str) -> str:
    text = (ROOT / file).read_text()
    m = re.search(rf'variable "{name}" \{{(.*?)\n\}}', text, re.S)
    return re.search(r'default\s*=\s*"([^"]*)"', m.group(1)).group(1)


net = lambda c: ipaddress.ip_network(c)  # noqa: E731
aws = {"vpc": default("infra/aws/variables.tf", "vpc_cidr"), "public_a": default("infra/aws/variables.tf", "public_a_cidr"),
       "db_a": default("infra/aws/variables.tf", "db_private_a_cidr"), "db_b": default("infra/aws/variables.tf", "db_private_b_cidr"),
       "public_b_v2": default("infra/aws-v2/variables.tf", "public_b_cidr")}
oci = {"vcn": default("infra/oci/variables.tf", "vcn_cidr"), "subnet": default("infra/oci/variables.tf", "private_subnet_cidr")}
az = {"vnet": default("infra/azure/variables.tf", "vnet_cidr"), "subnet": default("infra/azure/variables.tf", "subnet_cidr")}

# 1) El estado real de V1 (si existe localmente) coincide con las variables
state = ROOT / "work" / "terraform-state" / "academy-current" / "terraform.tfstate"
if state.exists():
    found = {}
    for r in json.loads(state.read_text())["resources"]:
        for i in r.get("instances", []):
            a = i["attributes"]
            if r["type"] == "aws_vpc" and r["mode"] == "managed":
                found["vpc"] = a["cidr_block"]
            if r["type"] == "aws_subnet":
                found[{"nexoeventos-academy-public-a": "public_a", "nexoeventos-academy-db-private-a": "db_a", "nexoeventos-academy-db-private-b": "db_b"}.get(a["tags"].get("Name"), "?")] = a["cidr_block"]
    for k in ("vpc", "public_a", "db_a", "db_b"):
        check(found.get(k) == aws[k], f"AWS {k}: estado Terraform = variables ({aws[k]})")
else:
    print("AVISO el estado local de V1 no está disponible (CI): se valida solo contra variables")

# 2) Subredes dentro de su red y sin solape entre nubes
for label, (parent, kids) in {"AWS": (aws["vpc"], [aws[k] for k in ("public_a", "db_a", "db_b", "public_b_v2")]), "OCI": (oci["vcn"], [oci["subnet"]]), "Azure": (az["vnet"], [az["subnet"]])}.items():
    check(all(net(k).subnet_of(net(parent)) for k in kids), f"{label}: subredes dentro de {parent}")
check(len({aws["public_a"], aws["db_a"], aws["db_b"], aws["public_b_v2"]}) == 4 and not any(net(a).overlaps(net(b)) for a in (aws["public_a"], aws["db_a"], aws["db_b"]) for b in (aws["public_b_v2"],)), "AWS: subredes sin solape (incluida public-b de V2)")
vpcs = {"AWS": aws["vpc"], "OCI": oci["vcn"], "Azure": az["vnet"]}
check(not any(net(vpcs[a]).overlaps(net(vpcs[b])) for a in vpcs for b in vpcs if a < b), f"Sin solape entre nubes: {vpcs}")

# 3) La documentación cita exactamente esos CIDR y rutas existentes
docs = "\n".join(p.read_text() for p in (ROOT / "docs" / "multicloud").glob("*.md"))
for c in (aws["vpc"], aws["public_a"], aws["db_a"], aws["db_b"], aws["public_b_v2"], oci["vcn"], oci["subnet"], az["vnet"], az["subnet"]):
    check(c in docs, f"docs/multicloud cita {c}")
cited = set(re.findall(r"\b10\.\d+\.\d+\.\d+/\d+\b", docs))
known = {aws["vpc"], aws["public_a"], aws["db_a"], aws["db_b"], aws["public_b_v2"], oci["vcn"], oci["subnet"], az["vnet"], az["subnet"]}
check(cited <= known, f"Todos los CIDR citados existen en Terraform/variables (sin inventados): sobran {sorted(cited - known)}")
for d in ("infra/aws", "infra/aws-v2", "infra/aws-recovery", "infra/oci", "infra/azure"):
    check((ROOT / d).is_dir() and (d in docs or d.split("/")[-1] in docs), f"Raíz Terraform citada y existente: {d}")

# 4) Etapas 0–11 contiguas y región de Azure permitida
plan = (ROOT / "docs" / "multicloud" / "04-plan-implementacion.md").read_text()
stages = [int(m) for m in re.findall(r"^\| (\d+) \|", plan, re.M)]
check(stages == list(range(12)), f"Plan: etapas {stages[0]}–{stages[-1]} contiguas ({len(stages)})")
allowed = {"southcentralus", "mexicocentral", "westus3", "canadacentral", "centralus"}
check(default("infra/azure/variables.tf", "azure_region") in allowed and all(r in (ROOT / "docs" / "diagnostico-entorno.md").read_text() for r in allowed), "Región por defecto de Azure dentro de la directiva documentada")
sys.exit(1 if errors else 0)
