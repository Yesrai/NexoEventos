import json

import pytest

from nexoops.actions import ActionError, Actions


def test_parametros_fuera_de_lista_blanca_se_rechazan_y_auditan(authed, app):
    r = authed.post("/api/actions", json={"name": "status.refresh", "params": {"cmd": "id"}})
    assert r.status_code == 400
    event = [e for e in app.state.audit.entries() if e["event"] == "status.refresh"][-1]
    assert event["data"]["resultado"] == "rechazada_parametros"
    assert event["data"]["evidencia"]["campos_no_permitidos"] == ["cmd"]


def test_limite_de_frecuencia_tambien_queda_auditado(authed, app):
    payload = {"name": "service.restart.request", "confirm": True,
               "params": {"service": "ops-center", "reason": "validación académica local"}}
    assert [authed.post("/api/actions", json=payload).status_code for _ in range(4)] == [200, 200, 200, 429]
    events = [e for e in app.state.audit.entries() if e["event"] == "service.restart.request"]
    assert events[-1]["data"]["resultado"] == "rechazada_limite"


def test_solicitud_se_guarda_0600_y_archivo_corrupto_no_rompe_listado(authed, cfg):
    r = authed.post("/api/actions", json={"name": "service.restart.request", "confirm": True,
                                          "params": {"service": "ops-center", "reason": "validación académica local"}})
    assert r.status_code == 200
    files = list((cfg.data_dir / "intervention-requests").glob("ir-*.json"))
    assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600
    assert json.loads(files[0].read_text())["state"] == "BLOQUEADA_REQUIERE_APROBACION_INDEPENDIENTE"
    (cfg.data_dir / "intervention-requests" / "ir-corrupta.json").write_text("{")
    assert authed.get("/api/incidents").status_code == 200


def test_acciones_exigen_super_admin_incluso_fuera_del_endpoint(cfg, app):
    actions = Actions(cfg, app.state.audit, {})
    with pytest.raises(ActionError) as exc:
        actions.run({"email": "lector@example.test", "role": "LECTOR"}, "status.refresh", {}, False, "rq-test")
    assert exc.value.code == 403
    event = [e for e in app.state.audit.entries() if e["event"] == "status.refresh"][-1]
    assert event["data"]["resultado"] == "rechazada_rol"


def test_asg_falla_cerrado_sin_lista_blanca(cfg, app):
    actions = Actions(cfg, app.state.audit, {"aws": object()})
    with pytest.raises(ActionError) as exc:
        actions.run({"email": "ti@example.test", "role": "SUPER_ADMIN_TI"}, "aws.asg_activities", {"asg": "cualquiera"}, False, "rq-test")
    assert exc.value.code == 409


def test_error_de_dependencia_no_filtra_excepcion_y_se_audita(cfg, app):
    def broken():
        raise RuntimeError("token-secreto-no-debe-salir")
    actions = Actions(cfg, app.state.audit, {"cloud_overview": broken})
    with pytest.raises(ActionError) as exc:
        actions.run({"email": "ti@example.test", "role": "SUPER_ADMIN_TI"}, "status.refresh", {}, False, "rq-test")
    assert exc.value.code == 502 and "token-secreto" not in str(exc.value)
    event = [e for e in app.state.audit.entries() if e["event"] == "status.refresh"][-1]
    assert event["data"]["resultado"] == "error_interno"

