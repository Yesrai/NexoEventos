"""Cobertura de la compuerta de escritura: qué rutas y qué productores pasan (o NO pasan) por ella. Usa la base de datos de pruebas local; no toca nada real.
Si estas pruebas fallan tras un cambio, hay una nueva ruta/tarea/motor que puede escribir fuera de la compuerta: revisar app/failover/write_paths.py ANTES de aceptar el cambio."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.failover import write_paths as wp
from app.failover.gate import WriteFenceError, WriteGate, is_write_statement
from app.failover.lease import LeaseClient, LeaseConfig, init_lease
from app.failover.store import InMemoryStore
from app.main import create_app
from tests.conftest import admin_engine

ORIGIN = {"Origin": "http://testserver"}
APP_DIR = Path(__file__).resolve().parents[1] / "app"


class Clock:
    def __init__(self): self.t = 9000.0
    def __call__(self): return self.t
    def advance(self, s): self.t += s


def gated_app(holder_valid: bool):
    clock = Clock(); store = InMemoryStore(); store.verified = True; init_lease(store)
    lease = LeaseClient(store, LeaseConfig(ttl_s=15, margin_s=5), holder_id="primario", mono=clock)
    gate = WriteGate(lease, role="primary")
    if holder_valid:
        assert lease.acquire().ok
    return create_app(write_gate=gate), gate, clock, lease


# ───────────────────────────── inventario estático de productores ─────────────────────────────
def test_un_solo_motor_de_base_de_datos_y_ninguna_conexion_cruda():
    found = wp.scan_app_sources(APP_DIR)
    assert found["engine"] == wp.EXPECTED_ENGINE_FILES, f"hay otro create_engine() fuera de la compuerta: {found['engine']}"
    assert found["raw"] == set(), f"conexiones crudas que se saltan los eventos del Engine: {found['raw']}"


def test_no_hay_tareas_de_fondo_ni_procesos_nuevos_que_puedan_escribir():
    found = wp.scan_app_sources(APP_DIR)
    assert found["background"] <= wp.EXPECTED_BACKGROUND_FILES, f"nuevas tareas de fondo/hilos sin revisar: {found['background'] - wp.EXPECTED_BACKGROUND_FILES}"
    assert found["subprocess"] <= wp.EXPECTED_SUBPROCESS_FILES, f"nuevos subprocesos: {found['subprocess'] - wp.EXPECTED_SUBPROCESS_FILES}"


def test_el_inventario_declara_los_productores_externos_y_los_limites():
    assert {w["nombre"] for w in wp.KNOWN_EXTERNAL_WRITERS} >= {"migraciones Alembic", "administración manual"}
    assert any("off" in l for l in wp.KNOWN_LIMITS) and any("independientes" in l for l in wp.KNOWN_LIMITS)
    # cada ruta declarada existe de verdad en el repositorio (el inventario no puede quedar obsoleto sin que alguien lo note)
    root = APP_DIR.parents[1]
    for w in wp.KNOWN_EXTERNAL_WRITERS:
        first = w["ruta"].split(",")[0].split(" + ")[0].split(" ")[0]
        if first.startswith(("backend/", "scripts/", "deploy/")):
            assert (root / first.rstrip("/")).exists() or list(root.glob(first + "*")), f"la ruta del inventario no existe: {first}"


# ───────────────────────────── rutas HTTP ─────────────────────────────
def test_toda_ruta_de_escritura_devuelve_503_sin_lease_antes_de_llegar_a_la_aplicacion():
    app, gate, clock, lease = gated_app(holder_valid=False)
    inv = wp.route_inventory(app)
    unsafe = [r for r in inv if any(m not in wp.SAFE_METHODS for m in r["metodos"])]
    assert len(unsafe) >= 8, "se esperan al menos 8 rutas de escritura en la API"
    with TestClient(app) as c:
        for r in unsafe:
            path = re.sub(r"\{[^}]+\}", "1", r["ruta"])
            for m in (m for m in r["metodos"] if m not in wp.SAFE_METHODS):
                resp = c.request(m, path, headers=ORIGIN, json={})
                assert resp.status_code == 503 and resp.json().get("code") == "write_gate_closed", (m, path, resp.status_code)
    assert gate.blocked_http >= len(unsafe)


def test_las_lecturas_anonimas_funcionan_sin_lease_y_no_ejecutan_escrituras():
    app, gate, clock, lease = gated_app(holder_valid=True)
    writes = []
    @event.listens_for(app.state.engine, "before_cursor_execute")
    def spy(conn, cursor, statement, *a):
        if is_write_statement(statement): writes.append(statement)
    lease_valid_calls = []
    with TestClient(app) as c:
        for p in ("/health", "/ready", "/api/events", "/api/auth/session"):
            c.get(p)
    assert writes == [], f"una lectura ejecutó escrituras: {writes}"
    clock.advance(100)                                              # sin lease: las lecturas siguen funcionando (la base sigue disponible para consultar)
    with TestClient(app) as c:
        assert c.get("/api/events").status_code == 200
        assert c.get("/health").status_code == 200


def test_todas_las_rutas_get_declaradas_estan_clasificadas_como_lectura_con_guardia_de_bd():
    app, *_ = gated_app(holder_valid=False)
    for r in wp.route_inventory(app):
        if all(m in wp.SAFE_METHODS for m in r["metodos"]) and r["metodos"]:
            assert "guardia de BD" in r["clase"]


# ───────────────────────────── guardia de base de datos: rutas alternativas ─────────────────────────────
@pytest.fixture
def engine_with_gate():
    app, gate, clock, lease = gated_app(holder_valid=True)
    yield app.state.engine, gate, clock, lease
    with admin_engine.begin() as c:
        c.execute(text("DELETE FROM auth_rate_limits WHERE key_hash LIKE 'cov-%'"))


INSERT = "INSERT INTO auth_rate_limits (key_hash, failed_count, window_started_at) VALUES ('cov-1', 1, now())"


def count(key="cov-1"):
    with admin_engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM auth_rate_limits WHERE key_hash = :k"), {"k": key}).scalar()


def test_engine_begin_sin_session_tambien_comprueba_el_commit(engine_with_gate):
    eng, gate, clock, lease = engine_with_gate
    with pytest.raises(WriteFenceError):
        with eng.begin() as conn:
            conn.execute(text(INSERT))
            clock.advance(100)                                       # el lease caduca entre la sentencia y el commit, SIN Session
    assert count() == 0                                              # no se persistió nada
    clock.advance(0); assert lease.acquire() is not None


def test_engine_begin_con_lease_valido_si_escribe(engine_with_gate):
    eng, gate, clock, lease = engine_with_gate
    with eng.begin() as conn:
        conn.execute(text(INSERT))
    assert count() == 1


def test_la_marca_de_escritura_no_se_filtra_entre_usos_del_pool(engine_with_gate):
    eng, gate, clock, lease = engine_with_gate
    with eng.begin() as conn:
        conn.execute(text(INSERT))
    clock.advance(100)                                               # sin lease: una transacción de SOLO lectura posterior debe poder terminar
    with eng.begin() as conn:
        conn.execute(text("SELECT 1"))


@pytest.mark.parametrize("sql", [
    "INSERT INTO auth_rate_limits VALUES (1)", "UPDATE users SET display_name='x'", "DELETE FROM users", "TRUNCATE users", "ALTER TABLE users ADD COLUMN x int",
    "SELECT nextval('events_id_seq')", "SELECT setval('events_id_seq', 5)", "DO $$ BEGIN PERFORM 1; END $$", "CALL algun_procedimiento()", "SELECT * INTO nueva FROM users",
    "WITH x AS (INSERT INTO users DEFAULT VALUES RETURNING id) SELECT * FROM x", "EXECUTE plan_guardado", "NOTIFY canal", "SELECT * FROM events FOR UPDATE", "COPY users FROM STDIN",
    "REFRESH MATERIALIZED VIEW vista", "LOCK TABLE users",
])
def test_cualquier_sentencia_que_pueda_escribir_se_rechaza_sin_lease(engine_with_gate, sql):
    eng, gate, clock, lease = engine_with_gate
    clock.advance(100)
    assert is_write_statement(sql)
    with pytest.raises(WriteFenceError):
        with eng.connect() as conn:
            conn.exec_driver_sql(sql)                                # se rechaza ANTES de enviarla al servidor (before_cursor_execute)


@pytest.mark.parametrize("sql", ["SELECT refresh_token FROM t", "SELECT 'do it' AS x", "SELECT id FROM events WHERE name = 'insert into'", "SELECT count(*) FROM users -- delete",
                                 "SELECT updated_at, created_at FROM events", "SELECT 1"])
def test_las_lecturas_no_se_marcan_como_escritura(sql):
    assert not is_write_statement(sql)


def test_limite_una_funcion_con_efectos_laterales_no_se_detecta_por_texto():
    """LÍMITE DECLARADO (write_paths.KNOWN_LIMITS): el texto SQL no revela qué hace una función. Si existiera, esta llamada NO se bloquearía por la guardia."""
    assert not is_write_statement("SELECT mi_funcion_que_escribe()")
