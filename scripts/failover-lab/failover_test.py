#!/usr/bin/env python3
"""Pruebas del laboratorio LOCAL de failover (solo stdlib; solo localhost; datos ficticios).

Escenarios:
  T1 caída dura (docker kill) de la app "aws": tiempo de recuperación, errores y aciertos a través de HAProxy
  T2 congelación (docker pause) de la app "aws": el proceso sigue pero no responde
  T3 escrituras durante la caída: reservas con reintento + Idempotency-Key, sin duplicados ni sobreventa
  T4 disputa del mismo asiento repartida entre las dos instancias
  T5 QR emitido en una instancia y validado en la otra (segunda validación rechazada)
  T6 caída de PostgreSQL: la app NO conmuta (failover de app != failover de BD) y los datos persisten tras reiniciar la BD
Uso: python3 failover_test.py --out ../../docs/entregable3/evidencias/local-AAAAMMDD [--only T1,T3]
"""
from __future__ import annotations

import argparse, http.client, json, statistics, subprocess, sys, threading, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROXY, AWS, OCI = ("127.0.0.1", 18080), ("127.0.0.1", 18001), ("127.0.0.1", 18002)
STATS = ("127.0.0.1", 18404)
ORIGIN = "http://127.0.0.1:18080"
PROJECT = "nexo-failover-lab"
EV_SEATS, EV_GENERAL = 990001, 990002
PWD = "Lab-Only-Pass-12345!"  # contraseña ficticia de cuentas ficticias del laboratorio


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()


def docker(*args: str) -> float:
    """Ejecuta docker y devuelve el instante ANTERIOR a la orden (criterio conservador: incluye la latencia del comando docker)."""
    t = time.monotonic()
    subprocess.run(["docker", *args], capture_output=True, text=True, check=True)
    return t


def psql(sql: str) -> str:
    return sh(str(HERE / "psql.sh"), "-c", sql)


def req(addr, method, path, body=None, headers=None, timeout=3.0):
    c = http.client.HTTPConnection(*addr, timeout=timeout)
    try:
        h = {"Origin": ORIGIN, "Connection": "close", **(headers or {})}
        data = None
        if body is not None:
            data, h["Content-Type"] = json.dumps(body), "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read()
        return r.status, raw, r
    finally:
        c.close()


class User:
    def __init__(self, tag: str, addr=PROXY):
        self.email, self.addr, self.cookies = f"lab-{tag}-{uuid.uuid4().hex[:6]}@example.com", addr, {}

    def _do(self, method, path, body=None, extra=None, addr=None, timeout=3.0):
        h = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items()), **(extra or {})}
        if "nexoeventos_csrf" in self.cookies:
            h["X-CSRF-Token"] = self.cookies["nexoeventos_csrf"]
        st, raw, r = req(addr or self.addr, method, path, body, h, timeout)
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                name, _, rest = v.partition("=")
                self.cookies[name] = rest.split(";")[0]
        try:
            js = json.loads(raw) if raw else None
        except ValueError:
            js = None
        return st, js, r.getheader("X-Served-By")

    def register_login(self):
        assert self._do("POST", "/api/auth/register", {"email": self.email, "display_name": "Lab ficticio", "password": PWD}, timeout=10)[0] == 201
        assert self._do("POST", "/api/auth/login", {"email": self.email, "password": PWD}, timeout=10)[0] == 200
        return self

    def reserve(self, event, body, key, addr=None, timeout=3.0):
        return self._do("POST", f"/api/events/{event}/reservations", body, {"Idempotency-Key": key}, addr, timeout)


# ---------------------------------------------------------------- infraestructura
def haproxy_state() -> dict:
    st, raw, _ = req(STATS, "GET", "/;csv")
    rows = [l.split(",") for l in raw.decode().splitlines()[1:] if l]
    return {r[1]: r[17] for r in rows if r[0] == "apps" and r[1] in ("aws", "oci")}


def wait_state(want: dict, timeout=30):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            if all(haproxy_state().get(k, "").startswith(v) for k, v in want.items()):
                return time.monotonic() - t0
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"HAProxy no alcanzó {want}: {haproxy_state()}")


def ensure_baseline():
    for c in ("app-aws", "app-oci", "db"):
        cid = sh("docker", "ps", "-aq", "--filter", f"name={PROJECT}-{c}-1")
        sh("docker", "unpause", cid) if "Paused" in sh("docker", "inspect", "-f", "{{.State.Status}}", cid) else None
        if sh("docker", "inspect", "-f", "{{.State.Running}}", cid) != "true":
            sh("docker", "start", cid)
    wait_state({"aws": "UP", "oci": "UP"}, 60)


class Load:
    """Generador de carga: `workers` hilos, cada uno con una conexión nueva cada `period` s (≈ workers/period solicitudes por segundo)."""

    def __init__(self, path="/api/events", period=0.2, workers=4):
        self.path, self.period, self.rows, self.stop = path, period, [], threading.Event()
        self.ts = [threading.Thread(target=self.run, args=(i * period / workers,), daemon=True) for i in range(workers)]

    def run(self, offset):
        time.sleep(offset)
        while not self.stop.is_set():
            t0 = time.monotonic()
            try:
                st, _, r = req(PROXY, "GET", self.path, timeout=2.0)
                self.rows.append((t0, st, time.monotonic() - t0, r.getheader("X-Served-By"), time.monotonic()))
            except Exception as e:  # tiempo de espera o conexión rechazada/cortada
                self.rows.append((t0, 0, time.monotonic() - t0, type(e).__name__, time.monotonic()))
            time.sleep(max(0, self.period - (time.monotonic() - t0)))

    def __enter__(self):
        [t.start() for t in self.ts]; return self

    def __exit__(self, *a):
        self.stop.set(); [t.join() for t in self.ts]


def analyse(rows, t_fail):
    rows = sorted(rows)
    ok = [r for r in rows if r[1] == 200]
    bad = [r for r in rows if r[1] != 200]
    first_bad = next((r[0] for r in rows if r[0] >= t_fail and r[1] != 200), None)
    last_bad = max((r[0] for r in bad), default=None)
    served, codes = {}, {}
    for r in ok:
        served[r[3]] = served.get(r[3], 0) + 1
    for r in bad:
        k = str(r[1] or r[3]); codes[k] = codes.get(k, 0) + 1
    ends = sorted(r[4] for r in ok if t_fail - 1 <= r[4] <= t_fail + 15)
    gap = max((b - a for a, b in zip(ends, ends[1:])), default=None)
    lat = sorted(r[2] for r in ok)
    return {
        "solicitudes": len(rows), "exitosas": len(ok), "fallidas": len(bad), "codigos_fallidos": codes,
        "tasa_exito_pct": round(100 * len(ok) / max(1, len(rows)), 2),
        "primer_error_tras_falla_s": None if first_bad is None else round(first_bad - t_fail, 3),
        "ultimo_error_tras_falla_s": None if last_bad is None else round(last_bad - t_fail, 3),
        "mayor_silencio_entre_respuestas_exitosas_s": None if gap is None else round(gap, 3),
        "solicitudes_lentas_mas_de_500ms": sum(1 for r in ok if r[2] > 0.5),
        "atendidas_por": served,
        "latencia_p50_ms": round(1000 * statistics.median(lat), 1) if lat else None,
        "latencia_max_ms": round(1000 * lat[-1], 1) if lat else None,
    }


def check(res, name, ok, detail=""):
    res.append({"prueba": name, "ok": bool(ok), "detalle": detail})
    print(("OK   " if ok else "FALLA"), name, "-", detail, flush=True)


# ---------------------------------------------------------------- escenarios
def t_kill_or_pause(mode: str, runs: int):
    out = []
    for i in range(runs):
        ensure_baseline()
        time.sleep(1)
        poll_t = {}
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                try:
                    s = haproxy_state().get("aws", "")
                    if s.startswith("DOWN") and "down" not in poll_t:
                        poll_t["down"] = time.monotonic()
                except Exception:
                    pass
                time.sleep(0.05)

        w = threading.Thread(target=watch, daemon=True); w.start()
        with Load() as load:
            time.sleep(4)
            cid = f"{PROJECT}-app-aws-1"
            t_fail = docker("kill", cid) if mode == "kill" else docker("pause", cid)
            time.sleep(10)
            t_back = docker("start", cid) if mode == "kill" else docker("unpause", cid)
            time.sleep(10)
        stop.set(); w.join()
        a = analyse(load.rows, t_fail)
        a["haproxy_marca_caido_tras_falla_s"] = None if "down" not in poll_t else round(poll_t["down"] - t_fail, 3)
        post = sorted(r for r in load.rows if r[0] > t_back)
        back = next((r[0] for r in post if r[1] == 200 and r[3] == "aws"), None)
        a["retorno_automatico_a_aws_tras_reinicio_s"] = None if back is None else round(back - t_back, 3)
        out.append(a)
        print(f"  {mode} #{i + 1}:", json.dumps(a, ensure_ascii=False), flush=True)
    return out


def t_writes_during_failure(res):
    """60 clientes ficticios reservan 1 cupo cada uno (hay 40) repartidos en 2,5 s; 'aws' se mata a 1,0 s. Reintento con la MISMA clave ante error de red o 5xx."""
    import random
    ensure_baseline()
    n, cap = 60, 40
    psql(f"DELETE FROM tickets WHERE event_id={EV_GENERAL}; DELETE FROM reservations WHERE event_id={EV_GENERAL}; UPDATE events SET reserved_count=0, capacity={cap} WHERE id={EV_GENERAL}")
    users = [User(f"w{i}").register_login() for i in range(n)]
    keys = [uuid.uuid4().hex for _ in users]
    delays = [random.Random(i).uniform(0, 2.5) for i in range(n)]
    outcome, attempts, retried = [None] * n, [0] * n, [0] * n
    start = threading.Barrier(n + 2)
    kill_at = {}

    def killer():
        start.wait(); time.sleep(1.0)
        kill_at["t"] = docker("kill", f"{PROJECT}-app-aws-1")

    def worker(i):
        start.wait(); time.sleep(delays[i])
        for a in range(10):
            attempts[i] += 1
            try:
                st, js, srv = users[i].reserve(EV_GENERAL, {"quantity": 1}, keys[i], timeout=3)
                if st in (200, 201, 409):
                    outcome[i] = (st, js and js.get("reservation_id"), srv)
                    return
            except Exception:
                pass
            retried[i] += 1
            time.sleep(0.4)
        outcome[i] = ("sin_respuesta", None, None)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)] + [threading.Thread(target=killer)]
    for t in ts: t.start()
    start.wait()
    for t in ts: t.join()
    ok = [o for o in outcome if o and o[0] in (200, 201)]
    full = [o for o in outcome if o and o[0] == 409]
    lost = [o for o in outcome if not o or o[0] == "sin_respuesta"]
    replayed = sum(1 for o in ok if o[0] == 200)
    rc = int(psql(f"SELECT reserved_count FROM events WHERE id={EV_GENERAL}"))
    reservations = int(psql(f"SELECT count(*) FROM reservations WHERE event_id={EV_GENERAL}"))
    tickets = int(psql(f"SELECT count(*) FROM tickets WHERE event_id={EV_GENERAL}"))
    dup_users = int(psql(f"SELECT count(*) FROM (SELECT user_id FROM reservations WHERE event_id={EV_GENERAL} GROUP BY 1 HAVING count(*)>1) x"))
    served = {}
    for o in ok: served[o[2]] = served.get(o[2], 0) + 1
    info = {"clientes": n, "cupos": cap, "aceptadas": len(ok), "de_ellas_200_repetidas_por_idempotencia": replayed, "agotado_409": len(full), "sin_respuesta": len(lost),
            "clientes_que_tuvieron_que_reintentar": sum(1 for r in retried if r), "reintentos_totales": sum(retried),
            "reserved_count_bd": rc, "reservas_bd": reservations, "entradas_bd": tickets, "clientes_con_reserva_duplicada": dup_users, "aceptadas_atendidas_por": served}
    check(res, "T3 sin sobreventa: reservas == cupos y reserved_count == cupos", reservations == cap and rc == cap, json.dumps(info, ensure_ascii=False))
    check(res, "T3 sin duplicados: 1 reserva por cliente, entradas == reservas", dup_users == 0 and tickets == reservations)
    check(res, "T3 ningún cliente quedó sin respuesta tras reintentar con la misma clave", len(lost) == 0, f"{len(lost)} sin respuesta")
    check(res, "T3 aceptadas + agotadas == clientes", len(ok) + len(full) == n)
    check(res, "T3 la caída ocurrió con clientes aún pendientes (la prueba sí ejercitó el failover)", sum(retried) > 0 or "oci" in served, f"{sum(retried)} reintentos; atendidas por {served}")
    return info


def t_idempotent_replay(res):
    """La misma clave enviada a 'aws' y reenviada a 'oci' tras la caída devuelve la MISMA reserva (200, replayed)."""
    ensure_baseline()
    u = User("idem").register_login()
    seat_ids = [s["id"] for s in json.loads(req(PROXY, "GET", f"/api/events/{EV_SEATS}")[1])["seats"] if s.get("available", True)][:2]
    key = uuid.uuid4().hex
    st1, j1, s1 = u.reserve(EV_SEATS, {"quantity": 2, "seat_ids": seat_ids}, key, addr=AWS)
    docker("kill", f"{PROJECT}-app-aws-1")
    st2 = j2 = s2 = None
    retries, transient = 0, []
    for _ in range(10):  # el cliente reintenta con la MISMA clave hasta recibir respuesta
        try:
            st2, j2, s2 = u.reserve(EV_SEATS, {"quantity": 2, "seat_ids": seat_ids}, key, addr=PROXY)
            if st2 < 500:
                break
            transient.append(st2)
        except Exception as e:
            transient.append(type(e).__name__)
        retries += 1
        time.sleep(0.3)
    sess = None
    for _ in range(10):
        try:
            sess = u._do("GET", "/api/auth/session", addr=PROXY)
            break
        except Exception:
            time.sleep(0.3)
    check(res, "T3b sesión creada en 'aws' sigue válida en 'oci' (sesiones en PostgreSQL)", sess[0] == 200 and sess[2] in ("oci", "aws"), f"{sess[0]} servida por {sess[2]}")
    check(res, "T3b reserva original 201 en aws y reintento 200 en oci con la misma reserva",
          st1 == 201 and st2 == 200 and j1["reservation_id"] == j2["reservation_id"] and j2["replayed"] and s2 == "oci", f"{st1}/{st2}, atendida por {s1}/{s2}, {retries} reintento(s) tras error transitorio {transient}")
    n = int(psql(f"SELECT count(*) FROM reservations r JOIN users u ON u.id=r.user_id WHERE u.email='{u.email}'"))
    check(res, "T3b una sola reserva en la base pese al reintento", n == 1, f"{n}")
    return u, j1


def t_seat_race(res):
    ensure_baseline()
    free = [s["id"] for s in json.loads(req(PROXY, "GET", f"/api/events/{EV_SEATS}")[1])["seats"] if s.get("available", True)]
    seat = free[-1]
    users = [User(f"r{i}").register_login() for i in range(8)]
    codes, bar = [], threading.Barrier(8)

    def go(i):
        bar.wait()
        codes.append(users[i].reserve(EV_SEATS, {"quantity": 1, "seat_ids": [seat]}, uuid.uuid4().hex, addr=AWS if i % 2 == 0 else OCI, timeout=10)[0])

    ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in ts: t.start()
    for t in ts: t.join()
    holders = int(psql(f"SELECT count(*) FROM tickets WHERE seat_id={seat}"))
    check(res, "T4 mismo asiento desde 2 instancias: 1 ganador (201), el resto 409, 1 entrada en BD", sorted(codes).count(201) == 1 and sorted(codes).count(409) == 7 and holders == 1, f"códigos {sorted(codes)}, entradas {holders}")


def t_qr_cross(res):
    """QR emitido por una instancia (aws) y validado por la otra (oci); la segunda validación se rechaza en cualquiera."""
    ensure_baseline()
    cl = User("qr").register_login()
    op = User("op").register_login()
    psql(f"UPDATE users SET role='operator' WHERE email='{op.email}'")
    psql(f"INSERT INTO operator_event_assignments (operator_user_id, event_id) SELECT id, {EV_SEATS} FROM users WHERE email='{op.email}'")
    assert op._do("POST", "/api/auth/login", {"email": op.email, "password": PWD}, timeout=10)[0] == 200
    seats = [s["id"] for s in json.loads(req(PROXY, "GET", f"/api/events/{EV_SEATS}")[1])["seats"] if s.get("available", True)][:2]
    assert cl.reserve(EV_SEATS, {"quantity": 2, "seat_ids": seats}, uuid.uuid4().hex, addr=AWS)[0] == 201
    tk = cl._do("GET", "/api/me/tickets", addr=OCI)
    check(res, "T5 las entradas emitidas en 'aws' se leen desde 'oci' con su QR", tk[0] == 200 and len(tk[1]) == 2, f"servida por {tk[2]}")
    tok = tk[1][0]["qr_token"]
    v1 = op._do("POST", "/api/operator/validate", {"event_id": EV_SEATS, "qr_token": tok}, addr=OCI)
    v2 = op._do("POST", "/api/operator/validate", {"event_id": EV_SEATS, "qr_token": tok}, addr=AWS)
    check(res, "T5 QR emitido en aws se valida en oci (200) y la repetición en aws se rechaza (409)", v1[0] == 200 and v2[0] == 409, f"{v1[0]}/{v2[0]}")
    used = int(psql(f"SELECT count(*) FROM tickets WHERE used_at IS NOT NULL AND owner_user_id=(SELECT id FROM users WHERE email='{cl.email}')"))
    check(res, "T5 exactamente 1 entrada marcada como usada en la base", used == 1, f"{used}")


def t_db_failure(res):
    """Con PostgreSQL caída, HAProxy NO conmuta (ambas apps dependen de la misma base): failover de aplicación != failover de base."""
    ensure_baseline()
    before = {t: int(psql(f"SELECT count(*) FROM {t}")) for t in ("reservations", "tickets", "users", "auth_sessions")}
    docker("stop", f"{PROJECT}-db-1")
    time.sleep(6)
    live = [req(PROXY, "GET", "/health")[0] for _ in range(10)]
    ready = [req(PROXY, "GET", "/ready", timeout=8)[0] for _ in range(10)]
    api = [req(PROXY, "GET", "/api/events", timeout=8)[0] for _ in range(10)]
    state = haproxy_state()
    check(res, "T6 con la BD caída /health sigue 200 (liveness) y HAProxy mantiene aws y oci UP (no hay conmutación)",
          set(live) == {200} and state["aws"].startswith("UP") and state["oci"].startswith("UP"), f"estado {state}")
    sess_user = User("t6").cookies  # sin sesión: solo para observar el código que devuelve /api/auth/session
    sess = [req(PROXY, "GET", "/api/auth/session", timeout=8)[0] for _ in range(5)]
    check(res, "T6 con la BD caída ni /ready ni /api/events responden 200 en ninguna instancia (conmutar de app no arregla la BD)",
          set(ready) == {503} and 200 not in api, f"/ready {sorted(set(ready))}, /api/events {sorted(set(api))}, /api/auth/session sin cookie {sorted(set(sess))}")
    t0 = docker("start", f"{PROJECT}-db-1")
    rec = None
    while time.monotonic() - t0 < 60:
        try:
            if req(PROXY, "GET", "/api/events", timeout=3)[0] == 200:
                rec = time.monotonic() - t0
                break
        except Exception:
            pass
        time.sleep(0.25)
    after = {t: int(psql(f"SELECT count(*) FROM {t}")) for t in before}
    check(res, "T6 las apps se recuperan solas al volver la BD (sin reiniciar contenedores)", rec is not None, f"{None if rec is None else round(rec, 1)} s tras ordenar el inicio de la BD")
    check(res, "T6 los datos persisten tras reiniciar la BD (volumen local): mismos conteos", before == after, f"antes {before} / después {after}")
    return {"recuperacion_tras_iniciar_bd_s": None if rec is None else round(rec, 1), "conteos": after}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, a.only.split(",")))
    want = lambda k: not only or k in only
    res, data = [], {}
    ensure_baseline()
    # datos ficticios del laboratorio: se reinician los eventos 990001/990002 para que cada ejecución parta igual (solo BD del laboratorio)
    psql(f"DELETE FROM access_logs WHERE event_id IN ({EV_SEATS},{EV_GENERAL}); DELETE FROM tickets WHERE event_id IN ({EV_SEATS},{EV_GENERAL}); UPDATE event_seats SET reservation_id=NULL WHERE event_id={EV_SEATS}; "
         f"DELETE FROM reservations WHERE event_id IN ({EV_SEATS},{EV_GENERAL}); UPDATE events SET reserved_count=0 WHERE id IN ({EV_SEATS},{EV_GENERAL}); UPDATE event_zones SET reserved_count=0 WHERE event_id={EV_SEATS}")
    if want("T1"):
        print("== T1 caída dura (docker kill)"); data["T1_kill"] = t_kill_or_pause("kill", a.runs)
    if want("T2"):
        print("== T2 congelación (docker pause)"); data["T2_pause"] = t_kill_or_pause("pause", a.runs)
    if want("T3"):
        print("== T3 escrituras durante la caída"); data["T3"] = t_writes_during_failure(res); ensure_baseline()
        t_idempotent_replay(res); ensure_baseline()
    if want("T4"):
        print("== T4 disputa de asiento entre instancias"); t_seat_race(res)
    if want("T5"):
        print("== T5 QR entre instancias"); t_qr_cross(res)
    if want("T6"):
        print("== T6 caída de PostgreSQL"); data["T6"] = t_db_failure(res)
    (out / "resultados.json").write_text(json.dumps({"pruebas": res, "datos": data}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ensure_baseline()
    print(f"\n{sum(r['ok'] for r in res)} de {len(res)} comprobaciones OK")
    sys.exit(0 if all(r["ok"] for r in res) else 1)


if __name__ == "__main__":
    main()
