#!/usr/bin/env python3
"""Reconstruye el tfvars ignorado de Academy desde el estado real existente.

No consulta ni imprime secretos. Falla si el estado no contiene exactamente los
recursos esperados o si sus nombres no corresponden a NexoEventos Academy.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "work/terraform-state/academy-current/terraform.tfstate"
DESTINATION = ROOT / "work/terraform-envs/academy.tfvars"


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def attributes(state: dict, resource_type: str, name: str) -> dict:
    matches = [
        instance["attributes"]
        for resource in state.get("resources", [])
        if resource.get("type") == resource_type and resource.get("name") == name
        for instance in resource.get("instances", [])
        if "attributes" in instance
    ]
    if len(matches) != 1:
        fail(f"se esperaba una instancia de {resource_type}.{name}; hay {len(matches)}")
    return matches[0]


def hcl_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def main() -> None:
    if not STATE.is_file():
        fail(f"no existe el estado real esperado: {STATE}")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if not state.get("lineage") or not isinstance(state.get("serial"), int):
        fail("el estado carece de lineage o serial")

    caller = attributes(state, "aws_caller_identity", "current")
    profile = attributes(state, "aws_iam_instance_profile", "app")
    vpc = attributes(state, "aws_vpc", "main")
    public = attributes(state, "aws_subnet", "public_a")
    db_a = attributes(state, "aws_subnet", "db_private_a")
    db_b = attributes(state, "aws_subnet", "db_private_b")
    instance = attributes(state, "aws_instance", "app")
    database = attributes(state, "aws_db_instance", "postgres")
    api_logs = attributes(state, "aws_cloudwatch_log_group", "api")

    expected_names = {
        instance.get("tags", {}).get("Name"): "nexoeventos-academy-app",
        database.get("tags", {}).get("Name"): "nexoeventos-academy-postgres",
        vpc.get("tags", {}).get("Name"): "nexoeventos-academy-vpc",
    }
    if any(actual != expected for actual, expected in expected_names.items()):
        fail("los nombres del estado no corresponden a nexoeventos-academy")

    account_id = str(caller.get("account_id", ""))
    region = str(instance.get("region", ""))
    root_devices = instance.get("root_block_device") or []
    if not (account_id.isdigit() and len(account_id) == 12):
        fail("el estado no contiene una cuenta AWS valida")
    if region != database.get("region") or region != api_logs.get("region"):
        fail("las regiones de EC2, RDS y CloudWatch no coinciden")
    if len(root_devices) != 1:
        fail("no se pudo identificar un unico volumen raiz de EC2")

    values: list[tuple[str, object]] = [
        ("aws_region", region),
        ("project_slug", "nexoeventos"),
        ("environment", "academy"),
        ("expected_account_id", account_id),
        ("vpc_cidr", vpc["cidr_block"]),
        ("public_a_cidr", public["cidr_block"]),
        ("db_private_a_cidr", db_a["cidr_block"]),
        ("db_private_b_cidr", db_b["cidr_block"]),
        ("admin_cidr", ""),
        ("ec2_instance_type", instance["instance_type"]),
        ("ec2_root_volume_gib", root_devices[0]["volume_size"]),
        ("instance_profile_name", profile["name"]),
        ("db_instance_class", database["instance_class"]),
        ("db_allocated_storage_gib", database["allocated_storage"]),
        ("backup_retention_days", database["backup_retention_period"]),
        ("log_retention_days", api_logs["retention_in_days"]),
        ("final_snapshot_identifier", database["final_snapshot_identifier"]),
    ]
    lines = [
        "# Reconstruido desde el estado Terraform real academy-current.",
        f"# lineage presente; serial {state['serial']}. Archivo ignorado por Git.",
    ]
    for key, value in values:
        rendered = hcl_string(value) if isinstance(value, str) else str(value)
        lines.append(f"{key} = {rendered}")
    content = "\n".join(lines) + "\n"

    DESTINATION.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".academy.", dir=DESTINATION.parent)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, DESTINATION)
        os.chmod(DESTINATION, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(
        "academy.tfvars reconstruido sin mostrar valores; "
        f"estado serial {state['serial']}, modo 0600."
    )


if __name__ == "__main__":
    main()
