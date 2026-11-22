"""Revisión estricta del plan de Terraform de V2 (scripts/v2-ops/review-plan.py): por recurso y por atributo, en los escenarios «first» y «resume».
Planes sintéticos en JSON; no toca ninguna nube. La suite simulada de `rds-window.sh chain` (scripts/v2-ops/tests) cubre además el flujo completo."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("review_plan", ROOT / "scripts/v2-ops/review-plan.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

LB = {"name": "nexoeventos-academy-v2-alb", "internal": False, "load_balancer_type": "application", "drop_invalid_header_fields": True}
HTTP = {"port": 80, "protocol": "HTTP", "default_action": [{"type": "redirect", "redirect": [{"port": "443", "protocol": "HTTPS"}]}]}
HTTPS = {"port": 443, "protocol": "HTTPS", "ssl_policy": "ELBSecurityPolicy-TLS13-1-2-2021-06", "default_action": [{"type": "forward", "redirect": []}]}
ALARMS = list(R.ALB_ALARMS)


def ch(addr, actions, before=None, after=None, unknown=None):
    return {"address": addr, "change": {"actions": actions, "before": before, "after": after if after is not None else {}, "after_unknown": unknown or {}}}


def asg(mn=2, ds=2, mx=3):
    return ch(R.ASG, ["update"], {"min_size": 0, "desired_capacity": 0, "max_size": 3}, {"min_size": mn, "desired_capacity": ds, "max_size": mx})


def plan(changes):
    return {"errored": False, "resource_changes": changes}


def first_plan():
    creates = [ch(R.LB, ["create"], None, LB), ch(R.LISTENERS[0], ["create"], None, HTTP), ch(R.LISTENERS[1], ["create"], None, HTTPS), ch(R.DASHBOARD, ["create"])]
    return plan(creates + [ch(a, ["create"]) for a in ALARMS] + [asg(), ch("aws_lb_target_group.web", ["no-op"], {}, {})])


def resume_changes():
    dash = ch(R.DASHBOARD, ["update"], {"dashboard_name": "n", "dashboard_body": "old"}, {"dashboard_name": "n"}, {"dashboard_body": True})
    dims = [ch(a, ["update"], {"threshold": 5, "dimensions": {"x": "y"}}, {"threshold": 5}, {"dimensions": True}) for a in ALARMS[1:]]
    mq = ch(ALARMS[0], ["update"], {"threshold": 1, "metric_query": [{"id": "a"}]}, {"threshold": 1, "metric_query": [{"id": "b"}]})
    return [ch(R.LB, ["create"], None, LB), ch(R.LISTENERS[0], ["create"], None, HTTP), ch(R.LISTENERS[1], ["create"], None, HTTPS), asg(), dash, mq, *dims]


def test_first_deployment_good_plan_is_accepted() -> None:
    assert R.main("first", first_plan()) == []


def test_resume_good_plan_is_accepted_and_first_plan_is_rejected_under_resume() -> None:
    assert R.main("resume", plan(resume_changes())) == []
    assert R.main("resume", first_plan())            # el plan de primer despliegue NO vale para reanudar
    assert R.main("first", plan(resume_changes()))   # ni el de reanudación para el primer despliegue


def test_nested_known_values_are_not_treated_as_unknown() -> None:
    # `after_unknown` marca [false] en listas conocidas: no debe contarse como atributo desconocido (error real detectado con el plan de AWS).
    changes = resume_changes()
    changes[-1]["change"]["after_unknown"]["alarm_actions"] = [False]
    assert R.main("resume", plan(changes)) == []


def test_any_destruction_replacement_or_sensitive_resource_is_blocked() -> None:
    base = resume_changes()
    for extra in (
        ch("aws_db_instance.postgres", ["delete"], {"id": "x"}, None),
        ch("aws_db_instance.postgres", ["update"], {"multi_az": True}, {"multi_az": False}),
        ch("aws_iam_role.x", ["create"]),
        ch("aws_secretsmanager_secret.s", ["update"], {"a": 1}, {"a": 2}),
        ch("aws_route53_record.r", ["create"]),
        ch("aws_security_group.alb", ["update"], {"a": 1}, {"a": 2}),
        ch("aws_lb_target_group.web", ["create"]),
    ):
        assert R.main("resume", plan(base + [extra])), extra["address"]
    assert R.main("resume", plan([ch(R.LB, ["delete", "create"], {"name": "x"}, LB) if c["address"] == R.LB else c for c in base]))


def test_unexpected_attributes_are_blocked_per_resource() -> None:
    def swapped(addr, new):
        return plan([new if c["address"] == addr else c for c in resume_changes()])
    assert R.main("resume", swapped(ALARMS[2], ch(ALARMS[2], ["update"], {"threshold": 5, "dimensions": {"a": "b"}}, {"threshold": 99}, {"dimensions": True})))
    assert R.main("resume", swapped(ALARMS[1], ch(ALARMS[1], ["update"], {"alarm_actions": ["t"], "dimensions": {"a": 1}}, {"alarm_actions": ["otro"]}, {"dimensions": True})))
    assert R.main("resume", swapped(R.DASHBOARD, ch(R.DASHBOARD, ["update"], {"dashboard_name": "n"}, {"dashboard_name": "otro"}, {"dashboard_body": True})))
    assert R.main("resume", swapped(R.ASG, asg(2, 2, 5)))   # el máximo no puede cambiar
    assert R.main("resume", swapped(R.ASG, asg(3, 3)))      # debe ser 0 → 2


def test_missing_or_extra_resources_are_blocked() -> None:
    base = resume_changes()
    assert R.main("resume", plan([c for c in base if c["address"] != R.LISTENERS[1]]))
    assert R.main("resume", plan([c for c in base if c["address"] != ALARMS[3]]))
    assert R.main("resume", plan(base + [ch("aws_cloudwatch_metric_alarm.nueva", ["create"])]))


def test_public_alb_and_tls13_listener_are_enforced() -> None:
    p = plan([ch(R.LB, ["create"], None, dict(LB, internal=True)) if c["address"] == R.LB else c for c in resume_changes()])
    assert R.main("resume", p)
    p = plan([ch(R.LISTENERS[1], ["create"], None, dict(HTTPS, ssl_policy="ELBSecurityPolicy-2016-08")) if c["address"] == R.LISTENERS[1] else c for c in resume_changes()])
    assert R.main("resume", p)


def test_errored_plan_and_unknown_scenario_and_cli_exit_codes() -> None:
    assert R.main("first", {"errored": True, "resource_changes": []})
    assert R.main("otro", first_plan())
    script = ROOT / "scripts/v2-ops/review-plan.py"
    ok = subprocess.run([sys.executable, str(script), "resume"], input=json.dumps(plan(resume_changes())), capture_output=True, text=True)
    bad = subprocess.run([sys.executable, str(script), "first"], input=json.dumps(plan(resume_changes())), capture_output=True, text=True)
    assert ok.returncode == 0 and "reanudación" in ok.stdout
    assert bad.returncode == 1 and bad.stdout.startswith("BLOQUEO")
