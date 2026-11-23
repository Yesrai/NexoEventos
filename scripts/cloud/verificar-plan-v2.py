#!/usr/bin/env python3
"""Condición de parada antes de aplicar V2 (Fase C). Lee SOLO el JSON de un plan (`terraform show -json <plan>`) y exige: solo creaciones (27 con alarmas, 21 sin ellas),
0 modificaciones/destrucciones, ningún recurso de datos ni de identidad (RDS, S3, IAM, KMS, NAT...), la ÚNICA regla sobre un grupo de seguridad existente es el
ingreso 5432 desde el SG de V2, el ALB solo tiene 80 (redirección) y 443, la plantilla de lanzamiento usa la AMI esperada con IMDSv2 y disco cifrado, el health check
es /healthz (ami_includes_livez=false) o /livez (true), y el user_data no contiene secretos y sí las huellas de la CA. No usa la nube.
Uso: terraform -chdir=infra/aws-v2 show -json plan.tfplan | python3 scripts/cloud/verificar-plan-v2.py --ami ami-... [--alarmas] [--livez]
"""
import base64
import json
import re
import sys

ALLOWED = {"aws_autoscaling_group": 1, "aws_autoscaling_policy": 1, "aws_cloudwatch_dashboard": 1, "aws_launch_template": 1, "aws_lb": 1, "aws_lb_listener": 2,
           "aws_lb_target_group": 1, "aws_route_table_association": 1, "aws_security_group": 2, "aws_subnet": 1, "aws_vpc_security_group_egress_rule": 5,
           "aws_vpc_security_group_ingress_rule": 4}
ALARM_TYPES = {"aws_cloudwatch_metric_alarm": 5, "aws_autoscaling_notification": 1}
SECRET_PATTERNS = (r"postgresql(\+\w+)?://[^\s'\"]*:[^\s'\"@]+@", r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY", r"TICKET_ENCRYPTION_KEY=\S{8,}", r"SECURITY_HASH_KEY=\S{8,}")


def verify(plan: dict, ami: str, alarmas: bool = True, livez: bool = False) -> list[str]:
    problems: list[str] = []
    counts: dict[str, int] = {}
    after_by_type: dict[str, list[dict]] = {}
    for rc in plan.get("resource_changes", []):
        actions = rc["change"]["actions"]
        if actions in (["no-op"], ["read"]):
            continue
        if actions != ["create"]:
            problems.append(f"acción distinta de crear: {rc['address']} {actions}")
            continue
        counts[rc["type"]] = counts.get(rc["type"], 0) + 1
        after_by_type.setdefault(rc["type"], []).append(rc["change"]["after"] or {})
    expected = dict(ALLOWED)
    if alarmas:
        expected.update(ALARM_TYPES)
    if counts != expected:
        problems.append(f"recursos distintos de los previstos: {counts} (previsto {expected})")
    for rule in after_by_type.get("aws_vpc_security_group_ingress_rule", []):
        existing = str(rule.get("security_group_id", "")).startswith("sg-")
        if existing and (rule.get("from_port"), rule.get("to_port"), rule.get("ip_protocol")) != (5432, 5432, "tcp"):
            problems.append("regla sobre un grupo de seguridad existente distinta de 5432/tcp")
        if existing and rule.get("cidr_ipv4"):
            problems.append("la regla sobre el SG existente no debe abrir un CIDR")
    for lt in after_by_type.get("aws_launch_template", []):
        if lt.get("image_id") != ami:
            problems.append("la plantilla de lanzamiento no usa la AMI esperada")
        if (lt.get("metadata_options") or [{}])[0].get("http_tokens") != "required":
            problems.append("IMDSv2 no es obligatorio")
        if not all(b["ebs"][0].get("encrypted") in (True, "true") for b in lt.get("block_device_mappings", [])):
            problems.append("hay un disco sin cifrar")
        ud = base64.b64decode(lt.get("user_data") or "").decode("utf-8", "replace")
        if any(re.search(p, ud) for p in SECRET_PATTERNS):
            problems.append("el user_data parece contener secretos")
        if "e4ce41d069f4bdcdb714259058961ee42ed18cf2bf627a3d647aff25437d4b68" not in ud or "truststore.pki.rds.amazonaws.com" not in ud:
            problems.append("el user_data no incluye la huella ni la URL de la CA de RDS")
    for tg in after_by_type.get("aws_lb_target_group", []):
        path = tg["health_check"][0]["path"]
        if path != ("/livez" if livez else "/healthz"):
            problems.append(f"health check inesperado: {path}")
    for lb in after_by_type.get("aws_lb", []):
        if lb.get("load_balancer_type") != "application":
            problems.append("el balanceador no es de tipo application")
    listeners = {(l.get("port"), l.get("protocol")) for l in after_by_type.get("aws_lb_listener", [])}
    if listeners != {(80, "HTTP"), (443, "HTTPS")}:
        problems.append(f"listeners inesperados: {sorted(listeners)}")
    for asg in after_by_type.get("aws_autoscaling_group", []):
        if (asg.get("min_size"), asg.get("max_size"), asg.get("desired_capacity")) != (2, 3, 2):
            problems.append("capacidad del ASG distinta de 2/3/2")
    return problems


def main() -> int:
    args = sys.argv[1:]
    ami = args[args.index("--ami") + 1]
    plan = json.load(sys.stdin)
    problems = verify(plan, ami, "--sin-alarmas" not in args, "--livez" in args)
    c = {"crear": 0, "modificar": 0, "destruir": 0}
    for rc in plan.get("resource_changes", []):
        a = rc["change"]["actions"]; c["crear"] += a == ["create"]; c["modificar"] += a == ["update"]; c["destruir"] += "delete" in a
    print(f"Plan: {c['crear']} a crear, {c['modificar']} a modificar, {c['destruir']} a destruir")
    for p in problems:
        print("FALLO:", p)
    print("RESULTADO:", "CORRECTO: coincide con lo previsto" if not problems else "NO APLICAR")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
