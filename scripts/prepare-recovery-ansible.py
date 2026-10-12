#!/usr/bin/env python3
"""Genera runtime/inventory 0600 desde el estado temporal ya aplicado."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def protected_write(path: Path, payload: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(payload)
    os.chmod(path, 0o600)


def tfvar(path: Path, name: str) -> str:
    match = re.search(rf'^\s*{re.escape(name)}\s*=\s*"([^"]+)"\s*$', path.read_text(), re.MULTILINE)
    if not match:
        raise SystemExit(f"Falta {name} en {path.name}.")
    return match.group(1)


def resource(state: dict, resource_type: str, name: str) -> dict:
    matches = []
    for item in state.get("resources", []):
        if item.get("type") == resource_type and item.get("name") == name:
            matches.extend(instance.get("attributes", {}) for instance in item.get("instances", []))
    if len(matches) != 1:
        raise SystemExit(f"Se esperaba exactamente un {resource_type}.{name} temporal.")
    return matches[0]


def aws_value(*arguments: str) -> str:
    value = subprocess.check_output(
        ["aws", *arguments, "--output", "text"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if not value or value == "None":
        raise SystemExit("AWS no devolvió un dato requerido para el runtime protegido.")
    return value


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d{8}t\d{4}", sys.argv[1]):
        raise SystemExit("Uso: prepare-recovery-ansible.py AAAAMMDDtHHMM")
    run_id = sys.argv[1]
    state_path = ROOT / f"work/terraform-envs/recovery-{run_id}.tfstate"
    tfvars_path = ROOT / f"work/terraform-envs/recovery-{run_id}.tfvars"
    state = json.loads(state_path.read_text())
    app = resource(state, "aws_instance", "app")
    database = resource(state, "aws_db_instance", "recovery")
    instance_id = app.get("id", "")
    public_ip = aws_value(
        "ec2", "describe-instances", "--region", tfvar(tfvars_path, "aws_region"),
        "--instance-ids", instance_id,
        "--query", "Reservations[0].Instances[0].PublicIpAddress",
    )
    db_identifier = database.get("identifier", "")
    if not re.fullmatch(r"i-[0-9a-f]+", instance_id) or not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", public_ip):
        raise SystemExit("ID o IPv4 temporal no verificable en el estado.")
    expected_db = f"nexoeventos-academy-recovery-{run_id}-postgres"
    if db_identifier != expected_db:
        raise SystemExit("El identificador RDS no coincide con el RunId.")
    domain = f"nexoeventos-recovery-{public_ip.replace('.', '-')}.sslip.io"
    release_id = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    artifact = ROOT / f"work/releases/nexoeventos-{release_id}.tar.gz"
    checksum_path = artifact.with_suffix(artifact.suffix + ".sha256")
    if not artifact.is_file() or not checksum_path.is_file():
        raise SystemExit("Falta el artefacto reproducible o su checksum.")
    actual_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    recorded_digest = checksum_path.read_text().split()[0]
    if actual_digest != recorded_digest:
        raise SystemExit("El hash del artefacto no coincide.")
    account = tfvar(tfvars_path, "expected_account_id")
    region = tfvar(tfvars_path, "aws_region")
    db_endpoint = aws_value(
        "rds", "describe-db-instances", "--region", region,
        "--db-instance-identifier", db_identifier,
        "--query", "DBInstances[0].Endpoint.Address",
    )
    source_secret_arn = aws_value(
        "rds", "describe-db-instances", "--region", region,
        "--db-instance-identifier", "nexoeventos-academy-postgres",
        "--query", "DBInstances[0].MasterUserSecret.SecretArn",
    )
    bucket = f"nexoeventos-academy-{account}-{region}"
    keys_file = ROOT / f"work/recuperacion-completa/{run_id}/keys.env"
    if not keys_file.is_file() or (keys_file.stat().st_mode & 0o777) != 0o600:
        raise SystemExit("Falta el archivo 0600 de claves recuperadas.")

    runtime = ROOT / "work/recovery/runtime.yml"
    inventory = ROOT / "work/recovery/inventory.yml"
    protected_write(runtime, "\n".join([
        "---",
        "aws_profile: nexoeventos-lab",
        f"ssm_bucket_name: {bucket}",
        f"release_id: {release_id}",
        f"release_artifact: {artifact}",
        f"recovery_run_id: {run_id}",
        f"recovery_db_identifier: {db_identifier}",
        f"recovery_db_endpoint: {db_endpoint}",
        f"source_master_secret_arn: {source_secret_arn}",
        f"recovery_keys_file: {keys_file}",
        f"nexoeventos_domain: {domain}",
        "",
    ]))
    host = f"nexoeventos-academy-recovery-{run_id}-app"
    protected_write(inventory, "\n".join([
        "---", "all:", "  children:", "    nexoeventos_recovery:", "      hosts:",
        f"        {host}:", f"          ansible_host: {instance_id}",
        f"          ansible_aws_ssm_instance_id: {instance_id}",
        "          ansible_connection: amazon.aws.aws_ssm",
        f"          ansible_aws_ssm_region: {region}", "",
    ]))
    print("Runtime e inventario de recuperación creados con modo 0600; identificadores ocultos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
