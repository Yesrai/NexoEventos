#!/usr/bin/env python3
"""Verifica, SOLO leyendo el JSON de un plan de Terraform (`terraform show -json <plan>`), que el plan de las alarmas de V1 hace exactamente lo previsto:
7 creaciones, 1 actualización (solo acciones de la alarma de CPU de la EC2), 0 destrucciones/reemplazos, ningún cambio en RDS, S3, subred, EC2 ni red, y que la
dirección de correo no aparece en el plan. Es la CONDICIÓN DE PARADA antes de aplicar. No usa la nube.
Uso: terraform -chdir=infra/aws show -json work/terraform-plans/alarmas-v1.tfplan | python3 scripts/cloud/verificar-plan-alarmas.py
"""
import json
import re
import sys

EXPECTED_CREATES = {
    "aws_sns_topic.alarms[0]", "aws_sns_topic_policy.alarms[0]", "aws_db_event_subscription.rds[0]",
    "aws_cloudwatch_metric_alarm.ec2_status_check_failed[0]", "aws_cloudwatch_metric_alarm.rds_cpu_high[0]",
    "aws_cloudwatch_metric_alarm.rds_free_storage_low[0]", "aws_cloudwatch_metric_alarm.rds_freeable_memory_low[0]",
}
EXPECTED_UPDATE = "aws_cloudwatch_metric_alarm.ec2_cpu_high"
UPDATE_ONLY_KEYS = {"alarm_actions", "ok_actions"}
FORBIDDEN_PREFIXES = ("aws_db_instance", "aws_s3_", "aws_subnet", "aws_instance", "aws_vpc", "aws_internet_gateway", "aws_route", "aws_security_group", "aws_db_subnet_group")


def verify(plan: dict) -> list[str]:
    problems: list[str] = []
    creates, updates = set(), {}
    for rc in plan.get("resource_changes", []):
        actions = rc["change"]["actions"]
        if actions in (["no-op"], ["read"]):
            continue
        address = rc["address"]
        if any(rc["type"].startswith(p) for p in FORBIDDEN_PREFIXES):
            problems.append(f"cambio en un recurso que no debe tocarse: {address} {actions}")
        if "delete" in actions:
            problems.append(f"destrucción o reemplazo: {address} {actions}")
        elif actions == ["create"]:
            creates.add(address)
        elif actions == ["update"]:
            before, after = rc["change"].get("before") or {}, rc["change"].get("after") or {}
            updates[address] = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        else:
            problems.append(f"acción inesperada: {address} {actions}")
    if creates != EXPECTED_CREATES:
        problems.append(f"creaciones distintas de las previstas: sobran {sorted(creates - EXPECTED_CREATES)}, faltan {sorted(EXPECTED_CREATES - creates)}")
    if set(updates) != {EXPECTED_UPDATE}:
        problems.append(f"actualizaciones distintas de las previstas: {sorted(updates)}")
    elif not updates[EXPECTED_UPDATE] <= UPDATE_ONLY_KEYS:
        problems.append(f"la actualización de {EXPECTED_UPDATE} cambia más que las acciones: {sorted(updates[EXPECTED_UPDATE] - UPDATE_ONLY_KEYS)}")
    if re.search(r'"endpoint"\s*:\s*"[^"]*@', json.dumps(plan)) or "aws_sns_topic_subscription" in json.dumps(plan.get("resource_changes", [])):
        problems.append("el plan contiene una suscripción o una dirección de correo (debe quedar fuera de Terraform)")
    return problems


def main() -> int:
    plan = json.load(sys.stdin)
    problems = verify(plan)
    counts = {"crear": 0, "actualizar": 0, "destruir": 0}
    for rc in plan.get("resource_changes", []):
        a = rc["change"]["actions"]
        counts["crear"] += a == ["create"]; counts["actualizar"] += a == ["update"]; counts["destruir"] += "delete" in a
    print(f"Plan: {counts['crear']} a crear, {counts['actualizar']} a actualizar, {counts['destruir']} a destruir")
    for p in problems:
        print("FALLO:", p)
    print("RESULTADO:", "CORRECTO: coincide con lo previsto" if not problems else "NO APLICAR")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
