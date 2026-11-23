import json
import socket

import pytest

from ops_center import barriers as B
from ops_center.app import create_app
from ops_center.settings import FAILOVER_PHRASE
from .conftest import H, TOKENS, write_evidence

REASON = "Prueba de recuperación autorizada por la propietaria"


def post(c, role, path, body=None):
    return c.post(path, json=body or {}, headers=H(role))


def make(c, tipo="restaurar_respaldo_en_oci", role="requester"):
    return post(c, role, "/api/ops/recovery-requests", {"tipo": tipo, "reason": REASON})


def test_sin_token_o_con_token_malo_401_y_roles_limitados(client):
    assert client.get("/api/ops/overview").status_code == 401
    assert client.get("/api/ops/overview", headers={"Authorization": "Bearer nada"}).status_code == 401
    assert client.get("/api/ops/overview", headers=H("viewer")).status_code == 200
    assert make(client, role="viewer").status_code == 403
    assert make(client, role="approver").status_code == 403
    assert client.get("/api/ops/audit", headers=H("viewer")).json()["verificacion"]["ok"]


def test_solicitud_de_restauracion_valida_se_aprueba_por_otro_y_queda_auditada(client):
    r = make(client); assert r.status_code == 201 and r.json()["state"] == "VALIDADA", r.json()
    rid = r.json()["id"]
    assert post(client, "approver", f"/api/ops/recovery-requests/{rid}/approve", {"comment": "ok"}).json()["state"] == "APROBADA"
    ev = [e["event"] for e in client.get("/api/ops/audit", headers=H("viewer")).json()["entradas"]]
    assert ev == ["solicitada", "validada", "aprobada"]
    assert client.get("/api/ops/audit", headers=H("viewer")).json()["verificacion"]["ok"]


def test_el_solicitante_no_puede_aprobar_ni_con_rol_aprobador(settings, clock):
    from ops_center import identities as I
    from fastapi.testclient import TestClient
    # una identidad que solicita y aprueba no existe: el rol requester no tiene 'decide'
    c = TestClient(create_app(settings, clock=clock)); rid = make(c).json()["id"]
    assert post(c, "requester", f"/api/ops/recovery-requests/{rid}/approve").status_code == 403
    # y el almacén rechaza aprobar a quien solicitó (defensa en profundidad)
    from ops_center.recovery import RecoveryStore, RecoveryError
    from ops_center.audit import AuditLog
    st = RecoveryStore(settings.state_dir, AuditLog(settings.state_dir / "audit.jsonl"), lambda r: {"ok": True, "barriers": []}, clock=clock)
    with pytest.raises(RecoveryError) as e: st.decide(rid, "ti-solicitante", True)
    assert e.value.code == 403


def test_failover_se_rechaza_en_validacion_sin_evidencias_ni_configuracion(client):
    r = make(client, "failover_aws_a_oci").json()
    assert r["state"] == "RECHAZADA_VALIDACION"
    fallidas = {b["id"] for b in r["validation"]["barriers"] if not b["ok"]}
    assert {"B06_T1", "B06_T2", "B06_T3", "B06_T4", "B07_configuracion_failover"} <= fallidas
    assert post(client, "approver", f"/api/ops/recovery-requests/{r['id']}/approve").status_code == 409   # no se puede aprobar lo rechazado


def test_una_solicitud_activa_por_tipo_idempotencia_y_justificacion(client):
    assert make(client).status_code == 201
    assert make(client).status_code == 409
    assert post(client, "requester", "/api/ops/recovery-requests", {"tipo": "restaurar_respaldo_en_oci", "reason": "corta"}).status_code in (400, 409)
    assert post(client, "requester", "/api/ops/recovery-requests", {"tipo": "borrar_todo", "reason": REASON}).status_code in (400, 409)


def test_idempotencia_devuelve_la_misma_solicitud(client):
    b = {"tipo": "restaurar_respaldo_en_oci", "reason": REASON, "idempotency_key": "k1"}
    a = post(client, "requester", "/api/ops/recovery-requests", b).json(); c = post(client, "requester", "/api/ops/recovery-requests", b).json()
    assert a["id"] == c["id"]


def test_expiran_la_solicitud_y_la_aprobacion(client, clock):
    rid = make(client).json()["id"]; clock.advance(minutes=31)
    assert client.get(f"/api/ops/recovery-requests/{rid}", headers=H("viewer")).json()["state"] == "EXPIRADA"
    rid2 = make(client).json()["id"]; post(client, "approver", f"/api/ops/recovery-requests/{rid2}/approve")
    clock.advance(minutes=61); assert client.get(f"/api/ops/recovery-requests/{rid2}", headers=H("viewer")).json()["state"] == "EXPIRADA"


def test_denegar_y_cancelar_con_permisos(client):
    rid = make(client).json()["id"]
    assert post(client, "approver", f"/api/ops/recovery-requests/{rid}/deny", {"comment": "no"}).json()["state"] == "DENEGADA"
    assert post(client, "requester", f"/api/ops/recovery-requests/{rid}/cancel").status_code == 409
    rid2 = make(client).json()["id"]
    assert post(client, "viewer", f"/api/ops/recovery-requests/{rid2}/cancel").status_code == 403
    assert post(client, "requester", f"/api/ops/recovery-requests/{rid2}/cancel").json()["state"] == "CANCELADA"


def test_kill_switch_y_plazo_bloquean_la_validacion(client, settings, clock):
    settings.state_dir.joinpath("KILL_SWITCH").write_text("x")
    assert make(client).json()["state"] == "RECHAZADA_VALIDACION"
    settings.state_dir.joinpath("KILL_SWITCH").unlink(); clock.advance(days=2, hours=20)   # 26-nov 08:00 > plazo − margen
    r = make(client).json(); assert r["state"] == "RECHAZADA_VALIDACION" and any(b["id"] == "B03_plazo_academy" and not b["ok"] for b in r["validation"]["barriers"])


def test_registro_de_promocion_pendiente_bloquea(client, settings):
    (settings.failover_dir / "ledger.json").write_text(json.dumps({"state": "PROMOTING"}))
    assert make(client).json()["state"] == "RECHAZADA_VALIDACION"


def test_respaldo_vencido_bloquea(client, settings):
    from datetime import datetime, timedelta, timezone   # app.ops evalúa la edad con la hora REAL (comportamiento de producción)
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (settings.backup_state_dir / "cycles.jsonl").write_text(json.dumps({"ok": True, "finished_at": old, "name": "x.cms", "env": "t"}) + "\n")
    assert make(client).json()["state"] == "RECHAZADA_VALIDACION"


def _todo_en_regla(settings, clock, monkeypatch):
    for st in ("T1", "T2", "T3", "T4"): write_evidence(settings, st, clock)
    monkeypatch.setattr(B, "_config_ok", lambda s: (True, "configuración válida"))


def test_ejecucion_sigue_bloqueada_aunque_todo_lo_demas_pase(settings, clock, monkeypatch):
    from fastapi.testclient import TestClient
    _todo_en_regla(settings, clock, monkeypatch)
    settings.env["NEXO_ALLOW_FAILOVER_EXECUTE"] = "YES"
    (settings.state_dir / "autorizacion-T6.json").write_text(json.dumps({"frase": FAILOVER_PHRASE, "expires_at": "2026-11-23T14:00:00Z"}))
    c = TestClient(create_app(settings, clock=clock))
    rid = make(c, "failover_aws_a_oci").json()
    assert rid["state"] == "VALIDADA", [b for b in rid["validation"]["barriers"] if not b["ok"]]
    post(c, "approver", f"/api/ops/recovery-requests/{rid['id']}/approve")
    res = c.get("/api/ops/barriers/failover_aws_a_oci", headers=H("viewer")).json()
    assert not res["ok"] and [b["id"] for b in res["barriers"] if not b["ok"]] == ["B11_adaptadores_reales_cableados"]
    monkeypatch.setattr(B, "REAL_EXECUTION_WIRED", True)     # solo para demostrar que las demás barreras son completables
    assert c.get("/api/ops/barriers/failover_aws_a_oci", headers=H("viewer")).json()["ok"]


def test_autorizacion_con_frase_distinta_o_larga_vigencia_no_vale(settings, clock):
    p = settings.state_dir / "autorizacion-T6.json"
    p.write_text(json.dumps({"frase": "si", "expires_at": "2026-11-23T14:00:00Z"})); assert B._read_authorization(settings, clock()) != True
    p.write_text(json.dumps({"frase": FAILOVER_PHRASE, "expires_at": "2026-11-30T00:00:00Z"})); assert B._read_authorization(settings, clock()) != True
    p.write_text(json.dumps({"frase": FAILOVER_PHRASE, "expires_at": "2026-11-23T11:00:00Z"})); assert B._read_authorization(settings, clock()) != True


def test_evidencia_vieja_o_fallida_no_cuenta(settings, clock):
    write_evidence(settings, "T3", clock, age_h=25); assert B.read_evidence(settings, "T3", clock())[0] is None
    write_evidence(settings, "T1", clock, result="FAIL"); assert B.read_evidence(settings, "T1", clock())[0] is None
    write_evidence(settings, "T1", clock); assert B.read_evidence(settings, "T1", clock())[0] is not None


def test_dominio_de_produccion_prohibido_en_la_configuracion(settings, tmp_path, monkeypatch):
    import failover_config as FC
    cfg = tmp_path / "c.json"; cfg.write_text(json.dumps({"dns": {"allowed_domains": ["nexoeventos-demo"]}}))
    settings.failover_config = cfg
    monkeypatch.setattr(FC, "load", lambda p: {}); monkeypatch.setattr(FC, "validate", lambda c: {"ok": True, "errors": []})
    ok, det = B._config_ok(settings); assert not ok and "producción" in det


def test_el_panel_funciona_sin_red_ni_aws_ni_base_de_datos(settings, clock, monkeypatch):
    from fastapi.testclient import TestClient
    def boom(*a, **k): raise AssertionError("el centro intentó usar la red")
    monkeypatch.setattr(socket.socket, "connect", boom); monkeypatch.setattr(socket, "create_connection", boom); monkeypatch.setattr(socket, "getaddrinfo", boom)
    for v in ("DATABASE_URL", "AWS_ACCESS_KEY_ID", "AWS_PROFILE"): monkeypatch.delenv(v, raising=False)
    c = TestClient(create_app(settings, clock=clock))
    o = c.get("/api/ops/overview", headers=H("viewer")).json()
    assert o["independencia"]["depende_de_aws"] is False and o["nubes"]["nubes"]["aws"]["estado"] == "No verificado"
    assert make(c).json()["state"] == "VALIDADA"


def test_estado_de_nubes_con_instantanea_reciente_vieja_y_con_secretos(settings, clock):
    from fastapi.testclient import TestClient
    sd = settings.state_dir / "status"; sd.mkdir()
    snap = {"observed_at": clock().strftime("%Y-%m-%dT%H:%M:%SZ"), "clouds": {"aws": {"estado": "OK", "origen": "cloud_verificado", "detalle": "ALB 54.210.33.99 sano"}, "oci": {"estado": "ERROR", "origen": "cloud_verificado", "detalle": "x"}, "azure": {"estado": "RARO"}}}
    (sd / "cloud-status.json").write_text(json.dumps(snap))
    c = TestClient(create_app(settings, clock=clock)); n = c.get("/api/ops/overview", headers=H("viewer")).json()["nubes"]["nubes"]
    assert n["aws"]["estado"] == "OK" and "54.210.33.99" not in n["aws"]["detalle"] and n["oci"]["estado"] == "ERROR" and n["azure"]["estado"] == "No verificado"
    clock.advance(minutes=11)
    assert c.get("/api/ops/overview", headers=H("viewer")).json()["nubes"]["nubes"]["aws"]["estado"] == "No verificado"


def test_panel_estatico_con_csp_y_sin_innerhtml(client):
    r = client.get("/"); assert r.status_code == 200 and "script-src 'self'" in r.headers["content-security-policy"] and "no ejecuta" in r.text
    js = client.get("/panel.js").text; assert "innerHTML" not in js and "eval(" not in js and "localStorage" not in js
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_guardia_la_ejecucion_real_sigue_sin_cablear():
    import re
    from pathlib import Path
    src = (Path(B.__file__)).read_text()
    assert re.search(r"^REAL_EXECUTION_WIRED = False$", src, re.M) and B.REAL_EXECUTION_WIRED is False
    # ningún módulo del centro importa herramientas de nube ni ejecuta procesos externos
    for f in Path(B.__file__).parent.glob("*.py"):
        t = f.read_text()
        assert not re.search(r"^\s*(import|from)\s+(boto3|oci|subprocess|azure)\b", t, re.M), f.name
