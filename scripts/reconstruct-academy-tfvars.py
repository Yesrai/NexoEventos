#!/usr/bin/env python3
"""Reconstruye el tfvars ignorado de Academy desde el estado real existente.

No consulta ni imprime secretos. Falla si el estado no contiene exactamente los
recursos esperados o si sus nombres no corresponden a NexoEventos Academy.

Seguridad de la RDS (corregido el 6-nov-2026): ya NO hay valores fijos para la base de datos.
- `db_multi_az` y `db_apply_immediately` se leen del estado real (nunca se omiten: el valor por
  defecto de la variable es false y quitaría Multi-AZ).
- `db_max_allocated_storage_gib` es el MAYOR entre el valor del estado y el del archivo de destino
  actual (el estado puede ir por detrás de AWS, p. ej. si el máximo se subió con la CLI); así una
  regeneración nunca desactiva ni reduce el autoescalado por accidente.
- Si el archivo actual tiene Multi-AZ activo y el estado dice lo contrario, se aborta
  (salvo --allow-downgrade explícito).
Interruptores opcionales (corregido el 6-nov-2026): `enable_alarms` y `enable_cloudtrail` se deducen de si el estado
contiene `aws_sns_topic.alarms` / `aws_cloudtrail`. Omitir `enable_alarms = true` haría que un plan de V1 proponga
DESTRUIR el tema SNS, las alarmas y la suscripción a eventos de RDS (hallazgo del plan de solo lectura del 6-nov).
Opciones: --state RUTA, --dest RUTA (por defecto, las reales) y --dry-run (muestra el resultado
con la cuenta enmascarada y no escribe nada).
"""

from __future__ import annotations

import argparse
import json
import os
import re
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


def render(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return hcl_string(value)
    return str(value)


def existing_value(path: Path, key: str) -> object | None:
    """Lee un valor simple (número o booleano) de un tfvars existente; None si no está."""
    if not path.is_file():
        return None
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*(true|false|\d+)\s*(?:#.*)?$", path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        return None
    raw = match.group(1)
    return raw == "true" if raw in ("true", "false") else int(raw)


def has_resource(state: dict, resource_type: str, name: str | None = None) -> bool:
    return any(r.get("type") == resource_type and (name is None or r.get("name") == name) and r.get("instances")
               and r.get("mode", "managed") == "managed" for r in state.get("resources", []))


def optional_switches(state: dict, destination: Path, allow_downgrade: bool) -> list[tuple[str, object]]:
    """Interruptores que el estado ya tiene activos: si no se declaran, el valor por defecto (false) destruiría esos recursos."""
    switches = [
        ("enable_alarms", has_resource(state, "aws_sns_topic", "alarms")),
        ("enable_cloudtrail", has_resource(state, "aws_cloudtrail")),
    ]
    for key, value in switches:
        if existing_value(destination, key) is True and value is False and not allow_downgrade:
            fail(f"el archivo actual declara {key} = true pero el estado no tiene esos recursos; "
                 "no se sobrescribe (usa --allow-downgrade solo si es lo que se quiere)")
    return switches


def rds_settings(database: dict, destination: Path, allow_downgrade: bool) -> list[tuple[str, object]]:
    multi_az = database.get("multi_az")
    if not isinstance(multi_az, bool):
        fail("el estado no indica de forma clara si la RDS es Multi-AZ; no se genera nada")
    previous_multi_az = existing_value(destination, "db_multi_az")
    if previous_multi_az is True and multi_az is False and not allow_downgrade:
        fail("el archivo actual declara Multi-AZ activo pero el estado dice lo contrario; "
             "no se sobrescribe (usa --allow-downgrade solo si eso es lo que se quiere)")
    apply_immediately = database.get("apply_immediately")
    if not isinstance(apply_immediately, bool):
        apply_immediately = False
    state_max = database.get("max_allocated_storage") or 0
    previous_max = existing_value(destination, "db_max_allocated_storage_gib")
    previous_max = previous_max if isinstance(previous_max, int) and not isinstance(previous_max, bool) else 0
    chosen_max = max(int(state_max), previous_max)
    if previous_max > int(state_max):
        print(f"AVISO: el estado dice máximo {state_max} GiB pero el archivo actual dice {previous_max}; se conserva {chosen_max} (el estado puede ir por detrás de AWS).", file=sys.stderr)
    allocated = int(database["allocated_storage"])
    if chosen_max not in (0, allocated) and chosen_max < -(-allocated * 11 // 10):
        fail(f"db_max_allocated_storage_gib={chosen_max} incumple el margen mínimo del 10 % sobre {allocated} GiB")
    return [
        ("db_max_allocated_storage_gib", chosen_max),
        ("db_multi_az", multi_az),
        ("db_apply_immediately", apply_immediately),
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Reconstruye work/terraform-envs/academy.tfvars desde el estado real.")
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--dest", type=Path, default=DESTINATION)
    parser.add_argument("--dry-run", action="store_true", help="muestra el resultado (cuenta enmascarada) sin escribir")
    parser.add_argument("--allow-downgrade", action="store_true", help="permite pasar de Multi-AZ activo a inactivo")
    args = parser.parse_args(argv)
    state_path, destination = args.state, args.dest
    if not state_path.is_file():
        fail(f"no existe el estado real esperado: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
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
        ("ec2_ami_id", instance["ami"]),
        ("ec2_root_volume_gib", root_devices[0]["volume_size"]),
        ("instance_profile_name", profile["name"]),
        ("db_instance_class", database["instance_class"]),
        ("db_allocated_storage_gib", database["allocated_storage"]),
        *rds_settings(database, destination, args.allow_downgrade),
        *optional_switches(state, destination, args.allow_downgrade),
        ("backup_retention_days", database["backup_retention_period"]),
        ("log_retention_days", api_logs["retention_in_days"]),
        ("final_snapshot_identifier", database["final_snapshot_identifier"]),
    ]
    lines = [
        "# Reconstruido desde el estado Terraform real academy-current.",
        f"# lineage presente; serial {state['serial']}. Archivo ignorado por Git.",
    ]
    for key, value in values:
        lines.append(f"{key} = {render(value)}")
    content = "\n".join(lines) + "\n"

    if args.dry_run:
        print(content.replace(account_id, "<cuenta>"), end="")
        print("(--dry-run) No se escribió ningún archivo.")
        return

    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".academy.", dir=destination.parent)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, destination)
        os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(
        "academy.tfvars reconstruido sin mostrar valores; "
        f"estado serial {state['serial']}, modo 0600."
    )


if __name__ == "__main__":
    main()
