#!/usr/bin/env python3
"""Comprobaciones estáticas de seguridad de infra/oci e infra/azure (sin nubes ni credenciales). Uso: python3 scripts/multicloud/check-iac-security.py"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
errors = []


def check(ok: bool, msg: str) -> None:
    print(("OK    " if ok else "FALLÓ ") + msg)
    if not ok:
        errors.append(msg)


def read(d: str) -> str:
    return "\n".join(p.read_text() for p in sorted((ROOT / d).rglob("*.tf")))


oci, az = read("infra/oci"), read("infra/azure")
oci_vars = (ROOT / "infra/oci/variables.tf").read_text()
check('access_type    = "NoPublicAccess"' in oci and 'versioning     = "Enabled"' in oci, "OCI: bucket privado y versionado")
check("assign_public_ip = false" in oci and "prohibit_public_ip_on_vnic = true" in oci, "OCI: VM y subred sin IP pública")
check("oci_core_internet_gateway" not in oci, "OCI: sin Internet Gateway")
check(not re.search(r'source\s*=\s*"0\.0\.0\.0/0"', oci), "OCI: ninguna regla de entrada abierta a Internet")
check('default     = false' in re.search(r'variable "create_recovery_vm".*?\n\}', oci_vars, re.S).group(0) and 'default     = false' in re.search(r'variable "enable_nat_gateway".*?\n\}', oci_vars, re.S).group(0), "OCI: VM y NAT desactivados por defecto")
check("manage objects" in oci and "OBJECT_CREATE" in oci and "OBJECT_DELETE" not in oci and "manage all-resources" not in oci, "OCI: política de mínimo privilegio (sin borrar ni administrar)")
check('source_address_prefix      = var.admin_cidr' in az and not re.search(r'source_address_prefix\s*=\s*"(\*|0\.0\.0\.0/0|Internet)"', az), "Azure: NSG solo desde admin_cidr")
check('!= "0.0.0.0/0"' in az, "Azure: admin_cidr no admite 0.0.0.0/0")
check('disable_password_authentication = true' in az, "Azure: VM solo con clave SSH")
check(re.search(r'variable "create_monitoring_vm".*?default\s*=\s*false', az, re.S) is not None, "Azure: VM desactivada por defecto")
check('contains(["southcentralus"' in az and 'resource_provider_registrations = "none"' in az, "Azure: regiones permitidas y sin registro automático de proveedores")
check("azurerm_consumption_budget_subscription" in az, "Azure: presupuesto con alertas")
check(not re.search(r'(password|secret|private_key|api_key)\s*=\s*"[^"]{6,}"', oci + az, re.I) and "BEGIN PRIVATE" not in oci + az, "Sin secretos ni claves en el código")
sys.exit(1 if errors else 0)
