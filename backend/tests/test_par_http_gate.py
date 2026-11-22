"""Compuerta de escritura con el lease en un almacén HTTP condicional (ParHttpStore) contra un servidor FALSO que imita If-Match / If-None-Match / ETag de OCI Object Storage.
Sin red externa ni OCI real. Cubre: autoprueba obligatoria al arrancar, aislamiento del almacén, resultado incierto, toma por otra instancia, primario recuperado, carrera de instancias
y —como LÍMITE explícito— un servicio que ignora las condiciones. No demuestra coordinación distribuida real (solo contra OCI)."""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.failover.gate import WriteFenceError, WriteGate, build_gate_from_env
from app.failover.lease import LeaseClient, LeaseConfig, init_lease
from app.failover.store import ParHttpStore, build_verified_par_store
from app.main import create_app
from tests.conftest import admin_engine

SECRET = "PAR-GATE-INVENTADO-SOLO-PRUEBAS-31"
ORIGIN = {"Origin": "http://testserver"}


class Srv:
    def __init__(self): self.lock = threading.Lock(); self.reset()
    def reset(self): self.objs = {}; self.n = 0; self.enforce = True; self.down = False; self.apply_then_503 = 0; self.puts = 0


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body=b"", etag=None):
        self.send_response(code)
        if etag: self.send_header("ETag", etag)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        s = self.server.s
        if not self.path.startswith(f"/p/{SECRET}/"): return self._send(404)
        if s.down: return self._send(503)
        with s.lock:
            o = s.objs.get(self.path)
            self._send(404) if o is None else self._send(200, o[0], o[1])
    def do_PUT(self):
        s = self.server.s; body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not self.path.startswith(f"/p/{SECRET}/"): return self._send(403)
        if s.down: return self._send(503)
        inm, im = self.headers.get("If-None-Match"), self.headers.get("If-Match")
        with s.lock:
            cur = s.objs.get(self.path)
            if s.enforce:
                if inm == "*" and cur is not None: return self._send(412)
                if im is not None and (cur is None or im != cur[1]): return self._send(412)
            s.n += 1; s.puts += 1; s.objs[self.path] = (body, f"v{s.n}")
            if s.apply_then_503 > 0: s.apply_then_503 -= 1; return self._send(503)
            self._send(200, b"", f"v{s.n}")


class Clock:
    def __init__(self, off=0.0, rate=1.0): self.t = 0.0; self.off = off; self.rate = rate
    def __call__(self): return self.rate * self.t + self.off


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    s = ThreadingHTTPServer(("127.0.0.1", 0), H); s.s = Srv()
    threading.Thread(target=s.serve_forever, daemon=True).start()
    d = tmp_path_factory.mktemp("par"); par = d / "lease.url"
    par.write_text(f"http://127.0.0.1:{s.server_port}/p/{SECRET}/n/ns/b/bk/o/"); os.chmod(par, 0o600)
    s.par = par
    yield s
    s.shutdown(); s.server_close()


@pytest.fixture
def S(srv):
    srv.s.reset(); return srv.s


def verified_store(srv, **kw):
    store, rep = build_verified_par_store(srv.par, "writer-lease.json", allow_http_localhost=True, **kw)
    return store, rep


def new_gate(srv, name, clock, role="primary", init=False):
    store, rep = verified_store(srv)
    assert store.verified, rep
    if init: init_lease(store)
    return WriteGate(LeaseClient(store, LeaseConfig(ttl_s=15, margin_s=5), holder_id=name, mono=clock), role=role)


# ───────────────────────────── autoprueba obligatoria ─────────────────────────────
def test_la_autoprueba_pasa_con_un_servicio_que_respeta_las_condiciones(srv, S):
    store, rep = verified_store(srv)
    assert store.verified and all(rep.values()), rep


def test_un_servicio_que_ignora_las_condiciones_no_queda_verificado_y_el_lease_lo_rechaza(srv, S):
    S.enforce = False
    store, rep = verified_store(srv)
    assert not store.verified and not all(rep.values())
    r = LeaseClient(store, LeaseConfig(), "A", Clock()).acquire()
    assert not r.ok and "NO verificado" in r.reason


def test_servicio_caido_o_url_invalida_no_verifica(srv, S):
    S.down = True
    store, rep = verified_store(srv)
    assert not store.verified


def _env(srv, **extra):
    return {"WRITE_GATE_MODE": "enforce", "WRITE_GATE_STORE": "par-http", "WRITE_GATE_PAR_URL_FILE": str(srv.par), "WRITE_GATE_ALLOW_HTTP_LOCALHOST": "1", "APP_ENV": "development", **extra}


def test_arranque_con_par_http_exige_autoprueba_y_nunca_degrada_en_silencio(srv, S):
    gate = build_gate_from_env(_env(srv))
    assert isinstance(gate, WriteGate) and gate.lease.store.verified
    S.enforce = False
    with pytest.raises(RuntimeError, match="autoprueba"):
        build_gate_from_env(_env(srv))
    S.enforce = True; S.down = True
    with pytest.raises(RuntimeError):
        build_gate_from_env(_env(srv))


def test_configuracion_invalida_no_filtra_la_url_ni_arranca(srv, S, tmp_path):
    with pytest.raises(RuntimeError, match="WRITE_GATE_PAR_URL_FILE"):
        build_gate_from_env({"WRITE_GATE_MODE": "enforce", "WRITE_GATE_STORE": "par-http"})
    bad = tmp_path / "u"; bad.write_text(f"http://ejemplo.invalid/p/{SECRET}/o/"); os.chmod(bad, 0o600)
    with pytest.raises(RuntimeError) as e:
        build_gate_from_env(_env(srv, WRITE_GATE_PAR_URL_FILE=str(bad)))
    assert SECRET not in str(e.value)
    open_perm = tmp_path / "v"; open_perm.write_text(srv.par.read_text()); os.chmod(open_perm, 0o644)
    with pytest.raises(RuntimeError):
        build_gate_from_env(_env(srv, WRITE_GATE_PAR_URL_FILE=str(open_perm)))
    with pytest.raises(RuntimeError, match="file, oci-cli o par-http"):
        build_gate_from_env({"WRITE_GATE_MODE": "enforce", "WRITE_GATE_STORE": "otro"})


def test_off_sigue_siendo_el_valor_por_defecto(monkeypatch):
    monkeypatch.delenv("WRITE_GATE_MODE", raising=False)
    assert build_gate_from_env({}) is None


# ───────────────────────────── lease por HTTP: seguridad de escritura ─────────────────────────────
def test_primario_aislado_del_almacen_deja_de_escribir_al_caducar(srv, S):
    clk = Clock(); g = new_gate(srv, "primario", clk, init=True); assert g.lease.acquire().ok and g.allows_writes()
    S.down = True
    for _ in range(20):
        clk.t += 1.0; g.keeper_step()
    assert not g.allows_writes()                                        # sin poder renovar, el plazo local se agota por su propio reloj
    S.down = False; clk.t += 1.0; g.keeper_step()
    assert g.allows_writes()                                            # si nadie más lo tomó, el titular vuelve a renovar


def test_resultado_incierto_no_extiende_la_validez(srv, S):
    clk = Clock(); g = new_gate(srv, "primario", clk, init=True); assert g.lease.acquire().ok
    clk.t += 4.0; S.apply_then_503 = 1; g.keeper_step()                 # el servidor aplicó la renovación pero respondió 503
    clk.t += 12.0
    assert not g.allows_writes()                                        # sin confirmación no hay validez: falla seguro
    assert g.lease.acquire().ok                                         # luego adopta su propia escritura incierta


def test_otra_instancia_toma_el_lease_y_el_primario_recuperado_no_vuelve_a_escribir(srv, S):
    ca, cb = Clock(1000.0, 1.03), Clock(-500.0, 0.97)
    a = new_gate(srv, "A", ca, init=True); b = new_gate(srv, "B", cb)
    assert a.lease.acquire().ok
    b.lease.acquire()
    for _ in range(26):                                                 # A deja de renovar (proceso congelado); B observa hasta que caduca
        ca.t += 1.0; cb.t += 1.0; b.lease.acquire()
    assert b.allows_writes() and not a.allows_writes()
    assert not (a.allows_writes() and b.allows_writes())
    a.keeper_step()                                                     # A se reanuda con su lease viejo en memoria y reintenta renovar: pierde
    assert not a.allows_writes() and a.lease.status()["lost"] is True
    for _ in range(40):
        ca.t += 1.0; cb.t += 1.0; b.keeper_step(); a.keeper_step()
        assert not (a.allows_writes() and b.allows_writes())            # nunca dos escritores a la vez


def test_carrera_de_8_instancias_un_solo_ganador(srv, S):
    store, _ = verified_store(srv); init_lease(store)
    gates = [new_gate(srv, f"N{i}", Clock()) for i in range(8)]
    wins = []
    def go(g):
        if g.lease.acquire().ok: wins.append(g)
    ts = [threading.Thread(target=go, args=(g,)) for g in gates]; [t.start() for t in ts]; [t.join() for t in ts]
    assert len(wins) == 1 and sum(g.allows_writes() for g in gates) == 1


def test_limite_sin_autoprueba_un_servicio_que_ignora_if_match_permite_dos_escritores(srv, S):
    """LÍMITE DECLARADO: si alguien marca `verified=True` a mano (saltándose la autoprueba) sobre un servicio que ignora If-Match, DOS instancias creen tener el lease.
    Por eso la autoprueba es obligatoria en el arranque (no hay variable para omitirla) y el orquestador la repite antes de adquirir."""
    store, _ = verified_store(srv); init_lease(store)
    S.enforce = False
    def mk(name, clk):
        st = ParHttpStore(srv.par, object_name="writer-lease.json", allow_http_localhost=True); st.verified = True      # ← la trampa
        return WriteGate(LeaseClient(st, LeaseConfig(ttl_s=15, margin_s=5), holder_id=name, mono=clk))
    a, b = mk("A", Clock()), mk("B", Clock())
    barrier = threading.Barrier(2, timeout=10)
    for g in (a, b):                                                    # ambos leen el MISMO ETag y recién entonces escriben (carrera real)
        orig = g.lease.store.read
        g.lease.store.read = lambda orig=orig: (lambda v: (barrier.wait(), v)[1])(orig())
    res = {}
    ts = [threading.Thread(target=lambda g=g, k=k: res.__setitem__(k, g.lease.acquire())) for k, g in (("A", a), ("B", b))]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert res["A"].ok and res["B"].ok and a.allows_writes() and b.allows_writes()     # dos escritores: el lease NO protege sin condiciones atómicas en el servidor


# ───────────────────────────── escritura real: HTTP + base de datos con el lease HTTP ─────────────────────────────
def test_la_api_rechaza_escrituras_cuando_el_lease_http_se_pierde(srv, S):
    clk = Clock(); g = new_gate(srv, "primario", clk, init=True); assert g.lease.acquire().ok
    app = create_app(write_gate=g)
    with TestClient(app) as c:
        r = c.post("/api/auth/register", headers=ORIGIN, json={"email": "par-http-1@example.com", "display_name": "Cliente", "password": "Contrasena-segura-123!"})
        assert r.status_code == 201, r.text
        S.down = True
        for _ in range(20): clk.t += 1.0; g.keeper_step()
        r = c.post("/api/auth/register", headers=ORIGIN, json={"email": "par-http-2@example.com", "display_name": "Cliente", "password": "Contrasena-segura-123!"})
        assert r.status_code == 503 and r.json()["code"] == "write_gate_closed"
        assert c.get("/api/events").status_code == 200                  # las lecturas siguen
    with admin_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users WHERE email = 'par-http-2@example.com'")).scalar() == 0
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE email LIKE 'par-http-%'"))
