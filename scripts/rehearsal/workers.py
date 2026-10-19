#!/usr/bin/env python3
"""Sesiones, disputa de asiento y fila virtual con VARIOS workers, contra una API LOCAL y una base DESECHABLE.

Uso: workers.py <base_local> <evento_con_asientos>
Activa la fila (3 turnos) en ese evento de la base desechable `nexo-rehearsal`; no toca otra base.
"""
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

BASE, EVENT = sys.argv[1], int(sys.argv[2])
if urlparse(BASE).hostname not in ("127.0.0.1", "localhost"):
    sys.exit("Solo host local.")
H = {"Origin": "http://localhost:5173"}
USERS = 12
MAX_ACTIVE = 3


def sql(q: str) -> str:
    return subprocess.run(["docker", "exec", "-i", "nexo-rehearsal", "psql", "-U", "postgres", "-d", "nexoeventos", "-At", "-c", q],
                          check=True, capture_output=True, text=True).stdout.strip()


def new_user(i: int) -> httpx.Client:
    c = httpx.Client(base_url=BASE, headers=H, timeout=30)
    r = c.post("/api/auth/register", json={"email": f"w{i}-{uuid.uuid4().hex[:6]}@example.com", "display_name": f"Ensayo {i}", "password": "Ensayo-local-1234"})
    assert r.status_code == 201, r.text
    return c


def post(c: httpx.Client, path: str, **kw):
    return c.post(path, headers={**H, "X-CSRF-Token": c.cookies.get("nexoeventos_csrf", ""), "Idempotency-Key": uuid.uuid4().hex}, **kw)


def main() -> None:
    sql(f"update events set queue_enabled=true, queue_max_active={MAX_ACTIVE}, queue_pass_minutes=10, sales_start_at=null where id={EVENT}")
    sql(f"delete from queue_entries where event_id={EVENT}")  # base desechable
    with ThreadPoolExecutor(USERS) as ex:
        clients = list(ex.map(new_user, range(USERS)))
    # 1) sesión creada en un worker válida en cualquiera: 80 lecturas repartidas
    codes = {clients[0].get("/api/auth/session").status_code for _ in range(80)}
    assert codes == {200}, codes
    # 2) sin turno no se reserva
    seat = httpx.get(f"{BASE}/api/events/{EVENT}").json()["seats"][0]["id"]
    r = post(clients[0], f"/api/events/{EVENT}/reservations", json={"quantity": 1, "seat_ids": [seat]})
    assert r.status_code in (403, 409, 423), ("sin turno debería rechazarse", r.status_code, r.text)
    # 3) 12 usuarios entran a la vez
    with ThreadPoolExecutor(USERS) as ex:
        res = list(ex.map(lambda c: post(c, f"/api/events/{EVENT}/queue"), clients))
    assert all(x.status_code == 200 for x in res), [x.status_code for x in res]
    sts = [c.get(f"/api/events/{EVENT}/sales").json()["queue"] for c in clients]
    admitted = [i for i, s in enumerate(sts) if s["status"] == "admitted"]
    waiting = sorted(s["position"] for s in sts if s["status"] == "waiting")
    assert len(admitted) == MAX_ACTIVE, ("admitidos", len(admitted))
    assert waiting == list(range(1, USERS - MAX_ACTIVE + 1)), ("posiciones", waiting)
    # 4) la posición es la misma en consultas repetidas (reparto entre workers)
    again = [c.get(f"/api/events/{EVENT}/sales").json()["queue"]["position"] for c in clients]
    assert sorted(p for p in again if p) == waiting
    # 5) todos disputan el mismo asiento a la vez: admitidos compiten, los demás se rechazan
    with ThreadPoolExecutor(USERS) as ex:
        out = list(ex.map(lambda c: post(c, f"/api/events/{EVENT}/reservations", json={"quantity": 1, "seat_ids": [seat]}).status_code, clients))
    winners = out.count(201)
    assert winners == 1, ("ganadores", winners, out)
    assert all(out[i] in (201, 409) for i in admitted) and all(out[i] != 201 for i in range(USERS) if i not in admitted), out
    n = sql(f"select count(*) from tickets where seat_id={seat}")
    assert n == "1", ("tickets en el asiento", n)
    print(f"workers OK: sesión válida en 80/80 lecturas; fila: {MAX_ACTIVE} admitidos y posiciones {waiting[0]}..{waiting[-1]} consistentes; asiento disputado: 1 ganador de {USERS}, 1 ticket")


if __name__ == "__main__":
    main()
