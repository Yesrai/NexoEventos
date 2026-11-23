"""Controles de seguridad del despliegue de las alarmas de V1: filtro de saneamiento, entrada oculta del correo y verificación del plan. Sin nube."""
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verify_plan", ROOT / "scripts/cloud/verificar-plan-alarmas.py")
VP = importlib.util.module_from_spec(spec)
spec.loader.exec_module(VP)


def test_mask_filter_hides_public_ips_account_ids_arns_ids_and_emails_without_breaking_versions() -> None:
    text = "ip=203.0.113.45 priv=10.0.1.5 arn:aws:iam::123456789012:role/x i-0123456789abcdef0 cuenta 123456789012 yo@correo.com usuario user1234567=Nombre_Apellido v3.0.22 1.2.3"
    out = subprocess.run([str(ROOT / "scripts/cloud/mask.sh")], input=text, capture_output=True, text=True, check=True).stdout
    for leaked in ("203.0.113.45", "10.0.1.5", "123456789012", "i-0123456789abcdef0", "yo@correo.com", "Nombre_Apellido"):
        assert leaked not in out
    assert "v3.0.22" in out and "1.2.3" in out


def test_subscription_script_reads_hidden_input_and_never_prints_or_passes_the_address_on_the_command_line() -> None:
    script = (ROOT / "scripts/cloud/suscribir-correo-alarmas.sh").read_text()
    assert script.count("read -r -s") == 2 and "set -x" not in script
    assert 'echo "$EMAIL' not in script and "echo $EMAIL" not in script and "> /tmp" not in script
    assert not any("/dev/stdin" in l for l in script.splitlines() if not l.lstrip().startswith("#"))  # la CLI lee el archivo dos veces: una tubería llega vacía
    assert '--cli-input-json "file://$WORK/in.json"' in script and "--notification-endpoint" not in script and "trap cleanup EXIT" in script
    assert ".invalid" in script


def test_subscription_script_validates_input_in_dry_run_without_calling_aws() -> None:
    run = lambda text: subprocess.run(["bash", str(ROOT / "scripts/cloud/suscribir-correo-alarmas.sh"), "--dry-run"], input=text, capture_output=True, text=True)  # noqa: E731
    ok = run("persona@correo.com\npersona@correo.com\n")
    assert ok.returncode == 0 and "persona" not in ok.stdout + ok.stderr
    assert run("persona@correo.com\notra@correo.com\n").returncode == 1  # no coinciden
    assert run("pendiente@example.invalid\npendiente@example.invalid\n").returncode == 1  # marcador rechazado
    assert run("no-es-correo\nno-es-correo\n").returncode == 1


def _plan(**overrides) -> dict:
    changes = [{"address": a, "type": a.split(".")[0], "change": {"actions": ["create"], "before": None, "after": {}}} for a in sorted(VP.EXPECTED_CREATES)]
    changes.append({"address": VP.EXPECTED_UPDATE, "type": "aws_cloudwatch_metric_alarm", "change": {"actions": ["update"], "before": {"alarm_actions": [], "ok_actions": []}, "after": {"alarm_actions": ["x"], "ok_actions": ["x"]}}})
    changes.append({"address": "aws_db_instance.postgres", "type": "aws_db_instance", "change": {"actions": ["no-op"], "before": {}, "after": {}}})
    changes.extend(overrides.get("extra", []))
    return {"resource_changes": changes}


def test_plan_verifier_accepts_exactly_the_expected_plan() -> None:
    assert VP.verify(_plan()) == []


def test_plan_verifier_rejects_subnet_rds_s3_destroy_and_email() -> None:
    bad = lambda t, a: {"address": f"{t}.x", "type": t, "change": {"actions": a, "before": {}, "after": {}}}  # noqa: E731
    assert any("subnet" in p or "no debe tocarse" in p for p in VP.verify(_plan(extra=[bad("aws_subnet", ["update"])])))
    assert any("no debe tocarse" in p for p in VP.verify(_plan(extra=[bad("aws_db_instance", ["update"])])))
    assert any("no debe tocarse" in p for p in VP.verify(_plan(extra=[bad("aws_s3_bucket_lifecycle_configuration", ["update"])])))
    assert any("destrucción" in p for p in VP.verify(_plan(extra=[bad("aws_cloudwatch_metric_alarm", ["delete", "create"])])))
    leaky = _plan()
    leaky["resource_changes"].append({"address": "aws_sns_topic_subscription.alarms_email[0]", "type": "aws_sns_topic_subscription", "change": {"actions": ["create"], "before": None, "after": {"endpoint": "a@b.com"}}})
    assert any("correo" in p for p in VP.verify(leaky))
    wider = _plan()
    wider["resource_changes"][-2]["change"]["after"]["threshold"] = 99
    assert any("más que las acciones" in p for p in VP.verify(wider))


def test_subscription_json_is_valid_for_special_characters_and_cleaned_up(tmp_path) -> None:
    """Regresión: la CLI leía el JSON dos veces desde la tubería y fallaba. Con un 'aws' falso se comprueba el archivo recibido y que se borre; sin AWS."""
    import os
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "aws").write_text('#!/usr/bin/env bash\nif [[ "$1 $2" == "sts get-caller-identity" ]]; then echo ok; exit 0; fi\n'
                              'if [[ "$1 $2" == "sns list-topics" ]]; then echo arn:aws:sns:us-east-1:111111111111:nexoeventos-academy-alarmas; exit 0; fi\n'
                              'if [[ "$1 $2" == "sns list-subscriptions-by-topic" ]]; then echo 0; exit 0; fi\n'
                              'if [[ "$1 $2" == "sns subscribe" ]]; then f="${4#file://}"; python3 -c "import json,sys;d=json.load(open(sys.argv[1]));open(sys.argv[2],\'w\').write(d[\'Endpoint\']+\'|\'+sys.argv[1])" "$f" "$FAKE_OUT"; exit 0; fi\n'
                              'exit 0\n')
    (fake / "aws").chmod(0o755)
    for addr in ("a.b+c%d@sub-dominio.example.com", "o'brien@correo.com"):
        out = tmp_path / f"out{abs(hash(addr))}.txt"
        env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "AWS_PROFILE": "x", "FAKE_OUT": str(out), "TMPDIR": str(tmp_path)}
        r = subprocess.run(["bash", str(ROOT / "scripts/cloud/suscribir-correo-alarmas.sh")], input=f"{addr}\n{addr}\n", capture_output=True, text=True, env=env)
        if "'" in addr:  # la validación rechaza comillas antes de generar JSON
            assert r.returncode == 1 and not out.exists()
            continue
        assert r.returncode == 0 and addr not in r.stdout + r.stderr
        endpoint, path = out.read_text().split("|")
        assert endpoint == addr and not Path(path).exists()  # JSON correcto y archivo temporal borrado
    assert not list(tmp_path.glob("nexo-sns.*"))


def test_s3_lifecycle_targets_real_backup_prefix_with_long_default_retention() -> None:
    """Regresión del hallazgo 15: el lifecycle desplegado apuntaba a `database-backups/` (vacío); los respaldos reales están en `backups/database/`.
    Al corregir el prefijo, la retención por defecto no puede ser corta: alinear con 7 días borraría los respaldos reales."""
    import re
    tf = (ROOT / "infra/aws/storage_observability.tf").read_text()
    assert 'filter { prefix = "backups/database/" }' in tf and "database-backups/" not in tf
    variables = (ROOT / "infra/aws/variables.tf").read_text()
    block = variables.split('variable "s3_backup_retention_days"')[1].split("\n}\n")[0]
    assert int(re.search(r"default\s*=\s*(\d+)", block).group(1)) >= 365


def test_s3_subnet_plan_verifier_accepts_only_prefix_retention_and_public_ip_changes() -> None:
    spec2 = importlib.util.spec_from_file_location("verify_s3", ROOT / "scripts/cloud/verificar-plan-s3-subred.py")
    vs = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(vs)
    rule = lambda p, d: {"bucket": "b", "rule": [{"filter": [{"prefix": p}], "expiration": [{"days": d}], "noncurrent_version_expiration": [{"noncurrent_days": d}]}]}  # noqa: E731
    lc = {"address": vs.LIFECYCLE, "type": "aws_s3_bucket_lifecycle_configuration", "change": {"actions": ["update"], "before": rule("database-backups/", 7), "after": rule("backups/database/", 365)}}
    sn = {"address": vs.SUBNET, "type": "aws_subnet", "change": {"actions": ["update"], "before": {"map_public_ip_on_launch": True, "cidr_block": "x"}, "after": {"map_public_ip_on_launch": False, "cidr_block": "x"}}}
    assert vs.verify({"resource_changes": [lc, sn]}) == []
    short = {**lc, "change": {**lc["change"], "after": rule("backups/database/", 7)}}
    assert any("retención" in p for p in vs.verify({"resource_changes": [short, sn]}))  # 7 días borraría los respaldos reales
    wrong = {**lc, "change": {**lc["change"], "after": rule("database-backups/", 365)}}
    assert any("prefijo" in p for p in vs.verify({"resource_changes": [wrong, sn]}))
    wider = {**sn, "change": {**sn["change"], "after": {"map_public_ip_on_launch": False, "cidr_block": "y"}}}
    assert any("subred" in p for p in vs.verify({"resource_changes": [lc, wider]}))
    ec2 = {"address": "aws_instance.app", "type": "aws_instance", "change": {"actions": ["update"], "before": {}, "after": {}}}
    assert vs.verify({"resource_changes": [lc, sn, ec2]})
    destroy = {"address": "aws_s3_bucket.private", "type": "aws_s3_bucket", "change": {"actions": ["delete", "create"], "before": {}, "after": {}}}
    assert any("destrucción" in p for p in vs.verify({"resource_changes": [lc, sn, destroy]}))


def test_s3_only_mode_rejects_any_subnet_change() -> None:
    spec3 = importlib.util.spec_from_file_location("verify_s3b", ROOT / "scripts/cloud/verificar-plan-s3-subred.py")
    vs = importlib.util.module_from_spec(spec3)
    spec3.loader.exec_module(vs)
    rule = lambda p, d: {"bucket": "b", "rule": [{"filter": [{"prefix": p}], "expiration": [{"days": d}], "noncurrent_version_expiration": [{"noncurrent_days": d}]}]}  # noqa: E731
    lc = {"address": vs.LIFECYCLE, "type": "aws_s3_bucket_lifecycle_configuration", "change": {"actions": ["update"], "before": rule("database-backups/", 7), "after": rule("backups/database/", 365)}}
    sn = {"address": vs.SUBNET, "type": "aws_subnet", "change": {"actions": ["update"], "before": {"map_public_ip_on_launch": True}, "after": {"map_public_ip_on_launch": False}}}
    assert vs.verify({"resource_changes": [lc]}, solo_s3=True) == []
    assert vs.verify({"resource_changes": [lc, sn]}, solo_s3=True)  # la subred no puede venir en la Fase A1
    assert vs.verify({"resource_changes": [lc]}, solo_s3=False)  # y el modo completo exige ambas


def test_subnet_only_mode_accepts_just_public_ip_flag_and_rejects_the_rest() -> None:
    spec4 = importlib.util.spec_from_file_location("verify_s3c", ROOT / "scripts/cloud/verificar-plan-s3-subred.py")
    vs = importlib.util.module_from_spec(spec4)
    spec4.loader.exec_module(vs)
    sn = lambda b, a: {"address": vs.SUBNET, "type": "aws_subnet", "change": {"actions": ["update"], "before": b, "after": a}}  # noqa: E731
    ok = sn({"map_public_ip_on_launch": True, "cidr_block": "x"}, {"map_public_ip_on_launch": False, "cidr_block": "x"})
    assert vs.verify({"resource_changes": [ok]}, solo_subred=True) == []
    assert vs.verify({"resource_changes": [sn({"map_public_ip_on_launch": True, "cidr_block": "x"}, {"map_public_ip_on_launch": False, "cidr_block": "y"})]}, solo_subred=True)
    assert vs.verify({"resource_changes": [sn({"map_public_ip_on_launch": False}, {"map_public_ip_on_launch": True})]}, solo_subred=True)  # sentido contrario
    lc = {"address": vs.LIFECYCLE, "type": "aws_s3_bucket_lifecycle_configuration", "change": {"actions": ["update"], "before": {}, "after": {}}}
    assert vs.verify({"resource_changes": [ok, lc]}, solo_subred=True)  # ningún otro recurso


def test_v2_plan_verifier_accepts_only_creations_with_expected_ami_and_rejects_changes() -> None:
    spec5 = importlib.util.spec_from_file_location("verify_v2", ROOT / "scripts/cloud/verificar-plan-v2.py")
    v2 = importlib.util.module_from_spec(spec5)
    spec5.loader.exec_module(v2)
    import base64 as b64
    ud = b64.b64encode(b"truststore.pki.rds.amazonaws.com e4ce41d069f4bdcdb714259058961ee42ed18cf2bf627a3d647aff25437d4b68").decode()

    def res(t, after=None, actions=("create",)):
        return {"address": f"{t}.x", "type": t, "change": {"actions": list(actions), "before": None, "after": after or {}}}

    changes = []
    for t, n in {**v2.ALLOWED, **v2.ALARM_TYPES}.items():
        for _ in range(n):
            after = {}
            if t == "aws_launch_template":
                after = {"image_id": "ami-1", "metadata_options": [{"http_tokens": "required"}], "block_device_mappings": [{"ebs": [{"encrypted": True}]}], "user_data": ud}
            elif t == "aws_lb_target_group":
                after = {"health_check": [{"path": "/healthz"}]}
            elif t == "aws_lb":
                after = {"load_balancer_type": "application"}
            elif t == "aws_autoscaling_group":
                after = {"min_size": 2, "max_size": 3, "desired_capacity": 2}
            elif t == "aws_lb_listener":
                after = {"port": 80 if len([c for c in changes if c["type"] == t]) == 0 else 443, "protocol": "HTTP" if len([c for c in changes if c["type"] == t]) == 0 else "HTTPS"}
            changes.append(res(t, after))
    assert v2.verify({"resource_changes": changes}, "ami-1") == []
    assert any("AMI" in p for p in v2.verify({"resource_changes": changes}, "ami-2"))
    assert any("distinta de crear" in p for p in v2.verify({"resource_changes": changes + [res("aws_db_instance", actions=("update",))]}, "ami-1"))
    assert v2.verify({"resource_changes": changes + [res("aws_s3_bucket")]}, "ami-1")  # un recurso no previsto
    assert any("secretos" in p for p in v2.verify({"resource_changes": [{**c, "change": {**c["change"], "after": {**c["change"]["after"], "user_data": b64.b64encode(b"DATABASE=postgresql+psycopg://u:clave@h/db").decode()}}} if c["type"] == "aws_launch_template" else c for c in changes]}, "ami-1"))
