"""Panel de operación (API de solo lectura): autenticación, autorización, ocultación de secretos y «No verificado» cuando no hay evidencia. Sin nubes; usa la base de pruebas local."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.failover.gate import WriteGate
from app.failover.lease import LeaseClient, LeaseConfig, init_lease
from app.failover.store import InMemoryStore
from app.main import create_app
from tests.conftest import TEST_APP_URL, login
from tests.test_api import register_client

SECRET_BITS = ["https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/PAR-SECRETO-ABCDEF/n/ns/b/bk/o/", "10.20.1.15", "129.151.20.33", "/Users/alguien/Workspace/NexoEventos/work/backups",
               "ocid1.bucket.oc1.sa-saopaulo-1.aaaabbbbcccc", "arn:aws:rds:us-east-1:123456789012:db:nexo", "AKIAABCDEFGHIJKLMNOP", "/etc/nexoeventos/backup-par.url"]


@pytest.fixture(autouse=True)
def _ops_allowlist(monkeypatch):
    monkeypatch.setenv("OPS_ALLOWED_EMAILS", "organizador@example.com")


def org(passwords, who="organizer", app=None):
    c = TestClient(app or create_app(TEST_APP_URL))
    login(c, {"organizer": "organizador@example.com", "organizer_other": "otro-organizador@example.com", "operator": "operador@example.com"}[who], passwords[who])
    return c


def now_iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_cycles(d, *recs):
    (d / "cycles.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")


# ───────────────────────────── autenticación y autorización ─────────────────────────────
def test_sin_sesion_401_y_roles_no_organizador_403(privileged_accounts):
    app = create_app(TEST_APP_URL)
    assert TestClient(app).get("/api/ops/overview").status_code == 401
    assert org(privileged_accounts, "operator", app).get("/api/ops/overview").status_code == 403
    with TestClient(app) as client:
        register_client(client)
        assert client.get("/api/ops/overview").status_code == 403


def test_organizador_accede_y_el_panel_es_solo_lectura(privileged_accounts):
    c = org(privileged_accounts)
    r = c.get("/api/ops/overview")
    assert r.status_code == 200 and r.json()["solo_lectura"] is True
    assert set(r.json()["secciones"]) == {"servicios", "respaldo", "lease", "compuerta", "failover"}
    for m in ("post", "put", "patch", "delete"):
        assert getattr(c, m)("/api/ops/overview").status_code in (403, 405)           # ningún método de escritura


def test_lista_de_correos_permitidos_limita_a_otros_organizadores(privileged_accounts, monkeypatch):
    monkeypatch.setenv("OPS_ALLOWED_EMAILS", "organizador@example.com")
    app = create_app(TEST_APP_URL)
    assert org(privileged_accounts, "organizer", app).get("/api/ops/overview").status_code == 200
    assert org(privileged_accounts, "organizer_other", app).get("/api/ops/overview").status_code == 403


@pytest.mark.parametrize("valor", [None, "", "   ", ",,", "sin-arroba", "otro@example.com"])
def test_lista_vacia_ausente_o_mal_configurada_deniega_incluso_al_organizador(privileged_accounts, monkeypatch, valor):
    if valor is None:
        monkeypatch.delenv("OPS_ALLOWED_EMAILS", raising=False)
    else:
        monkeypatch.setenv("OPS_ALLOWED_EMAILS", valor)
    r = org(privileged_accounts).get("/api/ops/overview")
    assert r.status_code == 403 and "organizador@example.com" not in r.text


def test_correo_permitido_sin_rol_organizador_sigue_denegado(privileged_accounts, monkeypatch):
    monkeypatch.setenv("OPS_ALLOWED_EMAILS", "operador@example.com")
    assert org(privileged_accounts, "operator").get("/api/ops/overview").status_code == 403


def test_correo_en_lista_se_compara_sin_distinguir_mayusculas(privileged_accounts, monkeypatch):
    monkeypatch.setenv("OPS_ALLOWED_EMAILS", " X@y.com , ORGANIZADOR@Example.com ")
    assert org(privileged_accounts).get("/api/ops/overview").status_code == 200


def test_panel_apagado_responde_404(privileged_accounts, monkeypatch):
    monkeypatch.setenv("OPS_PANEL_ENABLED", "0")
    assert org(privileged_accounts).get("/api/ops/overview").status_code == 404


# ───────────────────────────── «No verificado» sin evidencia ─────────────────────────────
def test_sin_fuentes_todo_lo_cloud_y_lo_sin_datos_es_no_verificado(privileged_accounts, monkeypatch):
    for v in ("OPS_BACKUP_STATE_DIR", "OPS_FAILOVER_DIR"): monkeypatch.delenv(v, raising=False)
    s = org(privileged_accounts).get("/api/ops/overview").json()["secciones"]
    assert s["respaldo"]["estado"] == "No verificado" and s["respaldo"]["origen"] == "sin_datos"
    assert s["failover"]["estado"] == "No verificado" and s["lease"]["estado"] == "No verificado" and s["compuerta"]["estado"] == "No verificado"
    sv = s["servicios"]["servicios"]
    assert sv["api"]["estado"] == "OK" and sv["base_de_datos"]["estado"] == "OK"
    for k in ("balanceador_aws", "rds_aws", "oci_recuperacion", "azure_monitoreo"):
        assert sv[k]["estado"] == "No verificado"                                        # nada cloud aparece sano por defecto
    assert s["servicios"]["estado"] != "OK"                                              # y el resumen tampoco es «OK»
    assert "WRITE_GATE_MODE=off" in s["compuerta"]["detalle"] and s["compuerta"]["modo"] == "off"


# ───────────────────────────── respaldo y RPO ─────────────────────────────
def test_respaldo_reciente_dentro_del_rpo(privileged_accounts, monkeypatch, tmp_path):
    write_cycles(tmp_path, {"ok": True, "env": "aws-academy", "name": "nexoeventos-rds-20261117T010203Z.cms", "finished_at": now_iso(10), "duration_s": 3.2, "cms_bytes": 92911, "cms_sha256": "a" * 64, "par": SECRET_BITS[0]})
    monkeypatch.setenv("OPS_BACKUP_STATE_DIR", str(tmp_path)); monkeypatch.setenv("OPS_BACKUP_MAX_AGE_MIN", "90")
    b = org(privileged_accounts).get("/api/ops/overview").json()["secciones"]["respaldo"]
    assert b["estado"] == "OK" and b["rpo"] == "dentro" and b["origen"] == "local" and 9 <= b["edad_min"] <= 12
    assert b["ultimo"] == {"nombre": "nexoeventos-rds-20261117T010203Z.cms", "entorno": "aws-academy", "terminado": b["ultimo"]["terminado"], "duracion_s": 3.2, "bytes": 92911}
    assert b["objeto_en_el_destino"] == "No verificado"                                  # un registro local NO prueba que el objeto exista en OCI
    assert "cms_sha256" not in json.dumps(b) and "par" not in b["ultimo"]


def test_respaldo_vencido_o_con_ultimo_intento_fallido(privileged_accounts, monkeypatch, tmp_path):
    monkeypatch.setenv("OPS_BACKUP_STATE_DIR", str(tmp_path))
    write_cycles(tmp_path, {"ok": True, "name": "a.cms", "finished_at": now_iso(500)})
    b = org(privileged_accounts).get("/api/ops/overview").json()["secciones"]["respaldo"]
    assert b["estado"] == "ERROR" and b["rpo"] == "vencido"
    write_cycles(tmp_path, {"ok": True, "name": "a.cms", "finished_at": now_iso(20)}, {"ok": False, "finished_at": now_iso(5), "error": "x"})
    b = org(privileged_accounts).get("/api/ops/overview").json()["secciones"]["respaldo"]
    assert b["estado"] == "ADVERTENCIA" and b["ultimo_intento_fallo"] is True
    write_cycles(tmp_path, {"ok": False, "finished_at": now_iso(5)})
    assert org(privileged_accounts).get("/api/ops/overview").json()["secciones"]["respaldo"]["estado"] == "ERROR"


def test_registro_corrupto_o_ausente_es_no_verificado(privileged_accounts, monkeypatch, tmp_path):
    monkeypatch.setenv("OPS_BACKUP_STATE_DIR", str(tmp_path))
    assert org(privileged_accounts).get("/api/ops/overview").json()["secciones"]["respaldo"]["estado"] == "No verificado"
    (tmp_path / "cycles.jsonl").write_text("no es json\n")
    assert org(privileged_accounts).get("/api/ops/overview").json()["secciones"]["respaldo"]["estado"] == "No verificado"


# ───────────────────────────── compuerta y lease ─────────────────────────────
class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t


def test_compuerta_activa_muestra_el_lease_local_y_la_perdida(privileged_accounts):
    clk = Clock(); st = InMemoryStore(); st.verified = True; init_lease(st)
    lease = LeaseClient(st, LeaseConfig(ttl_s=15, margin_s=5), holder_id="nodo", mono=clk); assert lease.acquire().ok
    app = create_app(TEST_APP_URL, write_gate=WriteGate(lease, "primary"))
    c = org(privileged_accounts, app=app)
    s = c.get("/api/ops/overview").json()["secciones"]
    assert s["compuerta"]["modo"] == "enforce" and s["compuerta"]["estado"] == "OK" and s["lease"]["titular_local"] is True and s["lease"]["epoca"] == 1
    assert s["lease"]["almacen_remoto"] == "No verificado"
    clk.t += 100                                                                          # el lease caduca: el panel (GET) sigue funcionando y lo muestra
    r = c.get("/api/ops/overview"); assert r.status_code == 200
    s = r.json()["secciones"]; assert s["compuerta"]["estado"] == "ADVERTENCIA" and s["lease"]["titular_local"] is False


# ───────────────────────────── failover y ocultación de secretos ─────────────────────────────
def test_failover_muestra_registro_y_ultima_ejecucion(privileged_accounts, monkeypatch, tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps({"state": "UNCERTAIN_DNS", "run_id": "r1", "epoch": 2}))
    (tmp_path / "last-run.json").write_text(json.dumps({"outcome": "ABORTED", "safe_state": "nuevo escritor activo; DNS INCIERTO", "origen": "simulado", "timeline": [["PRECHECK", 1.0], ["DECIDE", 2.0]]}))
    monkeypatch.setenv("OPS_FAILOVER_DIR", str(tmp_path))
    f = org(privileged_accounts).get("/api/ops/overview").json()["secciones"]["failover"]
    assert f["estado"] == "ERROR" and f["origen"] == "simulado" and f["registro"] == {"estado": "UNCERTAIN_DNS", "epoca": 2}
    assert f["ultima_ejecucion"]["etapas"] == ["PRECHECK", "DECIDE"] and f["failover_real_validado"] is False


def test_ningun_secreto_url_ip_ni_ruta_sale_en_la_respuesta(privileged_accounts, monkeypatch, tmp_path):
    ledger = {"state": "PROMOTED", "run_id": "r1", "epoch": 3, "par_url": SECRET_BITS[0], "token": "tok-secreto-1234567890"}
    last = {"outcome": "ABORTED", "safe_state": " | ".join(SECRET_BITS), "origen": "local", "timeline": [["PRECHECK", 1.0]], "key": "-----BEGIN PRIVATE KEY-----"}
    (tmp_path / "ledger.json").write_text(json.dumps(ledger)); (tmp_path / "last-run.json").write_text(json.dumps(last))
    write_cycles(tmp_path, {"ok": True, "name": SECRET_BITS[3] + "/nexoeventos-rds-x.cms", "env": SECRET_BITS[1], "finished_at": now_iso(5), "duration_s": 1, "cms_bytes": 10})
    monkeypatch.setenv("OPS_FAILOVER_DIR", str(tmp_path)); monkeypatch.setenv("OPS_BACKUP_STATE_DIR", str(tmp_path))
    body = org(privileged_accounts).get("/api/ops/overview").text
    for bit in SECRET_BITS + ["tok-secreto", "BEGIN PRIVATE", str(tmp_path)]:
        assert bit not in body, bit
    assert "[oculto]" in body


def test_la_ruta_de_la_api_no_escribe_nada_aunque_la_compuerta_este_cerrada(privileged_accounts):
    clk = Clock(); st = InMemoryStore(); st.verified = True; init_lease(st)
    gate = WriteGate(LeaseClient(st, LeaseConfig(ttl_s=15, margin_s=5), holder_id="nodo", mono=clk))     # nunca adquiere: compuerta cerrada
    app = create_app(TEST_APP_URL, write_gate=gate)
    # iniciar sesión es una escritura (503 con la compuerta cerrada): se prepara la sesión con la compuerta abierta y luego se cierra
    assert gate.lease.acquire().ok
    c = org(privileged_accounts, app=app); clk.t += 100
    assert c.get("/api/ops/overview").status_code == 200 and gate.blocked_sql == 0


def test_contrato_con_el_frontend_estados_y_origenes_permitidos(privileged_accounts):
    """El componente Operations.tsx interpreta estos valores; cualquier otro se muestra como «No verificado». Esta prueba fija el contrato del lado del servidor."""
    secs = org(privileged_accounts).get("/api/ops/overview").json()["secciones"]
    for name, s in secs.items():
        assert s["estado"] in {"OK", "ADVERTENCIA", "ERROR", "No verificado"}, name
        assert s["origen"] in {"local", "simulado", "cloud_verificado", "sin_datos"}, name
        assert isinstance(s["detalle"], str) and s["actualizado"].endswith("Z")
    assert all(v["estado"] in {"OK", "ADVERTENCIA", "ERROR", "No verificado"} for v in secs["servicios"]["servicios"].values())
    assert not any(s["origen"] == "cloud_verificado" for s in secs.values())                 # hoy nada se verifica contra la nube desde la API


def test_failover_muestra_alertas_y_la_recuperacion_aislada_con_tiempos_reales(privileged_accounts, monkeypatch, tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps({"state": "NONE"}))
    (tmp_path / "last-run.json").write_text(json.dumps({"outcome": "ABORTED", "safe_state": "sin escritor nuevo", "origen": "simulado", "timeline": [["PRECHECK", 1.0]],
                                                        "alerts": [{"severity": "critical", "message": "el primario SIGUE aceptando escrituras: promoción bloqueada"}]}))
    (tmp_path / "recovery-run.json").write_text(json.dumps({"respaldo": "nexoeventos-rds-20261119T055432Z", "origen": "local", "resultado": "OK", "etapas": {"descarga": 4.586, "restauracion": 0.343, "x": True},
                                                            "total_s": 6.69, "secreto": "https://objectstorage.example/p/TOKEN"}))
    monkeypatch.setenv("OPS_FAILOVER_DIR", str(tmp_path))
    f = org(privileged_accounts).get("/api/ops/overview").json()["secciones"]["failover"]
    assert f["estado"] == "ERROR"                                              # una alerta crítica no se muestra como sano
    assert f["ultima_ejecucion"]["alertas"][0]["severidad"] == "critical"
    r = f["recuperacion_aislada"]
    assert r["resultado"] == "OK" and r["origen"] == "local" and r["etapas_s"] == {"descarga": 4.586, "restauracion": 0.343} and r["total_s"] == 6.69
    assert "NO es el RTO" in r["nota"] and f["failover_real_validado"] is False
    assert "TOKEN" not in json.dumps(f) and "objectstorage" not in json.dumps(f)  # solo lista blanca


def test_recovery_status_escribe_solo_campos_validos(tmp_path):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "scripts/multicloud"))
    import recovery_status as rs
    p = rs.write(str(tmp_path), respaldo="nexoeventos-rds-20261119T055432Z", origen="local", resultado="OK", etapas={"descarga": 1.5, "restauracion": 0.5})
    assert oct(p.stat().st_mode & 0o777) == "0o600" and json.loads(p.read_text())["total_s"] == 2.0
    for malo in (dict(origen="cloud"), dict(resultado="X"), dict(respaldo="../x"), dict(etapas={"Mala": 1}), dict(etapas={"ok": -1}), dict(etapas={"ok": True})):
        kw = dict(respaldo="a", origen="local", resultado="OK", etapas={"ok": 1.0}); kw.update(malo)
        try:
            rs.write(str(tmp_path / "otro"), **kw)
        except ValueError:
            continue
        raise AssertionError(malo)


def test_panel_muestra_la_secuencia_del_incidente_con_clasificacion_vallado_y_modo(privileged_accounts, monkeypatch, tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps({"state": "NONE"}))
    (tmp_path / "last-run.json").write_text(json.dumps({
        "outcome": "DONE", "safe_state": "nuevo escritor activo y verificado", "origen": "simulado", "modo": "FAILOVER_AUTOMATICO",
        "timeline": [["PRECHECK", 0.0], ["DECIDE", 10.0], ["FENCE_CHECK", 32.0], ["HEALTH_GATE", 32.0], ["ENABLE_STANDBY", 32.0]],
        "incident": {"kind": "INSTANCE_DOWN", "promotable": True, "reasons": ["/livez falla y AWS confirma la EC2 stopped"], "signals": {"livez": False, "ec2": "stopped", "secreto": "https://x.example/p/TOK"}},
        "fencing": {"verdict": "FENCED", "evidence": [{"kind": "aws_instance", "strength": "verified", "detail": "la instancia del primario está stopped (API de AWS)"}]}}))
    monkeypatch.setenv("OPS_FAILOVER_DIR", str(tmp_path))
    f = org(privileged_accounts).get("/api/ops/overview").json()["secciones"]["failover"]
    u = f["ultima_ejecucion"]
    assert f["modo"] == "FAILOVER_AUTOMATICO" and f["origen"] == "simulado" and f["failover_real_validado"] is False       # nunca se declara validado por un archivo local
    assert u["incidente"]["clase"] == "INSTANCE_DOWN" and u["incidente"]["promovible"] is True and u["incidente"]["senales"]["ec2"] == "stopped"
    assert u["vallado"]["veredicto"] == "FENCED" and u["vallado"]["evidencia"][0] == {"tipo": "aws_instance", "fuerza": "verified", "detalle": "la instancia del primario está stopped (API de AWS)"}
    assert u["etapas"][2:5] == ["FENCE_CHECK", "HEALTH_GATE", "ENABLE_STANDBY"]
    assert "TOK" not in json.dumps(f) and "x.example" not in json.dumps(f)
    # un modo desconocido o ausente no se presenta como failover
    (tmp_path / "last-run.json").write_text(json.dumps({"outcome": "DONE", "origen": "simulado", "modo": "INVENTADO", "timeline": []}))
    assert org(privileged_accounts).get("/api/ops/overview").json()["secciones"]["failover"]["modo"] == "RECUPERACION_DESDE_RESPALDO"


def test_panel_compuerta_informa_el_vallado_en_la_base_solo_con_datos_del_proceso(privileged_accounts):
    from app.failover.gate import WriteGate
    from app.failover.lease import LeaseClient, LeaseConfig, init_lease
    from app.failover.store import InMemoryStore
    store = InMemoryStore(); store.verified = True; init_lease(store)
    gate = WriteGate(LeaseClient(store, LeaseConfig(ttl_s=15, margin_s=5), holder_id="p"), role="primary")
    gate.lease.acquire()
    from app.main import create_app
    from fastapi.testclient import TestClient
    app = create_app(write_gate=gate)
    c = TestClient(app); c.cookies.update(org(privileged_accounts).cookies)
    g = c.get("/api/ops/overview").json()["secciones"]["compuerta"]
    assert g["vallado_en_base"] == {"activo": False} and "SIN vallado en la base" in g["detalle"]               # sin pg_fence se dice, no se inventa
    class Fence:
        def grant(self, *a): pass
        def revoke(self, *a): pass
    gate.db_fence, gate.last_db_sync_ok, gate.db_sync_errors = Fence(), False, 2
    g = c.get("/api/ops/overview").json()["secciones"]["compuerta"]
    assert g["vallado_en_base"] == {"activo": True, "ultima_sincronizacion_ok": False, "errores_de_sincronizacion": 2} and g["estado"] == "ADVERTENCIA"   # una sincronización fallida NO se muestra como sana
