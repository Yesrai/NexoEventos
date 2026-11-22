"""Las pruebas funcionales de reservas de T3 (scripts/multicloud/oci-drill/app_functional.py) contra la APLICACIÓN REAL y PostgreSQL de pruebas: si no funcionan aquí, no se llevan a la nube."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from sqlalchemy import text
from tests.conftest import TEST_APP_URL, admin_engine, csrf_headers, login
from tests.test_api import register_client

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/multicloud/oci-drill"))
import app_functional as AF  # noqa: E402


def world(passwords):
    with admin_engine.begin() as c: c.execute(text("UPDATE events SET capacity = 60 WHERE id = 9001"))   # evento general asignado al operador, con cupos suficientes (la base de pruebas lo trae con 1)
    app = create_app(TEST_APP_URL); cl, op = TestClient(app), TestClient(app); register_client(cl); login(op, "operador@example.com", passwords["operator"])
    events = cl.get("/api/events").json(); ops = [e["id"] for e in op.get("/api/operator/events").json()]
    def new_client():
        c = TestClient(app); c.cookies.update(cl.cookies); return c
    return app, cl, op, events, ops, new_client


def run(passwords, **kw):
    app, cl, op, events, ops, new_client = world(passwords); log = []
    def check(name, ok, detail=""): log.append((name, bool(ok), detail))
    try: summary = AF.functional_checks(cl, op, kw.get("events", events), kw.get("ops", ops), check, csrf_headers, new_client)
    finally: app.state.engine.dispose()
    return log, summary


def test_las_pruebas_funcionales_pasan_contra_la_aplicacion_real(privileged_accounts):
    log, s = run(privileged_accounts); names = [n for n, _, _ in log]
    assert all(n.startswith("funcional:") for n in names) and len(log) == 7, names
    assert all(ok for _, ok, _ in log), [x for x in log if not x[1]]
    assert s["cupos_despues"] == s["cupos_antes"] - 5                      # 1 reserva + 4 concurrentes; la repetición idempotente no cuenta


def test_sin_evento_reservable_asignado_al_operador_falla_con_claridad(privileged_accounts):
    log, s = run(privileged_accounts, ops=[]); assert len(log) == 1 and log[0][1] is False and "ninguno cumple" in log[0][2]


def test_una_comprobacion_fallida_se_refleja_si_el_inventario_se_pierde(privileged_accounts, monkeypatch):
    """Control negativo: si la API dejara de descontar cupos, la prueba funcional lo detecta (no es una prueba que siempre pase)."""
    app, cl, op, events, ops, new_client = world(privileged_accounts); log = []
    real_get = cl.get
    def check(name, ok, detail=""): log.append((name, bool(ok), detail))
    class Stale:                                           # un cliente que siempre ve los cupos iniciales
        def __init__(self, c): self.c = c; self.cache = {}
        def __getattr__(self, n): return getattr(self.c, n)
        def get(self, url, **k):
            r = self.c.get(url, **k)
            if url.startswith("/api/events/") and r.status_code == 200:
                eid = url.rsplit("/", 1)[1]; j = r.json(); self.cache.setdefault(eid, j["available_capacity"]); j["available_capacity"] = self.cache[eid]
                class R:
                    status_code = 200
                    def json(s): return j
                return R()
            return r
    try: AF.functional_checks(Stale(cl), op, events, ops, check, csrf_headers, new_client)
    finally: app.state.engine.dispose()
    assert any(not ok for _, ok, _ in log)
