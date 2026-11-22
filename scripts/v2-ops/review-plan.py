#!/usr/bin/env python3
"""Revisión ESTRICTA del plan de Terraform de V2 antes de aplicarlo (la usa `rds-window.sh chain`). Lee `terraform show -json <plan>` por la entrada estándar.
Uso: review-plan.py first|resume < plan.json        Salida 0 = plan aceptado ("PLAN REVISADO: …"); salida 1 = "BLOQUEO: …" (no se aplica nada).

Escenarios (ambos exigen 0 destrucciones y 0 sustituciones, y revisan CADA recurso y CADA atributo, no solo cuántos cambios hay):
  first   PRIMER DESPLIEGUE: 8 creaciones (ALB, 2 listeners, panel, 4 alarmas del ALB) + 1 modificación del ASG (mín/deseada 0→2, máx sin cambio).
  resume  REANUDACIÓN tras una limpieza de emergencia verificada (el ALB y sus listeners fueron eliminados por la API y el panel y las 4 alarmas siguen):
          3 creaciones (ALB y 2 listeners) + modificación del ASG (0→2) + 5 actualizaciones de monitoreo cuyos ÚNICOS atributos distintos son los que dependen del ALB nuevo
          (panel: dashboard_body; alarmas por destino: dimensions; alarma de capacidad: metric_query). Cualquier otro atributo, recurso o acción bloquea.
Siempre se bloquea cualquier cambio en RDS, IAM, secretos, DNS, redes, certificados, claves o S3, aunque sea una modificación menor."""
from __future__ import annotations

import json
import sys

ALB_NAME = "nexoeventos-academy-v2-alb"
ASG = "aws_autoscaling_group.web"
LB = "aws_lb.main"
LISTENERS = ("aws_lb_listener.http_redirect", "aws_lb_listener.https")
ALARM_PREFIX = "aws_cloudwatch_metric_alarm."
ALB_ALARMS = {
    "aws_cloudwatch_metric_alarm.alb_healthy_below_desired[0]": {"metric_query"},
    "aws_cloudwatch_metric_alarm.alb_latency_p95[0]": {"dimensions"},
    "aws_cloudwatch_metric_alarm.alb_target_5xx[0]": {"dimensions"},
    "aws_cloudwatch_metric_alarm.alb_unhealthy_hosts[0]": {"dimensions"},
}
DASHBOARD = "aws_cloudwatch_dashboard.v2"
CREATES = {
    "first": {LB, *LISTENERS, DASHBOARD, *ALB_ALARMS},
    "resume": {LB, *LISTENERS},
}
UPDATES_RESUME = {DASHBOARD: {"dashboard_body"}, **ALB_ALARMS}
# Recursos que NUNCA pueden cambiar en estas operaciones (RDS, IAM, secretos, DNS, redes, certificados, claves, S3).
SENSITIVE = ("aws_db_", "aws_rds", "aws_iam", "aws_secretsmanager", "aws_ssm_parameter", "aws_route53", "aws_vpc", "aws_subnet", "aws_security_group",
             "aws_route", "aws_internet_gateway", "aws_nat_gateway", "aws_network_acl", "aws_eip", "aws_acm", "aws_kms", "aws_s3", "aws_lb_target_group", "aws_launch_template")


def has_unknown(value) -> bool:
    """`after_unknown` marca con True lo que se sabrá al aplicar; en listas/mapas aparece anidado ([false] = conocido)."""
    if isinstance(value, dict):
        return any(has_unknown(v) for v in value.values())
    if isinstance(value, list):
        return any(has_unknown(v) for v in value)
    return value is True


def changed_attrs(change: dict) -> set:
    """Atributos cuyo valor cambia (conocidos) o que quedan 'desconocidos hasta aplicar'."""
    before, after = change.get("before") or {}, change.get("after") or {}
    known = {k for k, v in after.items() if v != before.get(k)}
    unknown = {k for k, v in (change.get("after_unknown") or {}).items() if has_unknown(v)}
    return known | unknown


def main(scenario: str, plan: dict) -> list[str]:
    errors: list[str] = []
    if scenario not in CREATES:
        return [f"escenario desconocido: {scenario}"]
    if plan.get("errored"):
        return ["el plan terminó con errores"]
    changes = [c for c in plan.get("resource_changes", []) if c["change"]["actions"] not in (["no-op"], ["read"])]
    by_addr = {c["address"]: c for c in changes}

    for c in changes:
        actions, addr = c["change"]["actions"], c["address"]
        if "delete" in actions:
            errors.append(f"{addr}: destrucción o sustitución ({'+'.join(actions)})")
        elif addr.startswith(SENSITIVE):
            errors.append(f"{addr}: recurso sensible (RDS/IAM/secretos/DNS/redes/certificados/claves/S3) con acción {'+'.join(actions)}")
        elif actions not in (["create"], ["update"]):
            errors.append(f"{addr}: acción no permitida {'+'.join(actions)}")

    created = {a for a, c in by_addr.items() if c["change"]["actions"] == ["create"]}
    if created != CREATES[scenario]:
        errors.append(f"creaciones: faltan {sorted(CREATES[scenario] - created)}; no esperadas {sorted(created - CREATES[scenario])}")

    expected_updates = {ASG} if scenario == "first" else {ASG, *UPDATES_RESUME}
    updated = {a for a, c in by_addr.items() if c["change"]["actions"] == ["update"]}
    if updated != expected_updates:
        errors.append(f"actualizaciones: faltan {sorted(expected_updates - updated)}; no esperadas {sorted(updated - expected_updates)}")

    asg = by_addr.get(ASG)
    if asg and asg["change"]["actions"] == ["update"]:
        ch, b, a = asg["change"], asg["change"]["before"], asg["change"]["after"]
        if changed_attrs(ch) != {"min_size", "desired_capacity"}:
            errors.append(f"{ASG}: cambian atributos no esperados {sorted(changed_attrs(ch) ^ {'min_size', 'desired_capacity'})}")
        if (b.get("min_size"), b.get("desired_capacity")) != (0, 0) or (a.get("min_size"), a.get("desired_capacity")) != (2, 2):
            errors.append(f"{ASG}: se esperaba mín/deseada 0→2 y es {b.get('min_size')}/{b.get('desired_capacity')}→{a.get('min_size')}/{a.get('desired_capacity')}")
        if b.get("max_size") != a.get("max_size"):
            errors.append(f"{ASG}: cambia el máximo ({b.get('max_size')}→{a.get('max_size')})")

    if scenario == "resume":
        for addr, allowed in UPDATES_RESUME.items():
            if addr in by_addr and by_addr[addr]["change"]["actions"] == ["update"]:
                extra = changed_attrs(by_addr[addr]["change"]) - allowed
                if extra:
                    errors.append(f"{addr}: cambian atributos no permitidos {sorted(extra)} (solo {sorted(allowed)})")

    lb = by_addr.get(LB)
    if lb and lb["change"]["actions"] == ["create"]:
        a = lb["change"]["after"] or {}
        if a.get("name") != ALB_NAME or a.get("internal") is not False or a.get("load_balancer_type") != "application" or a.get("drop_invalid_header_fields") is not True:
            errors.append(f"{LB}: atributos inesperados (nombre, público/interno, tipo o cabeceras inválidas)")
    ln = {k: by_addr.get(k) for k in LISTENERS}
    if ln[LISTENERS[0]] and ln[LISTENERS[0]]["change"]["actions"] == ["create"]:
        a = ln[LISTENERS[0]]["change"]["after"] or {}
        acts = a.get("default_action") or [{}]
        redirect = (acts[0].get("redirect") or [{}])[0]
        if (a.get("port"), a.get("protocol"), acts[0].get("type"), str(redirect.get("port")), redirect.get("protocol")) != (80, "HTTP", "redirect", "443", "HTTPS"):
            errors.append(f"{LISTENERS[0]}: debe redirigir 80 → 443 HTTPS")
    if ln[LISTENERS[1]] and ln[LISTENERS[1]]["change"]["actions"] == ["create"]:
        a = ln[LISTENERS[1]]["change"]["after"] or {}
        acts = a.get("default_action") or [{}]
        if (a.get("port"), a.get("protocol"), acts[0].get("type")) != (443, "HTTPS", "forward") or not str(a.get("ssl_policy") or "").startswith("ELBSecurityPolicy-TLS13"):
            errors.append(f"{LISTENERS[1]}: debe ser 443 HTTPS con política TLS 1.3 y reenviar al grupo de destino")
    return errors


if __name__ == "__main__":
    scenario = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("BLOQUEO: no se pudo leer el plan")
        sys.exit(1)
    problems = main(scenario, data)
    if problems:
        print("BLOQUEO: " + " | ".join(problems))
        sys.exit(1)
    if scenario == "first":
        print("PLAN REVISADO: exactamente 8 creaciones permitidas + 1 modificación del ASG (0→2); 0 destrucciones, 0 sustituciones.")
    else:
        print("PLAN REVISADO (reanudación): 3 creaciones (ALB y 2 listeners) + modificación del ASG (0→2) + 5 actualizaciones de monitoreo limitadas a los atributos que dependen del ALB; 0 destrucciones, 0 sustituciones.")
