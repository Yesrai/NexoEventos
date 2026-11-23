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

import base64
import json
import re
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
TG = "aws_lb_target_group.web"
CREATES = {
    "first": {LB, *LISTENERS, DASHBOARD, *ALB_ALARMS},
    "resume": {LB, *LISTENERS},
    "t5b": {LB, *LISTENERS},          # T5 2.º intento (variante B): como «resume» + 3 instancias + ajustes de detección del grupo de destino (ver T5B_*)
    "t5c": {LB, *LISTENERS},          # T5 2.º intento (variante C): como B pero con 6 instancias (máximo 3→7) y pool de BD acotado: un fallo afecta a 1/6 de las solicitudes
}
T5B_ALGORITHM, T5B_ATW, T5B_INTERVAL, T5B_TIMEOUT = "weighted_random", "on", 5, 3
T5_CAPACITY = {"t5b": 3, "t5c": 6}          # mín = deseada (= máximo en t5c)
T5_SCENARIOS = tuple(T5_CAPACITY)
T5C_MAX, T5C_POOL = 6, ("3", "2")          # t5c: máximo 6 (la SCP de Academy DENIEGA 7: sondeo del 23-nov 01:55Z; 6 permitido) y pool de BD 3+2 por worker (6 inst. × 2 workers × 5 = 60 ≤ 81 conexiones de la db.t3.micro)
LT = "aws_launch_template.web"
POOL_LINE = re.compile(r'^python3 - "\$tmp" "\$ENV_FILE\.new" "\$CA_FILE" "(\d+)" "(\d+)" ')
T5B_TG_ATTRS = {"load_balancing_algorithm_type", "load_balancing_anomaly_mitigation", "health_check"}
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
        elif scenario in T5_SCENARIOS and addr == TG and actions == ["update"]:
            continue
        elif scenario == "t5c" and addr == LT and actions == ["update"]:
            continue                     # único cambio permitido en la plantilla: el pool de BD en el user_data (revisado más abajo)                     # único cambio sobre el grupo de destino permitido: se revisa por atributo más abajo
        elif addr.startswith(SENSITIVE):
            errors.append(f"{addr}: recurso sensible (RDS/IAM/secretos/DNS/redes/certificados/claves/S3) con acción {'+'.join(actions)}")
        elif actions not in (["create"], ["update"]):
            errors.append(f"{addr}: acción no permitida {'+'.join(actions)}")

    created = {a for a, c in by_addr.items() if c["change"]["actions"] == ["create"]}
    if created != CREATES[scenario]:
        errors.append(f"creaciones: faltan {sorted(CREATES[scenario] - created)}; no esperadas {sorted(created - CREATES[scenario])}")

    expected_updates = {ASG} if scenario == "first" else ({ASG, *UPDATES_RESUME, *({TG, *([LT] if scenario == "t5c" else [])} & {a for a, c in by_addr.items() if c["change"]["actions"] == ["update"]})} if scenario in T5_SCENARIOS else {ASG, *UPDATES_RESUME})
    updated = {a for a, c in by_addr.items() if c["change"]["actions"] == ["update"]}
    if updated != expected_updates:
        errors.append(f"actualizaciones: faltan {sorted(expected_updates - updated)}; no esperadas {sorted(updated - expected_updates)}")

    asg = by_addr.get(ASG)
    if asg and asg["change"]["actions"] == ["update"]:
        ch, b, a = asg["change"], asg["change"]["before"], asg["change"]["after"]
        want_attrs = {"min_size", "desired_capacity"} | ({"max_size"} if scenario == "t5c" else set())
        if changed_attrs(ch) != want_attrs:
            errors.append(f"{ASG}: cambian atributos no esperados {sorted(changed_attrs(ch) ^ want_attrs)}")
        cap = T5_CAPACITY.get(scenario, 2)
        if (b.get("min_size"), b.get("desired_capacity")) != (0, 0) or (a.get("min_size"), a.get("desired_capacity")) != (cap, cap):
            errors.append(f"{ASG}: se esperaba mín/deseada 0→{cap} y es {b.get('min_size')}/{b.get('desired_capacity')}→{a.get('min_size')}/{a.get('desired_capacity')}")
        if scenario == "t5c":
            if (b.get("max_size"), a.get("max_size")) != (3, T5C_MAX):
                errors.append(f"{ASG}: en t5c el máximo debe pasar de 3 a {T5C_MAX} y es {b.get('max_size')}→{a.get('max_size')}")
        elif b.get("max_size") != a.get("max_size"):
            errors.append(f"{ASG}: cambia el máximo ({b.get('max_size')}→{a.get('max_size')})")

    if scenario in T5_SCENARIOS:
        tg = by_addr.get(TG)
        if tg and tg["change"]["actions"] == ["update"]:
            ch_, b, a = tg["change"], tg["change"]["before"] or {}, tg["change"]["after"] or {}
            extra = changed_attrs(ch_) - T5B_TG_ATTRS
            if extra:
                errors.append(f"{TG}: cambian atributos no permitidos {sorted(extra)} (solo {sorted(T5B_TG_ATTRS)})")
            if a.get("load_balancing_algorithm_type") != T5B_ALGORITHM or a.get("load_balancing_anomaly_mitigation") != T5B_ATW:
                errors.append(f"{TG}: se esperaba {T5B_ALGORITHM} con mitigación {T5B_ATW}")
            hb, ha = (b.get("health_check") or [{}])[0], (a.get("health_check") or [{}])[0]
            keys = {k for k in set(hb) | set(ha) if hb.get(k) != ha.get(k)}
            if keys - {"interval", "timeout"} or ha.get("interval") != T5B_INTERVAL or ha.get("timeout") != T5B_TIMEOUT or ha.get("unhealthy_threshold") != hb.get("unhealthy_threshold") or ha.get("path") != hb.get("path"):
                errors.append(f"{TG}: el health check solo puede cambiar intervalo→{T5B_INTERVAL} y timeout→{T5B_TIMEOUT} (umbral, ruta y protocolo iguales); cambian {sorted(keys)}")
    if scenario == "t5c":
        lt = by_addr.get(LT)
        if lt and lt["change"]["actions"] == ["update"]:
            b, a = lt["change"]["before"] or {}, lt["change"]["after"] or {}
            extra = {k for k in changed_attrs(lt["change"]) if k not in ("user_data", "latest_version", "default_version")}
            if extra:
                errors.append(f"{LT}: cambian atributos no permitidos {sorted(extra)} (solo el user_data)")
            try:
                ub, ua = base64.b64decode(b.get("user_data") or "").decode().splitlines(), base64.b64decode(a.get("user_data") or "").decode().splitlines()
            except (ValueError, UnicodeDecodeError):
                ub = ua = None
                errors.append(f"{LT}: user_data ilegible")
            if ub is not None:
                dif = [(x, y) for x, y in zip(ub, ua) if x != y]
                ok_lines = len(ub) == len(ua) and len(dif) == 1 and POOL_LINE.match(dif[0][0]) and POOL_LINE.match(dif[0][1]) and dif[0][1].replace(POOL_LINE.match(dif[0][1]).group(1) + '" "' + POOL_LINE.match(dif[0][1]).group(2), "X") == dif[0][0].replace(POOL_LINE.match(dif[0][0]).group(1) + '" "' + POOL_LINE.match(dif[0][0]).group(2), "X")
                m = POOL_LINE.match(dif[0][1]) if dif else None
                if not ok_lines or (m.group(1), m.group(2)) != T5C_POOL:
                    errors.append(f"{LT}: el user_data solo puede cambiar el pool de la BD a {T5C_POOL[0]}+{T5C_POOL[1]} (una línea; el resto idéntico)")
    if scenario in ("resume", *T5_SCENARIOS):
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
    if scenario in T5_SCENARIOS:
        print(f"PLAN REVISADO (T5 variante {scenario[-1].upper()}): 3 creaciones (ALB y 2 listeners) + ASG 0→{T5_CAPACITY[scenario]}{' (máximo 3→6; pool de BD 3+2)' if scenario == 't5c' else ''} + monitoreo dependiente del ALB + SOLO el algoritmo/ATW y el intervalo/timeout del health check del grupo de destino; 0 destrucciones, 0 sustituciones.")
    elif scenario == "first":
        print("PLAN REVISADO: exactamente 8 creaciones permitidas + 1 modificación del ASG (0→2); 0 destrucciones, 0 sustituciones.")
    else:
        print("PLAN REVISADO (reanudación): 3 creaciones (ALB y 2 listeners) + modificación del ASG (0→2) + 5 actualizaciones de monitoreo limitadas a los atributos que dependen del ALB; 0 destrucciones, 0 sustituciones.")
