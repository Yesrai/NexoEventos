#!/usr/bin/env python3
"""Crea tfvars protegidos del ensayo desde fuentes locales ya comprobadas."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_TFVARS = ROOT / "work/terraform-envs/academy.tfvars"
SOURCE_STATE = ROOT / "work/terraform-state/academy-current/terraform.tfstate"


def tfvar(text: str, name: str) -> str:
    match = re.search(rf'^\s*{re.escape(name)}\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if not match:
        raise SystemExit(f"Falta {name} en academy.tfvars protegido.")
    return match.group(1)


def resource_instances(state: dict, resource_type: str, name: str) -> list[dict]:
    for resource in state.get("resources", []):
        if resource.get("type") == resource_type and resource.get("name") == name:
            return [item.get("attributes", {}) for item in resource.get("instances", [])]
    return []


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d{8}t\d{4}", sys.argv[1]):
        raise SystemExit("Uso: prepare-recovery-runtime.py AAAAMMDDtHHMM")
    run_id = sys.argv[1]
    source_text = SOURCE_TFVARS.read_text()
    state = json.loads(SOURCE_STATE.read_text())
    account = tfvar(source_text, "expected_account_id")
    region = tfvar(source_text, "aws_region")
    if not re.fullmatch(r"\d{12}", account) or region != "us-east-1":
        raise SystemExit("Cuenta o región fuente fuera del alcance Academy esperado.")
    instances = resource_instances(state, "aws_instance", "app")
    if len(instances) != 1:
        raise SystemExit("El estado debe contener exactamente una aws_instance.app.")
    ami = instances[0].get("ami", "")
    profile = instances[0].get("iam_instance_profile", "")
    if not re.fullmatch(r"ami-[0-9a-f]{8,17}", ami) or not profile:
        raise SystemExit("AMI o perfil de instancia no verificables en el estado fuente.")

    destination = ROOT / f"work/terraform-envs/recovery-{run_id}.tfvars"
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = (
        f'aws_region = "{region}"\n'
        f'expected_account_id = "{account}"\n'
        'source_prefix = "nexoeventos-academy"\n'
        f'run_id = "{run_id}"\n'
        f'ec2_ami_id = "{ami}"\n'
        f'instance_profile_name = "{profile}"\n'
        'ec2_instance_type = "t3.small"\n'
        'db_instance_class = "db.t3.micro"\n'
    )
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(payload)
    os.chmod(destination, 0o600)
    print(f"Configuración protegida creada: work/terraform-envs/{destination.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
