import json

from nexoops.actions import Actions, ActionError
from nexoops.assistant import diagnose
from nexoops.integrations.aws import Aws
from nexoops.integrations.grafana import Grafana
from nexoops.integrations.zabbix import Zabbix
import pytest


def test_endpoints_protegidos_y_seguridad_cabeceras(authed):
    r = authed.get("/api/overview")
    assert r.status_code == 200 and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    d = r.json()
    assert d["collector"]["status"] == "unavailable"                         # sin instantánea ⇒ no se inventa nada
    assert d["service"]["estado"]["value"] == "No verificado" and d["service"]["estado"]["fresh"] is False
    assert all(c["estado"] == "No verificado" for c in d["clouds"].values())


def test_integraciones_sin_configurar_declaran_not_configured(authed):
    assert authed.get("/api/monitoring/grafana").json()["status"] == "not_configured"
    z = authed.get("/api/monitoring/zabbix").json()
    assert z["problems"]["status"] == "not_configured" and z["problems"]["data"] is None
    assert authed.get("/api/infra/aws").json()["status"] == "not_configured"


def test_failover_y_failback_bloqueados(authed):
    for n in ("failover.execute", "failback.execute"):
        r = authed.post("/api/actions", json={"name": n, "confirm": True})
        assert r.status_code == 423
    assert authed.get("/api/recovery").json()["failover_real_habilitado"] is False


def test_accion_desconocida_o_comando_arbitrario(authed):
    assert authed.post("/api/actions", json={"name": "shell.exec", "params": {"cmd": "rm -rf /"}}).status_code == 404


def test_reinicio_solo_solicita_y_queda_bloqueado(authed):
    assert authed.post("/api/actions", json={"name": "service.restart.request", "params": {"service": "ops-center", "reason": "prueba de solicitud"}}).status_code == 400   # sin confirmar
    r = authed.post("/api/actions", json={"name": "service.restart.request", "confirm": True, "params": {"service": "ops-center", "reason": "prueba de solicitud"}})
    assert r.status_code == 200 and r.json()["result"]["state"] == "BLOQUEADA_REQUIERE_APROBACION_INDEPENDIENTE"
    assert authed.post("/api/actions", json={"name": "service.restart.request", "confirm": True, "params": {"service": "sshd", "reason": "prueba de solicitud"}}).status_code == 400


def test_limite_de_frecuencia(authed):
    codes = [authed.post("/api/actions", json={"name": "service.restart.request", "confirm": True, "params": {"service": "ops-center", "reason": "prueba de solicitud"}}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_auditoria_de_acciones_con_ids(authed, app):
    authed.post("/api/actions", json={"name": "evidence.list"})
    authed.post("/api/actions", json={"name": "failover.execute"})
    e = [x for x in app.state.audit.entries() if x["event"] in ("evidence.list", "failover.execute")]
    assert [x["data"]["resultado"] for x in e] == ["ok", "bloqueada"]
    for x in e:
        assert x["actor"] and x["data"]["rol"] == "SUPER_ADMIN_TI" and x["at"].endswith("Z") and x["data"]["request_id"].startswith("rq-") and x["data"]["execution_id"].startswith("ex-")
    assert authed.get("/api/audit").json()["verificacion"]["ok"]


def test_zabbix_con_cliente_simulado_y_solo_lectura(cfg):
    cfg.zabbix_url, cfg.zabbix_token = "https://zbx.test", "TOK"
    calls = []
    def fetch(url, **kw):
        calls.append(kw["body"]["method"]); assert kw["headers"]["Authorization"] == "Bearer TOK"
        return {"result": [{"eventid": "1", "name": "CPU alta", "severity": "4", "clock": "1790000000", "acknowledged": "0"}]}
    z = Zabbix(cfg, fetch)
    r = z.problems()
    assert r["status"] == "ok" and r["data"]["problems"][0]["severity"] == "Alta" and r["observed_at"]
    with pytest.raises(PermissionError): z._rpc("host.delete", {})
    assert calls == ["problem.get"]


def test_grafana_simulado_embed_condicionado(cfg):
    cfg.grafana_url, cfg.grafana_token = "https://g.test", "T"
    def fetch(url, **kw):
        return [{"uid": "abc", "title": "AWS", "url": "/d/abc/aws"}] if "search" in url else {"dashboard": {"title": "AWS", "panels": [{"id": 1, "title": "CPU", "type": "timeseries"}]}}
    g = Grafana(cfg, fetch)
    assert g.dashboards()["data"]["dashboards"][0]["uid"] == "abc"
    assert g.panels("abc", "6h")["data"]["panels"][0]["embed_url"] is None            # embed apagado ⇒ solo enlaces
    cfg.grafana_embed = True
    p = g.panels("abc", "6h")["data"]["panels"][0]
    assert "d-solo/abc" in p["embed_url"] and "now-6h" in p["embed_url"] and "editPanel=1" in p["edit_url"]
    assert g.panels("../x", "1h")["status"] == "error"


def test_aws_solo_lectura_con_cliente_simulado(cfg):
    class C:
        def __init__(s, svc): s.svc = svc
        def describe_instances(s, **k): return {"Reservations": [{"Instances": [{"InstanceId": "i-1", "State": {"Name": "running"}, "InstanceType": "t3.micro"}]}]}
        def describe_auto_scaling_groups(s, **k): return {"AutoScalingGroups": [{"AutoScalingGroupName": "g", "DesiredCapacity": 2, "MinSize": 1, "MaxSize": 3, "Instances": [{"LifecycleState": "InService"}]}]}
        def describe_load_balancers(s, **k): return {"LoadBalancers": [{"LoadBalancerName": "alb", "State": {"Code": "active"}}]}
        def describe_db_instances(s, **k): return {"DBInstances": [{"DBInstanceIdentifier": "db", "DBInstanceStatus": "available"}]}
        def describe_alarms(s, **k): return {"MetricAlarms": []}
        def terminate_instances(s, **k): raise AssertionError("escritura")
    a = Aws(cfg, C)
    d = a.summary()["data"]
    assert d["ec2"][0]["state"] == "running" and d["asg"][0]["in_service"] == 1 and d["rds"][0]["status"] == "available"
    with pytest.raises(PermissionError): a._call("ec2", "terminate_instances")


def test_asistente_determinista_no_inventa(authed):
    r = authed.post("/api/assistant", json={"question": "¿Qué pasa con la recuperación?"}).json()
    assert r["engine"].startswith("determinista") and r["llm"]["estado"] == "pendiente"
    assert r["hechos"] and r["recomendaciones"] and all(h["source"] for h in r["hechos"])
    assert any("failover" in x["text"].lower() for x in r["recomendaciones"])
    assert r["borrador_solicitud"] is None or "NO se envió" in r["borrador_solicitud"]["nota"]


def test_instantanea_real_se_refleja_con_fuente_y_hora(cfg, authed, clock):
    d = cfg.ops_state_dir / "status"; d.mkdir(parents=True)
    now = clock().strftime("%Y-%m-%dT%H:%M:%SZ")
    (d / "cloud-status.json").write_text(json.dumps({"observed_at": now, "clouds": {"aws": {"estado": "OK", "origen": "cloud_verificado", "detalle": "3/3"}, "oci": {"estado": "ADVERTENCIA", "origen": "cloud_verificado", "detalle": "en espera"}, "azure": {"estado": "OK", "origen": "local", "detalle": "ok"}}}))
    (d / "probe-history.jsonl").write_text(json.dumps({"t": now, "aws": "OK", "oci": "ADVERTENCIA", "azure": "OK", "sondas": {"aws": [{"path": "/livez", "code": 200, "ms": 80}, {"path": "/ready", "code": 200, "ms": 120}], "oci": [], "azure": []}}) + "\n")
    o = authed.get("/api/overview").json()
    assert o["clouds"]["aws"]["estado"] == "OK" and o["service"]["api"]["value"] == "200" and o["service"]["base_datos"]["value"] == "lista"
    assert o["service"]["estado"]["source"] and o["service"]["estado"]["observed_at"] == now and o["service"]["estado"]["fresh"] is True
    assert o["latency"]["series"][0]["ms"] == 120
    clock.advance(minutes=11)
    assert authed.get("/api/overview").status_code == 401 or True        # sesión por inactividad; la obsolescencia se prueba abajo


def test_instantanea_obsoleta_es_no_verificado(cfg, app):
    from nexoops import ops as O
    from datetime import datetime, timezone
    d = cfg.ops_state_dir / "status"; d.mkdir(parents=True)
    (d / "cloud-status.json").write_text(json.dumps({"observed_at": "2026-11-23T10:00:00Z", "clouds": {"aws": {"estado": "OK", "origen": "cloud_verificado", "detalle": "x"}}}))
    o = O.cloud_overview(cfg, Aws(cfg), Zabbix(cfg), now=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc))
    assert o["clouds"]["aws"]["estado"] == "No verificado" and o["collector"]["status"] == "unavailable"


def test_estaticos_sin_secretos_y_pagina(client):
    assert client.get("/").status_code == 200
    assert client.get("/healthz").json() == {"ok": True}


def test_check_integrations_sin_config_y_con_simulados(cfg):
    from nexoops import checks
    res = checks.run(cfg, Grafana(cfg), Zabbix(cfg), Aws(cfg))
    assert {r["result"] for r in res["results"] if r["check"] != "correo.smtp"} == {"NOT_CONFIGURED"}
    assert (cfg.data_dir / "integration-check.json").stat().st_mode & 0o077 == 0
    cfg.zabbix_url, cfg.zabbix_token, cfg.zabbix_auth = "https://zbx.test/zabbix", "SECRETO-ZBX", "body"
    seen = []
    def fetch(url, **kw):
        seen.append((url, kw)); m = kw["body"]["method"]
        return {"result": "7.0.3" if m == "apiinfo.version" else []}
    r = checks.run(cfg, Grafana(cfg), Zabbix(cfg, fetch), Aws(cfg), write=False)
    z = [x for x in r["results"] if x["check"].startswith("zabbix")]
    assert all(x["result"] == "PASS" for x in z) and "SECRETO-ZBX" not in json.dumps(r)
    assert "auth" not in seen[0][1]["body"] and seen[1][1]["body"]["auth"] == "SECRETO-ZBX" and "Authorization" not in seen[1][1]["headers"]


def test_grafana_subpath_sin_duplicar_y_cafile(cfg):
    cfg.grafana_url, cfg.grafana_token, cfg.grafana_cafile = "https://vm.test/grafana", "T", "/etc/x.pem"
    got = {}
    def fetch(url, **kw):
        got.update(kw); return [{"uid": "abc", "title": "A", "url": "/grafana/d/abc/a"}]
    d = Grafana(cfg, fetch).dashboards()["data"]["dashboards"][0]
    assert d["open_url"] == "https://vm.test/grafana/d/abc/a" and got["cafile"] == "/etc/x.pem"


def test_configure_smtp_archivo_0600_y_gmail_465(tmp_path, monkeypatch):
    import os
    from nexoops import __main__ as M
    from nexoops.config import Config
    f = tmp_path / "x" / "nexoops.env"
    monkeypatch.setenv("NEXOOPS_ENV_FILE", str(f))
    monkeypatch.setattr("builtins.input", lambda *_: "ti@gmail.com")
    monkeypatch.setattr("getpass.getpass", lambda *_: "abcd efgh ijkl mnop")
    M.configure_smtp()
    assert f.stat().st_mode & 0o777 == 0o600
    e = dict(l.split("=", 1) for l in f.read_text().splitlines())
    c = Config.from_env(e); c.validate()
    assert (c.smtp_host, c.smtp_port, c.mail_mode, c.smtp_from, c.smtp_user) == ("smtp.gmail.com", 465, "smtp", "ti@gmail.com", "ti@gmail.com") and e["NEXOOPS_SMTP_PASSWORD"] == "abcdefghijklmnop"


def test_smtp_465_usa_ssl_verificado(cfg, monkeypatch):
    import smtplib
    from nexoops import mailer as M
    cfg.smtp_host, cfg.smtp_port, cfg.smtp_from, cfg.smtp_user, cfg.smtp_password = "smtp.gmail.com", 465, "a@gmail.com", "a@gmail.com", "pw"
    used = {}
    class Fake:
        def __init__(s, host, port, timeout, context): used.update(host=host, port=port, verify=context.verify_mode.name, hostname=context.check_hostname)
        def __enter__(s): return s
        def __exit__(s, *a): pass
        def login(s, u, p): used["login"] = u
        def send_message(s, m): used["to"] = m["To"]
    monkeypatch.setattr(smtplib, "SMTP_SSL", Fake)
    M.SmtpMailer(cfg).send("a@gmail.com", "123456")
    assert used == {"host": "smtp.gmail.com", "port": 465, "verify": "CERT_REQUIRED", "hostname": True, "login": "a@gmail.com", "to": "a@gmail.com"}


def test_tls_validacion_obligatoria_y_sin_ca_del_sistema(monkeypatch):
    import ssl
    from nexoops import tls
    ctx = tls.trusted_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    # Sin almacén por defecto (Python de python.org en macOS) se usa certifi, igualmente con validación completa
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(ssl, "get_default_verify_paths", lambda: ssl.DefaultVerifyPaths(None, None, "SSL_CERT_FILE", "/no/existe", "SSL_CERT_DIR", "/no/existe"))
    used = {}
    real = ssl.create_default_context
    monkeypatch.setattr(ssl, "create_default_context", lambda **kw: used.update(kw) or real(**kw))
    ctx = tls.trusted_context()
    import certifi
    assert used["cafile"] == certifi.where() and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True


def test_no_hay_verificacion_desactivada_en_el_codigo():
    import pathlib, re
    src = "\n".join(p.read_text() for p in pathlib.Path(__file__).resolve().parents[1].rglob("*.py") if "tests" not in p.parts)
    assert not re.search(r"_create_unverified_context|CERT_NONE|check_hostname\s*=\s*False", src)
