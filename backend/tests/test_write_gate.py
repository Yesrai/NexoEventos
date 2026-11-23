"""B-11 · Pruebas de la compuerta de escritura (fail-closed) con lease simulado. Sin red ni nubes; usa la base de datos de pruebas local."""
import threading
import time
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_session
from app.failover.gate import WriteFenceError, WriteGate, build_gate_from_env, is_write_statement
from app.failover.lease import LeaseClient, LeaseConfig, init_lease
from app.failover.store import FileStore, InMemoryStore, StoreUnavailable
from app.main import create_app
from tests.conftest import admin_engine

ORIGIN = {"Origin": "http://testserver"}


class Clock:
    def __init__(self): self.t = 5000.0
    def __call__(self): return self.t
    def advance(self, s): self.t += s


def new_store():
    s = InMemoryStore(); s.verified = True; init_lease(s); return s


def gate_for(store, clock, name, role="primary", **kw):
    return WriteGate(LeaseClient(store, LeaseConfig(ttl_s=15, margin_s=5), holder_id=name, mono=clock), role=role, **kw)


def register(client, email):
    return client.post("/api/auth/register", headers=ORIGIN, json={"email": email, "display_name": "Cliente", "password": "Contrasena-segura-123!"})


def users_count():
    with admin_engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM users")).scalar()


def fila_prueba():
    with admin_engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM auth_rate_limits WHERE key_hash = 'gate-test-99001'")).scalar()


def add_test_routes(app):
    @app.post("/test/escribir")
    def escribir(session: Session = Depends(get_session)):
        session.execute(text("INSERT INTO auth_rate_limits (key_hash, failed_count, window_started_at) VALUES ('gate-test-99001', 1, now())"))
        session.commit()
        return {"ok": True}

    @app.post("/test/escribir-y-caducar")
    def escribir_y_caducar(session: Session = Depends(get_session)):
        session.execute(text("INSERT INTO auth_rate_limits (key_hash, failed_count, window_started_at) VALUES ('gate-test-99001', 1, now())"))
        app.state.clock_to_advance.advance(100)          # el lease caduca MIENTRAS se atiende la petición (entre la sentencia y el commit)
        session.commit()
        return {"ok": True}
    return app


# ------------------------------------------------------------------ valor por defecto: sin cambios
def test_apagada_por_defecto_no_cambia_el_comportamiento(monkeypatch):
    monkeypatch.delenv("WRITE_GATE_MODE", raising=False)
    app = create_app()
    assert not hasattr(app.state, "write_gate")
    c = TestClient(app)
    assert register(c, "defecto@example.com").status_code == 201
    assert c.get("/write-gate").status_code == 404


# ------------------------------------------------------------------ sin lease / con lease / expiración / pérdida
def test_sin_lease_rechaza_escrituras_y_permite_lecturas_y_salud():
    clk, store = Clock(), new_store()
    app = create_app(write_gate=gate_for(store, clk, "A")); c = TestClient(app)          # nunca adquirió el lease
    r = register(c, "x@example.com")
    assert r.status_code == 503 and r.json()["code"] == "write_gate_closed" and r.headers["retry-after"] == "5"
    assert users_count() == 0                                                            # no se persistió nada
    assert c.get("/api/events").status_code == 200 and c.get("/health").status_code == 200 and c.get("/ready").status_code == 200
    s = c.get("/write-gate").json(); assert s["holds_lease"] is False and s["epoch"] is None


def test_con_lease_permite_escribir_y_expira_cerrando():
    clk, store = Clock(), new_store(); gate = gate_for(store, clk, "A"); app = create_app(write_gate=gate); c = TestClient(app)
    gate.keeper_step()
    assert register(c, "a1@example.com").status_code == 201 and c.get("/write-gate").json()["holds_lease"] is True
    clk.advance(9.9); assert register(c, "a2@example.com").status_code == 201             # aún dentro de ttl − margen (10 s)
    clk.advance(0.2)
    assert register(c, "a3@example.com").status_code == 503 and users_count() == 2         # EXPIRADO: se cierra aunque nadie haya llamado al lease
    assert c.get("/api/events").status_code == 200                                         # las lecturas siguen
    gate.keeper_step(); assert register(c, "a4@example.com").status_code == 201            # el guardián renueva (nadie tomó el lease) y se reabre


def test_perdida_del_lease_cierra_definitivamente_al_titular_anterior():
    clk, store = Clock(), new_store()
    ga, gb = gate_for(store, clk, "A"), gate_for(store, clk, "B")
    ca, cb = TestClient(create_app(write_gate=ga)), TestClient(create_app(write_gate=gb))
    ga.keeper_step(); gb.keeper_step()                                                       # B observa
    clk.advance(21); gb.keeper_step()                                                        # B toma (A no renovó)
    assert gb.allows_writes() and not ga.allows_writes()
    assert register(cb, "b1@example.com").status_code == 201 and register(ca, "a-viejo@example.com").status_code == 503
    ga.keeper_step()                                                                         # A intenta renovar: CAS con ETag viejo → perdido
    assert ga.status()["lost"] is True and register(ca, "a-viejo2@example.com").status_code == 503 and users_count() == 1


# ------------------------------------------------------------------ capa de BD y commit
def test_sentencia_de_escritura_sin_lease_se_rechaza_en_la_capa_de_bd_aunque_se_salte_http():
    clk, store = Clock(), new_store(); gate = gate_for(store, clk, "A"); app = add_test_routes(create_app(write_gate=gate))
    # Se salta la capa HTTP (como si una ruta GET escribiera): se llama a la función de BD directamente
    with app.state.session_factory() as session:
        with pytest.raises(WriteFenceError):
            session.execute(text("INSERT INTO auth_rate_limits (key_hash, failed_count, window_started_at) VALUES ('gate-test-99001', 1, now())"))
        assert session.execute(text("SELECT 1")).scalar() == 1                                 # las lecturas pasan
    assert fila_prueba() == 0 and gate.blocked_sql == 1


def test_commit_se_aborta_si_el_lease_caduca_durante_la_peticion():
    clk, store = Clock(), new_store(); gate = gate_for(store, clk, "A"); app = add_test_routes(create_app(write_gate=gate)); app.state.clock_to_advance = clk
    c = TestClient(app); gate.keeper_step()
    assert c.post("/test/escribir", headers=ORIGIN).status_code == 200 and fila_prueba() == 1       # con lease: se persiste
    with admin_engine.begin() as conn: conn.execute(text("DELETE FROM auth_rate_limits WHERE key_hash = 'gate-test-99001'"))
    gate.keeper_step()
    r = c.post("/test/escribir-y-caducar", headers=ORIGIN)
    assert r.status_code == 503 and r.json()["code"] == "write_gate_closed"
    assert fila_prueba() == 0 and gate.blocked_commit == 1                                         # el INSERT se hizo pero el COMMIT se abortó: nada persistió


# ------------------------------------------------------------------ doble escritura
def test_dos_instancias_misma_base_nunca_ambas_escriben_y_el_traspaso_es_limpio():
    clk, store = Clock(), new_store()
    ga, gb = gate_for(store, clk, "A"), gate_for(store, clk, "B")
    ca, cb = TestClient(create_app(write_gate=ga)), TestClient(create_app(write_gate=gb))
    ga.keeper_step(); gb.keeper_step()
    codes = {"A": [], "B": []}; lock = threading.Lock()
    def go(who, client, i):
        r = register(client, f"{who.lower()}{i}@example.com")
        with lock: codes[who].append(r.status_code)
    ts = [threading.Thread(target=go, args=(w, c, i)) for i in range(15) for w, c in (("A", ca), ("B", cb))]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert set(codes["A"]) == {201} and set(codes["B"]) == {503}                            # SOLO el titular escribe
    assert users_count() == 15
    # A deja de renovar (partición): su lease caduca por su reloj; B observa, espera y toma
    clk.advance(10.1); assert not ga.allows_writes() and not gb.allows_writes()             # hay un hueco sin escritor (consistencia sobre disponibilidad)
    assert register(ca, "hueco-a@example.com").status_code == 503 and register(cb, "hueco-b@example.com").status_code == 503
    clk.advance(15); gb.keeper_step()
    assert gb.allows_writes() and not ga.allows_writes()
    assert register(cb, "b-nuevo@example.com").status_code == 201 and register(ca, "a-tarde@example.com").status_code == 503
    assert users_count() == 16


def test_hueco_cuando_el_almacen_del_lease_cae_nadie_escribe_tras_la_expiracion():
    clk, store = Clock(), new_store(); gate = gate_for(store, clk, "A"); c = TestClient(create_app(write_gate=gate)); gate.keeper_step()
    store.before_op = lambda op: (_ for _ in ()).throw(StoreUnavailable("partición"))
    for _ in range(5):
        clk.advance(2.5); gate.keeper_step()                                                  # renovaciones fallidas: la validez NO se amplía
    assert register(c, "caido@example.com").status_code == 503                                # A está sano pero NO escribe: disponibilidad sacrificada


# ------------------------------------------------------------------ standby y guardián
def test_standby_solo_escribe_con_archivo_de_promocion(tmp_path):
    clk, store = Clock(), new_store(); promo = tmp_path / "promover"
    gate = gate_for(store, clk, "S", role="standby", promote_file=str(promo)); c = TestClient(create_app(write_gate=gate))
    gate.keeper_step(); assert register(c, "s0@example.com").status_code == 503
    promo.write_text("ok"); gate.keeper_step(); assert register(c, "s1@example.com").status_code == 201
    promo.unlink(); gate.keeper_step()
    assert register(c, "s2@example.com").status_code == 503                                    # sin promoción: libera y deja de escribir
    other = gate_for(store, clk, "P"); other.keeper_step(); assert not other.allows_writes()   # una liberación SIN firma no da atajo (pudo escribirla cualquiera): se observa ttl+margen
    clk.advance(30); other.keeper_step(); assert other.allows_writes()


def test_guardian_con_hilo_renueva_y_si_muere_el_lease_caduca_y_cierra():
    store = new_store()
    lease = LeaseClient(store, LeaseConfig(ttl_s=1.5, margin_s=0.5), holder_id="H")           # reloj real
    gate = WriteGate(lease, keeper_interval_s=0.1); c = TestClient(create_app(write_gate=gate))
    gate.start()
    for _ in range(40):
        if gate.allows_writes(): break
        time.sleep(0.05)
    assert register(c, "h1@example.com").status_code == 201
    time.sleep(1.4); assert gate.allows_writes()                                              # sigue renovando más allá del ttl
    gate._stop.set(); gate._thread.join(2)                                                    # el guardián «muere» sin liberar
    time.sleep(1.2); assert register(c, "h2@example.com").status_code == 503                  # caducó solo → falla cerrada
    gate.lease.release()


# ------------------------------------------------------------------ configuración y utilidades
def test_configuracion_desde_entorno(tmp_path):
    assert build_gate_from_env({}) is None and build_gate_from_env({"WRITE_GATE_MODE": "off"}) is None
    with pytest.raises(RuntimeError): build_gate_from_env({"WRITE_GATE_MODE": "quizas"})
    with pytest.raises(RuntimeError): build_gate_from_env({"WRITE_GATE_MODE": "enforce"})                       # sin almacén
    with pytest.raises(RuntimeError): build_gate_from_env({"WRITE_GATE_MODE": "enforce", "WRITE_GATE_STORE": "file", "WRITE_GATE_FILE_PATH": str(tmp_path / "l"), "APP_ENV": "production"})
    with pytest.raises(RuntimeError): build_gate_from_env({"WRITE_GATE_MODE": "enforce", "WRITE_GATE_STORE": "oci-cli"})                  # faltan namespace/bucket
    with pytest.raises(ValueError): build_gate_from_env({"WRITE_GATE_MODE": "enforce", "WRITE_GATE_STORE": "file", "WRITE_GATE_FILE_PATH": str(tmp_path / "l2"), "WRITE_GATE_ROLE": "otro"})
    g = build_gate_from_env({"WRITE_GATE_MODE": "enforce", "WRITE_GATE_STORE": "file", "WRITE_GATE_FILE_PATH": str(tmp_path / "l3"), "WRITE_GATE_ROLE": "standby"})
    assert g.role == "standby" and g.lease.store.verified and not g.allows_writes()
    with pytest.raises(Exception): build_gate_from_env({"WRITE_GATE_MODE": "enforce", "WRITE_GATE_STORE": "file", "WRITE_GATE_FILE_PATH": str(tmp_path / "l4"), "WRITE_GATE_MARGIN_S": "0.1"})   # margen < ρ·ttl: configuración insegura rechazada


@pytest.mark.parametrize("sql,esperado", [
    ("SELECT 1", False), ("select * from events where id = 1", False), ("SHOW server_version", False), ("SET statement_timeout = 5000", False),
    ("SELECT * FROM t WHERE name = 'update me'", False), ("SELECT 1 -- delete everything", False), ("/* insert */ SELECT 1", False),
    ("INSERT INTO t VALUES (1)", True), ("update t set a = 1", True), ("DELETE FROM t", True), ("WITH x AS (UPDATE t SET a=1 RETURNING *) SELECT * FROM x", True),
    ("SELECT * FROM t FOR UPDATE", True), ("CREATE TABLE z (a int)", True), ("TRUNCATE t", True), ("INSERT INTO t VALUES ('a''b') ON CONFLICT DO UPDATE SET a=1", True),
])
def test_clasificacion_de_sentencias(sql, esperado):
    assert is_write_statement(sql) is esperado
