"""AWS V2 (ALB + Auto Scaling, 2 EC2 en 2 zonas) PROBADO EN LOCAL: instancias REALES de la API (uvicorn) detrás de un simulador de ALB/ASG (scripts/v2/ha_sim.py) y PostgreSQL local.
Distribución de tráfico, sesiones compartidas, reservas concurrentes sin duplicados ni sobreventa, caída/colgado de una instancia, sustitución automática y recuperación.
LÍMITE: no es AWS (ver ha_sim.py); la prueba con ALB y EC2 reales sigue pendiente de autorización."""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, text

from tests.conftest import TEST_ADMIN_URL

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/v2"))
from ha_sim import Alb  # noqa: E402

PASSWORD = "Only-For-Tests-Client-2026!"
ORIGIN = "http://127.0.0.1:5173"


@pytest.fixture
def alb():
    a = Alb(env={}, python=sys.executable)
    try:
        a.wait_healthy(2, 90)
        yield a
    finally:
        a.close()


def client_for(alb, email):
    c = httpx.Client(base_url=alb.url, timeout=20)
    r = c.post("/api/auth/register", headers={"Origin": ORIGIN}, json={"email": email, "display_name": "Cliente HA", "password": PASSWORD}); assert r.status_code == 201, r.text
    return c


def reserve(c, event_id, key, **payload):
    return c.post(f"/api/events/{event_id}/reservations", headers={"Origin": ORIGIN, "X-CSRF-Token": c.cookies.get("nexoeventos_csrf"), "Idempotency-Key": key}, json={"quantity": 1, **payload})


def db(sql):
    with create_engine(TEST_ADMIN_URL).connect() as conn:
        return conn.scalar(text(sql))


def test_el_trafico_se_reparte_en_dos_zonas_y_la_sesion_vale_en_cualquier_instancia(alb):
    assert sorted(i.zone for i in alb.healthy_targets()) == ["a", "b"]
    c = client_for(alb, "ha-sesion@example.com")
    for _ in range(40): assert c.get("/api/events").status_code == 200
    served = [i.served for i in alb.instances]
    assert min(served) >= 10 and sum(served) >= 41, f"reparto desigual: {served}"                  # least_outstanding_requests entre ambas
    me = [c.get("/api/me/reservations").status_code for _ in range(20)]
    assert set(me) == {200}, "la sesión (guardada en PostgreSQL) debe valer en las dos instancias, sin afinidad"


def test_reservas_concurrentes_por_el_balanceador_sin_duplicados_ni_sobreventa(alb):
    n = 14
    clients = [client_for(alb, f"ha-{i}@example.com") for i in range(n)]
    zone_id = clients[0].get("/api/events/9003").json()["zones"][0]["id"]
    with create_engine(TEST_ADMIN_URL).connect() as conn:
        seat = conn.scalar(text("SELECT id FROM event_seats WHERE event_id=9004 AND seat_number=1"))
    barrier = threading.Barrier(n)

    def go(i):
        barrier.wait(); c = clients[i]
        return (reserve(c, 9001, f"ha-ultimo-cupo-{i}").status_code,                                             # último cupo
                reserve(c, 9003, f"ha-zona-{i}-clave", zone_id=zone_id).status_code,                             # zona de 4
                reserve(c, 9004, f"ha-asiento-{i}-clave", seat_ids=[seat]).status_code)                             # el MISMO asiento numerado
    with ThreadPoolExecutor(n) as pool: res = list(pool.map(go, range(n)))
    assert sorted(r[0] for r in res) == [201] + [409] * (n - 1)
    assert sorted(r[1] for r in res) == [201] * 4 + [409] * (n - 4)
    assert sorted(r[2] for r in res) == [201] + [409] * (n - 1)
    assert db("SELECT count(*) FROM reservations WHERE event_id=9001") == 1 and db("SELECT reserved_count FROM events WHERE id=9001") == 1
    assert db("SELECT count(*) FROM tickets WHERE event_id=9003") == 4 == db("SELECT reserved_count FROM events WHERE id=9003") == db("SELECT sum(reserved_count) FROM event_zones WHERE event_id=9003")
    assert db("SELECT count(*) FROM reservations WHERE event_id=9004") == 1 and db("SELECT count(*) FROM tickets WHERE seat_id IS NOT NULL AND event_id=9004") == 1
    assert {i.served > 0 for i in alb.instances} == {True}, "la carga debió pasar por las dos instancias"


def test_reintento_con_la_misma_clave_de_idempotencia_en_otra_instancia_no_duplica(alb):
    c = client_for(alb, "ha-idem@example.com")
    ids = set()
    for _ in range(8):                                                                                  # el ALB alterna instancias: la misma petición cae en ambas
        r = reserve(c, 9002, "misma-clave"); assert r.status_code in (200, 201), r.text; ids.add(r.json()["reservation_id"])
    assert len(ids) == 1 and db("SELECT count(*) FROM reservations WHERE event_id=9002") == 1 and db("SELECT reserved_count FROM events WHERE id=9002") == 1


def test_cae_una_instancia_el_balanceador_la_saca_el_asg_la_sustituye_y_el_servicio_no_se_interrumpe(alb):
    c = client_for(alb, "ha-caida@example.com"); codes = []; stop = threading.Event()
    def traffic():
        while not stop.is_set():
            try: codes.append(c.get("/api/events").status_code)
            except Exception: codes.append(599)
            time.sleep(0.02)
    t = threading.Thread(target=traffic); t.start()
    try:
        victim = alb.healthy_targets()[0]; victim.kill(); t0 = time.monotonic()
        end = time.monotonic() + 40
        while time.monotonic() < end and not (len(alb.healthy_targets()) == 2 and victim not in alb.healthy_targets() and alb.replacements >= 1): time.sleep(0.1)
        recovered_after = time.monotonic() - t0
        assert alb.replacements >= 1 and len(alb.healthy_targets()) == 2 and victim.id not in [i.id for i in alb.healthy_targets()]
        assert sorted(i.zone for i in alb.healthy_targets()) == ["a", "b"], "la sustituta debe volver a repartir las zonas"
        n_before = len(codes); time.sleep(1.0)
        assert all(x == 200 for x in codes[n_before:]), "tras la sustitución no puede haber errores"
    finally:
        stop.set(); t.join()
    bad = [x for x in codes if x != 200]
    ev = [h[1] for h in alb.history]
    assert "unhealthy" in ev and "terminate" in ev and ev.count("launch") >= 3
    assert len(bad) <= 0.25 * len(codes) and all(x in (502, 503, 599) for x in bad)             # solo la VENTANA de detección (medida), nunca 4xx ni datos erróneos
    print(f"\n[ha-sim] errores en la ventana de detección: {len(bad)}/{len(codes)}; recuperación completa en {recovered_after:.1f}s; historia: {alb.history}")


def test_una_instancia_colgada_se_detecta_por_health_check_y_se_reemplaza(alb):
    victim = alb.healthy_targets()[0]; victim.freeze(); t0 = time.monotonic()
    end = time.monotonic() + 40
    while time.monotonic() < end and not (alb.replacements >= 1 and len(alb.healthy_targets()) == 2): time.sleep(0.1)
    assert alb.replacements >= 1 and len(alb.healthy_targets()) == 2 and victim.id not in [i.id for i in alb.healthy_targets()], alb.history
    c = client_for(alb, "ha-colgada@example.com"); assert all(c.get("/api/events").status_code == 200 for _ in range(10))


def test_reservas_durante_la_caida_con_reintentos_idempotentes_no_se_duplican_ni_se_sobrevenden(alb):
    n = 12
    clients = [client_for(alb, f"hak-{i}@example.com") for i in range(n)]
    zone_id = clients[0].get("/api/events/9003").json()["zones"][0]["id"]
    barrier = threading.Barrier(n + 1); out = {}

    def go(i):
        barrier.wait(); final = None
        for attempt in range(25):                                                                      # el cliente reintenta con la MISMA clave ante 5xx/errores de red
            try:
                r = reserve(clients[i], 9003, f"ha-caida-clave-{i}", zone_id=zone_id); final = r.status_code
                if final < 500: break
            except Exception: final = 599
            time.sleep(0.2)
        out[i] = final
    ths = [threading.Thread(target=go, args=(i,)) for i in range(n)]; [t.start() for t in ths]
    barrier.wait(); time.sleep(0.05); alb.healthy_targets()[0].kill()                                  # una instancia cae en pleno pico
    [t.join(60) for t in ths]
    ok = sorted(v for v in out.values() if v in (200, 201))                                              # 200 = repetición idempotente de una reserva ya confirmada (el reintento tras un 5xx ambiguo)
    assert len(ok) == 4 and sorted(v for v in out.values() if v not in (200, 201)) == [409] * (n - 4), out   # exactamente 4 éxitos, aunque haya habido 5xx y reintentos
    assert db("SELECT count(*) FROM tickets WHERE event_id=9003") == 4 == db("SELECT reserved_count FROM events WHERE id=9003")
    assert db("SELECT count(*) FROM reservations WHERE event_id=9003") == 4
    assert db("SELECT count(*) FROM (SELECT idempotency_key FROM reservations GROUP BY 1 HAVING count(*) > 1) d") == 0
