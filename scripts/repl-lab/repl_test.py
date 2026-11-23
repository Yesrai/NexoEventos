#!/usr/bin/env python3
"""Pruebas del laboratorio nexo-repl-lab (solo Docker local; datos ficticios; solo stdlib).

Etapas:  A replicación y sus límites · B fallas seguras (witness caído, partición, aislamiento no confirmable) · C caída del escritor con carga y tras confirmar
         D failback manual seguro · E causa del HTTP 500 con la BD caída
Uso: python3 repl_test.py --out ../../docs/entregable3/evidencias/repl-AAAAMMDD [--only A,B,C,D,E]
"""
from __future__ import annotations

import argparse, contextlib, importlib.util, json, os, signal, subprocess, sys, threading, time, traceback, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import labctl as L  # noqa: E402

spec = importlib.util.spec_from_file_location("fl", HERE.parent / "failover-lab" / "failover_test.py")
fl = importlib.util.module_from_spec(spec); spec.loader.exec_module(fl)  # reutiliza User/req/Load/analyse/check (HTTP, solo localhost)

EV_SEATS, EV_GENERAL = 990001, 990002
OUT: Path = Path(".")
MON: subprocess.Popen | None = None
RES: list = []
DATA: dict = {}


def new_user(tag: str, addr=None):
    """Alta + login de un usuario ficticio. Las respuestas no exitosas se registran en DATA['incidencias_de_registro']; si no se logra tras 8 intentos, falla con la última respuesta."""
    u = fl.User(tag, addr=addr) if addr else fl.User(tag)
    last = None
    for attempt in range(8):
        try:
            st, js, srv = u._do("POST", "/api/auth/register", {"email": u.email, "display_name": "Lab ficticio", "password": fl.PWD}, timeout=10)
            if st == 201:
                st2, js2, _ = u._do("POST", "/api/auth/login", {"email": u.email, "password": fl.PWD}, timeout=10)
                if st2 == 200:
                    return u
                last = ("login", st2, js2)
            else:
                last = ("registro", st, js)
        except Exception as e:  # noqa: BLE001 - se registra
            last = ("excepcion", type(e).__name__, str(e)[:120])
        DATA.setdefault("incidencias_de_registro", []).append({"usuario": tag, "intento": attempt + 1, "respuesta": str(last)[:300], "t": round(time.time(), 2)})
        time.sleep(0.7)
    raise RuntimeError(f"no se pudo registrar al usuario ficticio {tag}: {last}")


@contextlib.contextmanager
def scenario(name: str):
    """Aísla un escenario: si lanza una excepción se REGISTRA como comprobación fallida con su traza y se continúa con el siguiente (las evidencias no se pierden)."""
    try:
        yield
    except KeyboardInterrupt:
        raise
    except BaseException as e:  # noqa: BLE001
        check(f"{name} EXCEPCIÓN durante la prueba ({type(e).__name__})", False, traceback.format_exc()[-1000:])
        try:
            stop_monitor()
        except Exception:  # noqa: BLE001
            pass


def check(name, ok, detail=""):
    fl.check(RES, name, ok, detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, default=str))


def sql(node, q, **kw):
    return L.sql(node, q, **kw)


def q1(node, q, **kw):
    return L.sql(node, q, **kw)[1]


# ------------------------------------------------------------------ ciclo de vida del laboratorio
def run(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, **k)


class MonitorDied(RuntimeError):
    pass


FLAGS = {"mon_death_ok": False}      # True solo mientras una prueba PROVOCA la caída del controlador (inyección de fallos)


def mon_check():
    """Las pruebas fallan de inmediato si el monitor terminó de forma inesperada (nunca se continúa con un monitor muerto)."""
    if FLAGS["mon_death_ok"]:
        return
    if MON is not None and MON.poll() is not None:
        raise MonitorDied(f"el monitor terminó inesperadamente (código {MON.returncode}); ver {OUT}/eventos-*.stderr.log")


def msleep(sec: float):
    t0 = time.time()
    while time.time() - t0 < sec:
        mon_check(); time.sleep(min(0.5, max(0.0, sec - (time.time() - t0))))


def stop_monitor():
    global MON
    if MON and MON.poll() is None:
        MON.send_signal(signal.SIGTERM)
        try: MON.wait(5)
        except Exception: MON.kill()
    MON = None


def start_monitor(tag: str, auto=True, env=None) -> Path:
    global MON
    stop_monitor()
    log = OUT / f"eventos-{tag}.jsonl"
    log.unlink(missing_ok=True)
    e = {**os.environ, "LAB_EVENT_LOG": str(log), **(env or {})}
    out_f = open(OUT / f"eventos-{tag}.stdout.log", "w"); err_f = open(OUT / f"eventos-{tag}.stderr.log", "w")
    MON = subprocess.Popen([sys.executable, "-u", str(HERE / "labctl.py"), "monitor"] + ([] if auto else ["--no-auto"]), env=e, stdout=out_f, stderr=err_f)
    time.sleep(1.5)
    mon_check()
    return log


def events(log: Path) -> list[dict]:
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()] if log.exists() else []


SEED = f"""
INSERT INTO events (id, name, event_date, event_time, venue, city, category, description, price, capacity, reserved_count, ticket_mode, is_demo, status)
VALUES ({EV_SEATS}, '[LAB] Evento con asientos', current_date + 30, '20:00', 'Sede ficticia', 'Lima', 'Prueba', 'Ficticio.', 50, 40, 0, 'seats', true, 'published'),
       ({EV_GENERAL}, '[LAB] Evento general', current_date + 30, '20:00', 'Sede ficticia', 'Lima', 'Prueba', 'Ficticio.', 30, 100000, 0, 'general', true, 'published');
INSERT INTO event_zones (event_id, name, price, capacity, reserved_count) VALUES ({EV_SEATS}, 'Platea', 50, 40, 0);
INSERT INTO event_seats (event_id, zone_id, row_label, seat_number)
SELECT {EV_SEATS}, z.id, r, n FROM event_zones z, unnest(ARRAY['A','B','C','D']) r, generate_series(1,10) n WHERE z.event_id = {EV_SEATS};
"""


def fresh_lab(tag: str, monitor=True, env=None, sync=False):
    """Destruye y reconstruye SOLO nexo-repl-lab; siembra datos ficticios; arranca el monitor."""
    stop_monitor()
    L.PAUSE.unlink(missing_ok=True)
    L.PROT.unlink(missing_ok=True)
    os.environ["LAB_SYNC"] = "1" if sync else "0"      # A-E: asíncrono (comparable con las corridas anteriores); F: síncrono
    subprocess.run(["docker", "build", "-q", "--pull=false", "--network=none", "-f", str(HERE / "Dockerfile.current"), "-t", "nexo-repl-lab-backend:current", str(HERE.parents[1] / "backend")], capture_output=True)
    key = L.KEYFILE
    envs = {**os.environ, **{k: v for k, v in (l.split("=", 1) for l in key.read_text().splitlines() if "=" in l)}}
    subprocess.run(["docker", "compose", "-p", L.PROJECT, "-f", str(HERE / "compose.yml"), "--profile", "tools", "--profile", "fault", "--profile", "stale", "down", "-v", "--remove-orphans"], capture_output=True, env=envs)
    r = run(sys.executable, str(HERE / "labctl.py"), "setup", env=envs)
    assert r.returncode == 0, r.stdout[-300:] + r.stderr[-600:]
    assert sql("pg-aws", SEED)[0] == 0
    wait_equal(["events", "event_seats"])
    sql("pg-aws", "SELECT 1")
    if not monitor:
        return None
    log = start_monitor(tag, env=env)
    assert wait_until(lambda: any(v.startswith("UP") for v in L.hap_state().values()), 30) is not None, "HAProxy-BD no enruta a ningún escritor tras arrancar el monitor"
    return log


def wait_equal(tabs=None, timeout=30):
    tabs = tabs or L.published_tables("pg-aws")
    t0 = time.time()
    while time.time() - t0 < timeout:
        if L.counts("pg-aws", tabs) == L.counts("pg-oci", tabs):
            return time.time() - t0
        time.sleep(0.3)
    return None


def edge_ok():
    try:
        return fl.req(("127.0.0.1", 18080), "GET", "/api/events", timeout=3)[0] == 200
    except Exception:
        return False


def wait_until(fn, timeout=40, step=0.25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        mon_check()
        try:
            if fn(): return time.time() - t0
        except Exception: pass
        time.sleep(step)
    return None


class WriterWatch:
    """Muestrea con ESCRITURAS REALES (rol de la aplicación) si cada base acepta escrituras. Es un muestreo (~3 por segundo y nodo): "sin doble escritura observada"
    NO equivale a "ausencia de split-brain demostrada"; solo demuestra que en los instantes muestreados no hubo dos escritores."""
    def __init__(self, tag: str, period=0.25):
        self.tag, self.rows, self.stop, self.period = tag, [], threading.Event(), period
        self.t = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        while not self.stop.is_set():
            a, ea = L.probe_write("pg-aws"); t1 = time.time()
            o, eo = L.probe_write("pg-oci")
            self.rows.append((round(t1, 3), a, o, ea[:90], eo[:90]))
            time.sleep(self.period)

    def __enter__(self): self.t.start(); return self
    def __exit__(self, *a):
        self.stop.set(); self.t.join()
        (OUT / f"escritores-{self.tag}.json").write_text(json.dumps([{"t": r[0], "pg-aws_acepta_escritura": r[1], "pg-oci_acepta_escritura": r[2], "error_aws": r[3], "error_oci": r[4]} for r in self.rows], indent=1, ensure_ascii=False) + "\n")

    def summary(self):
        both = [r for r in self.rows if r[1] and r[2]]
        none = [r for r in self.rows if not r[1] and not r[2]]
        return {"muestras": len(self.rows), "con_dos_escritores": len(both), "sin_escritor": len(none),
                "escribe_aws_alguna_vez": any(r[1] for r in self.rows), "escribe_oci_alguna_vez": any(r[2] for r in self.rows)}


# ================================================================== ETAPA A
def stage_a():
    print("== A replicación lógica y sus límites", flush=True)
    fresh_lab("A")
    tabs = L.published_tables("pg-aws")
    info = {}
    # A1: datos reales de la aplicación a través del borde -> pg-aws -> pg-oci
    users = [fl.User(f"a{i}").register_login() for i in range(5)]
    for i, u in enumerate(users):
        st = u.reserve(EV_GENERAL, {"quantity": 2}, uuid.uuid4().hex)[0]
        assert st == 201, st
    seats = [s["id"] for s in json.loads(fl.req(("127.0.0.1", 18080), "GET", f"/api/events/{EV_SEATS}")[1])["seats"]][:2]
    assert users[0].reserve(EV_SEATS, {"quantity": 2, "seat_ids": seats}, uuid.uuid4().hex)[0] == 201
    conv = wait_equal(tabs)
    ca, co = L.counts("pg-aws", tabs), L.counts("pg-oci", tabs)
    digests = {}
    for t in tabs:
        digests[t] = (q1("pg-aws", f"SELECT md5(coalesce(string_agg(x::text, ',' ORDER BY x::text),'')) FROM {t} x"),
                      q1("pg-oci", f"SELECT md5(coalesce(string_agg(x::text, ',' ORDER BY x::text),'')) FROM {t} x"))
    same = {t: a == b for t, (a, b) in digests.items()}
    info["A1"] = {"convergencia_s": None if conv is None else round(conv, 2), "filas_por_tabla": ca, "tablas_identicas": sum(same.values()), "tablas": len(tabs)}
    check("A1 usuarios, sesiones, eventos, reservas, entradas y asientos se replican (conteo y huella md5 idénticos en todas las tablas)",
          conv is not None and ca == co and all(same.values()), info["A1"])
    # A6: el seguidor rechaza escrituras de la aplicación
    ok, err = L.probe_write("pg-oci")
    check("A6 el seguidor rechaza una escritura real del rol de la aplicación (solo lectura)", not ok, err)
    # A2 secuencias
    seq = "event_seats_id_seq"
    la, lo = q1("pg-aws", f"SELECT last_value FROM {seq}"), q1("pg-oci", f"SELECT last_value FROM {seq}")
    rc, out, err = sql("pg-oci", f"BEGIN; INSERT INTO event_seats(event_id, zone_id, row_label, seat_number) SELECT {EV_SEATS}, zone_id, 'Z', 1 FROM event_seats LIMIT 1; ROLLBACK;")
    info["A2"] = {"ultimo_valor_secuencia_aws": la, "ultimo_valor_secuencia_oci": lo, "insercion_en_oci_sin_ajustar": (err.splitlines() or [""])[-1][:160]}
    check("A2 las secuencias NO se replican: pg-oci conserva el valor inicial y una inserción local sin ajustar choca con una clave existente",
          int(la) > int(lo) and rc != 0 and "duplicate key" in err, info["A2"])
    # A3 DDL
    sql("pg-aws", "ALTER TABLE events ADD COLUMN lab_x int DEFAULT 0")
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    sql("pg-aws", "INSERT INTO events (id, name, event_date, venue, city, category, description, price, capacity, ticket_mode, is_demo, status) "
                  "VALUES (990200,'[LAB] ddl',current_date+9,'v','Lima','c','d',10,10,'general',false,'published')")
    time.sleep(6)
    stalled = q1("pg-oci", "SELECT count(*) FROM events WHERE id=990200") == "0"
    logs = run("docker", "logs", "--since", since + "Z", L.cname("pg-oci")).stderr
    msg = next((l.split("ERROR:")[-1].strip() for l in logs.splitlines() if "missing replicated column" in l), "")
    sql("pg-oci", "ALTER TABLE events ADD COLUMN lab_x int DEFAULT 0")
    t_fix = wait_until(lambda: q1("pg-oci", "SELECT count(*) FROM events WHERE id=990200") == "1", 30)
    sql("pg-aws", "DELETE FROM events WHERE id=990200")
    wait_equal(["events"])
    sql("pg-aws", "ALTER TABLE events DROP COLUMN lab_x"); sql("pg-oci", "ALTER TABLE events DROP COLUMN lab_x")
    info["A3"] = {"replicacion_detenida_tras_DDL_solo_en_origen": stalled, "error_en_el_log_del_seguidor": msg[:200], "reanuda_tras_aplicar_el_DDL_en_el_seguidor_s": None if t_fix is None else round(t_fix, 1)}
    check("A3 un cambio de esquema hecho solo en el origen DETIENE la replicación; reanuda al aplicarlo también en el seguidor (el DDL no se replica)",
          stalled and "lab_x" in msg and t_fix is not None, info["A3"])
    # A4 conflicto
    sql("pg-oci", "INSERT INTO events (id, name, event_date, venue, city, category, description, price, capacity, ticket_mode, is_demo, status) "
                  "VALUES (990300,'[LAB] local en seguidor',current_date+9,'v','Lima','c','d',10,10,'general',false,'published')")
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    sql("pg-aws", "INSERT INTO events (id, name, event_date, venue, city, category, description, price, capacity, ticket_mode, is_demo, status) "
                  "VALUES (990300,'[LAB] mismo id en origen',current_date+9,'v','Lima','c','d',10,10,'general',false,'published')")
    sql("pg-aws", "INSERT INTO events (id, name, event_date, venue, city, category, description, price, capacity, ticket_mode, is_demo, status) "
                  "VALUES (990301,'[LAB] posterior al conflicto',current_date+9,'v','Lima','c','d',10,10,'general',false,'published')")
    time.sleep(7)
    blocked = q1("pg-oci", "SELECT count(*) FROM events WHERE id=990301") == "0"
    logs = run("docker", "logs", "--since", since + "Z", L.cname("pg-oci")).stderr
    msg = next((l.split("ERROR:")[-1].strip() for l in logs.splitlines() if "conflict detected" in l or "duplicate key" in l), "")
    sql("pg-oci", "DELETE FROM events WHERE id=990300")
    t_res = wait_until(lambda: q1("pg-oci", "SELECT count(*) FROM events WHERE id=990301") == "1", 40)
    sql("pg-aws", "DELETE FROM events WHERE id IN (990300, 990301)"); wait_equal(["events"])
    info["A4"] = {"cambio_posterior_bloqueado_por_el_conflicto": blocked, "error": msg[:200], "reanuda_tras_resolver_s": None if t_res is None else round(t_res, 1)}
    check("A4 un conflicto de clave en el seguidor bloquea TODOS los cambios posteriores hasta resolverlo a mano", blocked and msg != "" and t_res is not None, info["A4"])
    # A5 retraso, grandes transacciones y datos sin confirmar
    stop = threading.Event(); lag = []
    def sample():
        while not stop.is_set():
            rc, out, _ = sql("pg-aws", "SELECT coalesce((pg_current_wal_lsn() - confirmed_flush_lsn)::bigint,-1), coalesce(extract(epoch from (SELECT replay_lag FROM pg_stat_replication LIMIT 1)),0) "
                                       "FROM pg_replication_slots WHERE slot_name='slot_oci'")
            if rc == 0 and out:
                b, s = out.split("|"); lag.append((float(b), float(s)))
            time.sleep(0.3)
    th = threading.Thread(target=sample, daemon=True); th.start()
    script = "INSERT INTO lab_bulk(payload) VALUES (md5(random()::text));"
    run("docker", "exec", L.cname("pg-aws"), "sh", "-c", f"echo \"{script}\" > /tmp/ins.sql")
    t0 = time.time()
    r = run("docker", "exec", L.cname("pg-aws"), "pgbench", "-n", "-U", "postgres", "-c", "8", "-T", "10", "-f", "/tmp/ins.sql", "nexoeventos")
    tps = next((l.split("=")[1].split()[0] for l in r.stdout.splitlines() if l.startswith("tps")), "?")
    t_catch = wait_until(lambda: q1("pg-aws", "SELECT count(*) FROM lab_bulk") == q1("pg-oci", "SELECT count(*) FROM lab_bulk"), 60)
    stop.set(); th.join()
    n_bulk = q1("pg-aws", "SELECT count(*) FROM lab_bulk")
    # transacción grande
    t1 = time.time()
    sql("pg-aws", "INSERT INTO lab_bulk(payload) SELECT md5(g::text) FROM generate_series(1,300000) g", timeout=60)
    t_big = wait_until(lambda: q1("pg-aws", "SELECT count(*) FROM lab_bulk") == q1("pg-oci", "SELECT count(*) FROM lab_bulk"), 60, 0.1)
    # datos pendientes de confirmar: una transacción abierta no aparece en el seguidor hasta el COMMIT
    before = int(q1("pg-oci", "SELECT count(*) FROM lab_bulk"))
    holder = subprocess.Popen(["docker", "exec", "-i", L.cname("pg-aws"), "psql", "-X", "-q", "-U", "postgres", "-d", "nexoeventos", "-c",
                               "BEGIN; INSERT INTO lab_bulk(payload) SELECT 'pendiente' FROM generate_series(1,1000); SELECT pg_sleep(6); COMMIT;"], stdout=subprocess.DEVNULL)
    time.sleep(3)
    visible_during = int(q1("pg-oci", "SELECT count(*) FROM lab_bulk")) - before
    holder.wait()
    t_after = wait_until(lambda: int(q1("pg-oci", "SELECT count(*) FROM lab_bulk")) - before == 1000, 20, 0.1)
    mb = max((b for b, _ in lag), default=0) / 1024
    info["A5"] = {"carga": f"pgbench 8 clientes 10 s, {tps} tps, {n_bulk} filas", "retraso_maximo_KiB": round(mb, 1), "retraso_maximo_s_pg_stat_replication": round(max((s for _, s in lag), default=0), 3),
                  "alcanza_al_origen_tras_la_carga_s": None if t_catch is None else round(t_catch, 2),
                  "transaccion_de_300000_filas_visible_en_seguidor_tras_commit_s": None if t_big is None else round(t_big, 2),
                  "filas_visibles_en_seguidor_mientras_la_transaccion_sigue_abierta": visible_during, "visibles_tras_commit_s": None if t_after is None else round(t_after, 2)}
    check("A5 con carga el seguidor alcanza al origen; una transacción abierta NO es visible en el seguidor hasta el COMMIT (y se perdería si el origen cae antes)",
          t_catch is not None and t_big is not None and visible_during == 0 and t_after is not None, info["A5"])
    DATA["A"] = info
    sql("pg-aws", "TRUNCATE lab_bulk"); wait_equal(["lab_bulk"])


# ================================================================== helpers de etapas B-E
NET = "nexo-repl-lab_default"


def edge_write_ok(tag="w") -> bool:
    try:
        u = fl.User(tag).register_login()
        return u.reserve(EV_GENERAL, {"quantity": 1}, uuid.uuid4().hex, timeout=5)[0] == 201
    except Exception:
        return False


def kill_node(node: str) -> float:
    t = time.time()
    run("docker", "kill", L.cname(node))
    return t


def ev_t(evs, name, after=0.0, **match):
    return next((e["t"] for e in evs if e["ev"] == name and e["t"] >= after and all(e.get(k) == v for k, v in match.items())), None)


# ================================================================== ETAPA B
def stage_b():
    print("== B fallas seguras: witness caído, partición, aislamiento no confirmable", flush=True)
    # B0: la época impide que dos decisiones concurrentes tengan éxito
    fresh_lab("B0")
    st = L.witness_state(); codes = []; bar = threading.Barrier(2)
    def cas():
        bar.wait(); codes.append(L.w_req("POST", "/set", {"writer": "pg-aws", "expect_epoch": st["epoch"], "ttl": 6})[0])
    ts = [threading.Thread(target=cas) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    check("B0 dos cambios de escritor concurrentes con la misma época: solo uno se acepta (200) y el otro se rechaza (409)", sorted(codes) == [200, 409], f"códigos {sorted(codes)}")

    # B1: witness caído y escritor caído -> no se promueve (falla segura) -> al volver el witness se promueve con fencing
    log = fresh_lab("B1")
    ep0 = L.witness_state()["epoch"]
    with WriterWatch("B1") as ww:
        run("docker", "stop", "-t", "1", L.cname("witness"))
        t_kill = kill_node("pg-aws")
        msleep(14)
        mon_check()
        ev = events(log)
        promoted = [e for e in ev if e["ev"] in ("promote_inicio", "lease_otorgado") and e["t"] >= t_kill]
        excs = [e for e in ev if e["ev"] == "excepcion"]
        oci_writes = L.probe_write("pg-oci")[0]
        hap = L.hap_state()
        msgs = [e for e in ev if e["ev"] == "witness_no_disponible"]
        check("B1 con el witness caído y el escritor caído NO se promueve: sin promote_inicio ni lease, el seguidor sigue rechazando escrituras y HAProxy-BD no enruta a nadie",
              not promoted and not oci_writes and not any(v.startswith("UP") for v in hap.values()) and bool(msgs) and MON.poll() is None,
              {"monitor_vivo_durante_la_caida_del_witness": MON.poll() is None, "excepciones_registradas": [(e["donde"], e["tipo"]) for e in excs], "promociones": len(promoted), "escritura_real_en_oci": oci_writes, "haproxy_db": hap, "registros_witness_no_disponible": len(msgs)})
        run("docker", "start", L.cname("witness"))
        t_w = time.time()
        t_prom = wait_until(lambda: ev_t(events(log), "lease_otorgado", t_w) is not None, 60)
        ev = events(log)
        rec = next((e for e in ev if e["ev"] == "witness_recuperado"), {})
        t_ok = wait_until(edge_write_ok, 40)
        beats = [e for e in ev if e["ev"] == "latido" and e["t"] >= t_w]
        d = {"monitor_sigue_vivo_y_emite_latidos_tras_volver_el_witness": len(beats) > 0, "epoca_antes": ep0, "epoca_vista_tras_reiniciar_witness": rec.get("estado", {}).get("epoch"), "promocion_tras_volver_el_witness_s": None if t_prom is None else round(t_prom, 1),
             "escritura_por_el_borde_ok_tras_s": None if t_ok is None else round(t_ok, 1), "sondeo": ww.summary()}
        DATA["B1"] = d
    check("B1 al volver el witness (con su época persistida) se promueve con aislamiento confirmado y la aplicación vuelve a escribir; nunca hubo dos escritores",
          t_prom is not None and t_ok is not None and d["epoca_vista_tras_reiniciar_witness"] == ep0 and d["sondeo"]["con_dos_escritores"] == 0 and d["monitor_sigue_vivo_y_emite_latidos_tras_volver_el_witness"], d)

    # B2: partición del escritor; el aislamiento por el plano de control SÍ se confirma -> promoción segura
    log = fresh_lab("B2")
    with WriterWatch("B2") as ww:
        t_part = time.time()
        run("docker", "network", "disconnect", NET, L.cname("pg-aws"))
        t_prom = wait_until(lambda: ev_t(events(log), "lease_otorgado", t_part) is not None, 60)
        msleep(2)
        ev = events(log)
        f = next((e for e in ev if e["ev"] == "fence" and e["t"] >= t_part), {})
        w_dest = next((e for e in ev if e["ev"] == "escritura_destino" and e["t"] >= t_part), {})
        fin = next((e for e in ev if e["ev"] == "verificacion_final" and e["t"] >= t_part), {})
        t_lease = ev_t(ev, "lease_otorgado", t_part)
        order = f.get("t", 9e9) < w_dest.get("t", 9e9) <= (t_lease or 0)
        t_ok = wait_until(edge_write_ok, 30)
        # vías de escritura hacia el antiguo escritor con OCI ya promovido: TCP directo, pasarela de BD de cada app y regreso del contenedor tras sanar la red
        viaA = L.probe_write("pg-aws")[0]
        rc_gw, _, err_gw = L.sql("pg-oci", "INSERT INTO lab_probe(node) VALUES ('via_pasarela_aws')", user="nexoeventos_app", origin="pg-oci", timeout=4)
        gw_aws_sidecar = run("docker", "exec", L.cname("app-aws"), "python", "-c",
                             "import psycopg;c=psycopg.connect('host=127.0.0.1 port=5432 dbname=nexoeventos user=nexoeventos_app password=lab-local-only-app connect_timeout=3');"
                             "c.execute(\"INSERT INTO lab_probe(node) VALUES ('via_gateway_app_aws')\");c.commit();print(c.execute('SELECT inet_server_addr()').fetchone()[0])")
        ip_oci = run("docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", L.cname("pg-oci")).stdout.strip()
        gw_node_ip = gw_aws_sidecar.stdout.strip()
        # REGRESO del antiguo escritor SIN monitor: el arranque cerrado (witness != yo => pg_hba que rechaza todo) debe bastar por sí solo
        stop_monitor()
        run("docker", "network", "connect", "--alias", "pg-aws", NET, L.cname("pg-aws"))
        run("docker", "start", L.cname("pg-aws"))
        t_back = time.time(); window = []
        wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 40)
        for _ in range(25):
            okw, ew = L.app_connect("pg-aws", write=True)
            oko, eo = L.app_connect("pg-aws", write=True, override=True)
            window.append({"t_s": round(time.time() - t_back, 2), "escritura_nueva_conexion_aceptada": okw, "escritura_con_anulacion_aceptada": oko, "error": ew[:110]})
            time.sleep(0.25)
        boot_log = run("docker", "logs", L.cname("pg-aws")).stderr
        boot_line = next((l for l in reversed(boot_log.splitlines()) if "[lab-entry]" in l), "")
        accepted = [w for w in window if w["escritura_nueva_conexion_aceptada"] or w["escritura_con_anulacion_aceptada"]]
        log = start_monitor("B2-tras-regreso")
        d = {"rto_bd_hasta_lease_s": None if t_lease is None else round(t_lease - t_part, 1), "fence": f, "escritura_destino": w_dest, "verificacion_final": fin, "orden_fence_antes_de_escribir_en_destino": order,
             "escritura_por_el_borde_ok": t_ok is not None,
             "escritura_real_directa_al_antiguo_con_OCI_ya_promovido": viaA,
             "escritura_real_por_pasarela_de_BD_de_app-aws_llega_a": {"ip_del_servidor_que_la_atendio": gw_node_ip, "ip_de_pg-oci": ip_oci, "atendida_por_pg-oci": gw_node_ip == ip_oci},
             "antiguo_escritor_reiniciado_tras_sanar_la_red_SIN_monitor": {"arranque": boot_line, "intentos_de_escritura_real": len(window), "aceptadas": len(accepted),
                                                                           "primeras_muestras": window[:3], "ultima_muestra": window[-1]},
             "sondeo": ww.summary()}
        DATA["B2"] = d
    check("B2 partición del escritor: se aísla y se COMPRUEBA con una escritura real que ya no escribe ANTES de abrir el destino; luego el destino escribe y el antiguo sigue sin poder",
          bool(t_lease) and f.get("resultado") == "confirmado" and f.get("escritura_real_aceptada") is False and w_dest.get("aceptada") is True and order and fin.get("antiguo_escribe") is False and t_ok is not None
          and d["escritura_real_directa_al_antiguo_con_OCI_ya_promovido"] is False and d["escritura_real_por_pasarela_de_BD_de_app-aws_llega_a"]["atendida_por_pg-oci"],
          {k: v for k, v in d.items() if k != "sondeo"})
    ex = d["antiguo_escritor_reiniciado_tras_sanar_la_red_SIN_monitor"]
    check("B2 el antiguo escritor que REAPARECE (contenedor reiniciado y red restablecida, con el monitor detenido) arranca cerrado y rechaza TODA escritura real directa, también con intento de anular el solo-lectura",
          "modo fenced" in ex["arranque"] and ex["aceptadas"] == 0 and ex["intentos_de_escritura_real"] >= 20, ex)
    check("B2 muestreo con escrituras reales (~3 por segundo y nodo) durante toda la conmutación y el regreso: ninguna muestra con dos escritores (NO demuestra la ausencia de split-brain: solo no se observó)",
          d["sondeo"]["con_dos_escritores"] == 0, d["sondeo"])
    fl_ev = [e for e in events(OUT / "eventos-B2.jsonl") if e["ev"] == "fence_en_linea"]
    fe = fl_ev[0] if fl_ev else {}
    check("B2 el aislamiento EN LÍNEA del escritor particionado se verificó por efecto (pg_hba nuevo, sesiones terminadas, escritura real y escritura con anulación rechazadas) antes de detenerlo",
          bool(fe) and fe.get("verificado") is True and fe.get("escritura_real_conexion_nueva_aceptada") is False and fe.get("escritura_real_con_anulacion_aceptada") is False, {k: fe.get(k) for k in ("verificado", "modo_cerrado", "solo_lectura_global", "sesiones_app_terminadas", "rechazo_conexion_nueva", "rechazo_con_anulacion")})

    # B3: el aislamiento NO se puede confirmar -> no se promueve; al sanar la partición vuelve el escritor original
    log = fresh_lab("B3", env={"LAB_FENCE_FAIL": "1"})
    with WriterWatch("B3") as ww:
        t_part = time.time()
        run("docker", "network", "disconnect", NET, L.cname("pg-aws"))
        t_ab = wait_until(lambda: ev_t(events(log), "promote_abortada", t_part) is not None, 60)
        msleep(8)
        ev = events(log)
        ab = next((e for e in ev if e["ev"] == "promote_abortada" and e["t"] >= t_part), {})
        granted = ev_t(ev, "lease_otorgado", t_part) is not None
        oci_w = L.probe_write("pg-oci")[0]
        edge_w = edge_write_ok("b3")
        hap = L.hap_state()
        check("B3 aislamiento no confirmable: NO se promueve, el seguidor sigue rechazando escrituras reales y la aplicación no puede escribir (falla segura: sin servicio, no dos escritores)",
              t_ab is not None and not granted and not oci_w and not edge_w and not any(v.startswith("UP") for v in hap.values()),
              {"motivo": ab.get("motivo"), "lease_a_pg-oci": granted, "escritura_real_en_oci": oci_w, "escritura_por_el_borde": edge_w, "haproxy_db": hap})
        run("docker", "network", "connect", "--alias", "pg-aws", NET, L.cname("pg-aws"))   # sin --alias se pierde el nombre DNS del servicio
        t_h = time.time()
        t_rest = wait_until(lambda: ev_t(events(log), "lease_restaurado", t_h) is not None, 60)
        t_ok = wait_until(lambda: edge_write_ok("b3b"), 40)
        same = wait_equal(["reservations", "users", "events"], 40)
        d = {"sondeo": ww.summary(), "servicio_restaurado_tras_sanar_s": None if t_ok is None else round(t_ok, 1), "lease_devuelto_a_pg-aws_s": None if t_rest is None else round(t_rest, 1),
             "replicacion_reanudada_y_conteos_iguales": same is not None}
        DATA["B3"] = d
    check("B3 al sanar la partición el lease vuelve al escritor ORIGINAL (nunca al seguidor), el servicio se restablece y la replicación se reanuda",
          t_rest is not None and t_ok is not None and same is not None, d)
    check("B3 muestreo con escrituras reales: nunca dos escritores y pg-oci nunca escribió", d["sondeo"]["con_dos_escritores"] == 0 and not d["sondeo"]["escribe_oci_alguna_vez"], d["sondeo"])


    # B4: default_transaction_read_only NO es fencing: la propia aplicación puede anularlo; el pg_hba cerrado sí lo impide
    fresh_lab("B4")
    stop_monitor()                               # baseline sin monitor: el monitor (correctamente) volvería a cerrar el nodo expuesto
    pre = L.set_mode("pg-oci", "open")           # simula un seguidor protegido solo por el ajuste de solo-lectura
    ok_ro, e_ro = L.app_connect("pg-oci", write=True, origin="pg-oci")
    ok_ov, e_ov = L.app_connect("pg-oci", write=True, override=True, origin="pg-oci")
    post = L.set_mode("pg-oci", "fenced")
    ok_ro2, e_ro2 = L.app_connect("pg-oci", write=True, origin="pg-oci")
    ok_ov2, e_ov2 = L.app_connect("pg-oci", write=True, override=True, origin="pg-oci")
    DATA["B4"] = {"solo_lectura_por_GUC_escritura_directa": [ok_ro, e_ro], "solo_lectura_por_GUC_con_anulacion_desde_la_sesion": [ok_ov, e_ov],
                  "con_pg_hba_cerrado_escritura_directa": [ok_ro2, e_ro2], "con_pg_hba_cerrado_con_anulacion": [ok_ov2, e_ov2]}
    check("B4 solo default_transaction_read_only NO basta: la aplicación lo anula desde su propia sesión y escribe; con el pg_hba cerrado la misma conexión nueva es rechazada",
          not ok_ro and ok_ov and not ok_ro2 and not ok_ov2 and "pg_hba.conf rejects" in e_ov2, DATA["B4"])
    # guardia secundaria: un nodo no escritor que quede ABIERTO es detectado y cerrado por el monitor
    L.set_mode("pg-oci", "open")
    t_g = time.time()
    log4 = start_monitor("B4-guardia")
    t_iso = wait_until(lambda: ev_t(events(log4), "nodo_no_escritor_aislado", t_g) is not None, 30)
    ok_g, e_g = L.app_connect("pg-oci", write=True, override=True, origin="pg-oci")
    DATA["B4"]["guardia_del_monitor"] = {"aislado_tras_s": None if t_iso is None else round(t_iso, 1), "escritura_con_anulacion_despues": [ok_g, e_g]}
    check("B4 la guardia del monitor detecta un nodo no escritor ABIERTO, lo cierra y una escritura real con anulación posterior es rechazada por pg_hba",
          t_iso is not None and not ok_g and "pg_hba.conf rejects" in e_g, DATA["B4"]["guardia_del_monitor"])

    # B5: arranque cerrado ante la duda: el escritor legítimo reinicia con el witness caído y NO abre el acceso (se sacrifica disponibilidad, no seguridad)
    fresh_lab("B5")
    run("docker", "stop", "-t", "1", L.cname("witness"))
    stop_monitor()
    run("docker", "restart", "-t", "1", L.cname("pg-aws"))
    wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 40)
    ok5, e5 = L.app_connect("pg-aws", write=True)
    line5 = next((l for l in reversed(run("docker", "logs", L.cname("pg-aws")).stderr.splitlines()) if "[lab-entry]" in l), "")
    run("docker", "start", L.cname("witness"))
    wait_until(lambda: L.w_req("GET", "/state")[0] == 200, 30)
    run("docker", "restart", "-t", "1", L.cname("pg-aws"))
    wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 40)
    ok5b, e5b = L.app_connect("pg-aws", write=True)
    line5b = next((l for l in reversed(run("docker", "logs", L.cname("pg-aws")).stderr.splitlines()) if "[lab-entry]" in l), "")
    DATA["B5"] = {"con_witness_caido": {"arranque": line5, "escritura_real_aceptada": ok5, "error": e5}, "con_witness_vivo_y_me_declara_escritor": {"arranque": line5b, "escritura_real_aceptada": ok5b}}
    check("B5 el escritor legítimo que reinicia con el witness caído arranca CERRADO (falla cerrada: sin escrituras); con el witness disponible y declarándolo escritor, abre",
          "modo fenced" in line5 and not ok5 and "modo open" in line5b and ok5b, DATA["B5"])


# ================================================================== ETAPA C
def crash_under_load(tag: str, induce_s: float = 0.0, sync: bool = False, hook=None, env=None) -> dict:
    log = fresh_lab(tag, sync=sync, env=env)
    users = [new_user(f"c{i}") for i in range(8)]
    acked, att = [], []
    stop, killed = threading.Event(), threading.Event()
    lag = []

    def worker(u):
        while not stop.is_set():
            key = uuid.uuid4().hex
            for _ in range(60):
                t0 = time.time()
                try:
                    st, js, srv = u.reserve(EV_GENERAL, {"quantity": 1}, key, timeout=3)
                    att.append((t0, st, time.time()))
                    if st in (200, 201):
                        acked.append((time.time(), key, js["reservation_id"], st)); break
                    if st < 500: break
                except Exception:
                    att.append((t0, 0, time.time()))
                if stop.is_set(): break
                time.sleep(0.25)
            time.sleep(0.05)

    def sampler():
        while not killed.is_set():
            rc, out, _ = sql("pg-aws", "SELECT coalesce((pg_current_wal_lsn() - confirmed_flush_lsn)::bigint,-1) FROM pg_replication_slots WHERE slot_name='slot_oci'", timeout=3)
            if rc == 0 and out.lstrip("-").isdigit():
                lag.append((time.time(), int(out)))
            time.sleep(0.3)

    ths = [threading.Thread(target=worker, args=(users[i],), daemon=True) for i in range(len(users))] + [threading.Thread(target=sampler, daemon=True)]
    with fl.Load() as load:
        [t.start() for t in ths]
        time.sleep(4)
        t_dis = None; win = None
        if induce_s:
            sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE"); t_dis = time.time()
            time.sleep(induce_s)
        elif hook:
            win = hook()
        else:
            time.sleep(2)
        t_kill = kill_node("pg-aws"); killed.set()
        t_lease = wait_until(lambda: ev_t(events(log), "lease_otorgado", t_kill) is not None, 90)
        msleep(8)
        stop.set(); [t.join() for t in ths[:-1]]
    ev = events(log)
    time.sleep(1)
    ids = set(q1("pg-oci", f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
    lost = [a for a in acked if a[2] not in ids]
    acked_ids = {a[2] for a in acked}
    orf_dir = OUT / f"huerfanas-{tag}"
    orf_summary = L.orphans("pg-aws", "pg-oci", str(orf_dir))
    orf_file = sorted(orf_dir.glob("huerfanas-pg-aws-*.json"))[-1]
    orf_rows = json.loads(orf_file.read_text())["filas"].get("reservations", [])
    orf_ids = {r["id"] for r in orf_rows}
    orf_confirmed = orf_ids & acked_ids
    orf_uncertain = orf_ids - acked_ids
    orf_dups = orf_summary["duplicados_logicos_por_idempotency_key"]
    unacked = len(ids - acked_ids)
    rc_count = q1("pg-oci", f"SELECT reserved_count FROM events WHERE id={EV_GENERAL}")
    sum_q = q1("pg-oci", f"SELECT coalesce(sum(quantity),0) FROM reservations WHERE event_id={EV_GENERAL}")
    n_res, n_keys = q1("pg-oci", f"SELECT count(*), count(DISTINCT idempotency_key) FROM reservations WHERE event_id={EV_GENERAL}").split("|")
    replayed = sum(1 for a in acked if a[3] == 200)
    wf = sorted((t0, st) for t0, st, _ in att if t0 >= t_kill and not (200 <= st < 300))
    last_fail = max((t0 for t0, st in wf), default=None)
    first_ok_w = next((t_e for t0, st, t_e in sorted(att) if last_fail is not None and t0 > last_fail and 200 <= st < 300), None)
    off = time.time() - time.monotonic()      # fl.Load usa reloj monotónico; aquí todo va en reloj de pared
    rrows = sorted((r[0] + off, r[1], r[2], r[3], r[4] + off) for r in load.rows)
    reads_bad = [r for r in rrows if r[0] >= t_kill and r[1] != 200]
    last_rb = max((r[0] for r in reads_bad), default=None)
    first_bad_r = min((r[0] for r in reads_bad), default=None)
    first_ok_r = next((r[4] for r in rrows if last_rb is not None and r[0] > last_rb and r[1] == 200), None)
    (OUT / f"c1-{tag}-lineas-de-tiempo.json").write_text(json.dumps({"t_kill": t_kill,
        "lecturas": [{"t_s_desde_la_caida": round(r[0] - t_kill, 3), "http": r[1], "latencia_ms": round(r[2] * 1000, 1), "atendida_por_o_error": r[3]} for r in rrows],
        "escrituras": [{"t_s_desde_la_caida": round(t0 - t_kill, 3), "http_0_es_error_de_red": st, "fin_s": round(te - t_kill, 3)} for t0, st, te in sorted(att)]}) + "\n")
    pre = [b for t, b in lag if t < t_kill]
    codes_w, codes_r = {}, {}
    for t0, st, _ in att:
        if not 200 <= st < 300: codes_w[str(st or "error_de_red")] = codes_w.get(str(st or "error_de_red"), 0) + 1
    for r in load.rows:
        if r[1] != 200: codes_r[str(r[1] or r[3])] = codes_r.get(str(r[1] or r[3]), 0) + 1
    t_first_probe = ev_t(ev, "sonda_escritura_fallida", t_kill)
    t_fence = ev_t(ev, "fence", t_kill); t_oci_ok = ev_t(ev, "lease_otorgado", t_kill); t_hap = ev_t(ev, "haproxy_db_enruta", t_kill)
    d = {
        "induccion_de_retraso_s": induce_s,
        "RTO_escritura_s_desde_la_orden_de_caida": None if first_ok_w is None else round(first_ok_w - t_kill, 2),
        "RTO_lectura_s": None if first_ok_r is None else round(first_ok_r - t_kill, 2),
        "lectura_primer_error_s": None if first_bad_r is None else round(first_bad_r - t_kill, 2),
        "lectura_ultimo_error_s": None if last_rb is None else round(last_rb - t_kill, 2),
        "deteccion_primera_sonda_fallida_s": None if t_first_probe is None else round(t_first_probe - t_kill, 2),
        "aislamiento_confirmado_s": None if t_fence is None else round(t_fence - t_kill, 2),
        "lease_otorgado_s": None if t_oci_ok is None else round(t_oci_ok - t_kill, 2),
        "haproxy_db_enruta_s": None if t_hap is None else round(t_hap - t_kill, 2),
        "escrituras_intentos": len(att), "escrituras_confirmadas_al_cliente": len(acked), "de_ellas_repetidas_200_por_idempotencia": replayed,
        "errores_http_escritura": codes_w, "lecturas": len(load.rows), "errores_http_lectura": codes_r,
        "retraso_de_replicacion_maximo_antes_de_caer_KiB": round(max(pre, default=0) / 1024, 1),
        "latencia_de_confirmacion_ms_p50_antes_de_la_caida": _pct([te - t0 for t0, st, te in att if 200 <= st < 300 and t0 < t_kill], 0.5),
        "latencia_de_confirmacion_ms_p95_antes_de_la_caida": _pct([te - t0 for t0, st, te in att if 200 <= st < 300 and t0 < t_kill], 0.95),
        "intentos_no_exitosos_(reintentos_con_la_misma_clave)": sum(1 for t0, st, te in att if not 200 <= st < 300),
        "RPO_transacciones_confirmadas_al_cliente_PERDIDAS": len(lost),
        "confirmaciones_al_cliente_durante_el_bloqueo_inducido": None if not win else sum(1 for a in acked if win[0] + 0.5 <= a[0] <= win[1]),
        "huerfanas_en_la_antigua_primaria_reservas": len(orf_ids),
        "huerfanas_confirmadas_al_cliente_(perdidas)": len(orf_confirmed),
        "huerfanas_NO_confirmadas_al_cliente_(INCIERTAS)": len(orf_uncertain),
        "huerfanas_con_clave_repetida_en_la_nueva_primaria_(duplicado_logico)": len(orf_dups),
        "perdidas_confirmadas_coinciden_con_las_huerfanas_confirmadas": {a[2] for a in lost} == orf_confirmed,
        "RPO_ventana_s_(caida_menos_la_confirmacion_perdida_mas_antigua)": None if not lost else round(t_kill - min(a[0] for a in lost), 2),
        "filas_en_la_nueva_primaria_sin_confirmar_al_cliente": unacked,
        "reservas_en_nueva_primaria": int(n_res), "claves_distintas": int(n_keys), "reserved_count": rc_count, "suma_cantidades": sum_q,
    }
    DATA.setdefault("F2" if sync else "C1", {})[tag] = d
    (OUT / f"c1-{tag}-perdidas.json").write_text(json.dumps([{"reservation_id": a[2], "idempotency_key": a[1], "t_ack": a[0], "t_kill": t_kill} for a in lost], indent=2) + "\n")
    check(f"C1 {tag}: sin sobreventa ni duplicados (reserved_count == suma de cantidades; una reserva por clave de idempotencia) tras la conmutación",
          rc_count == sum_q and n_res == n_keys, {k: d[k] for k in ("reservas_en_nueva_primaria", "claves_distintas", "reserved_count", "suma_cantidades")})
    check(f"C1 {tag}: el servicio de escritura se recupera por el borde tras la caída de la primaria", d["RTO_escritura_s_desde_la_orden_de_caida"] is not None and t_lease is not None,
          {k: d[k] for k in ("RTO_escritura_s_desde_la_orden_de_caida", "RTO_lectura_s", "lease_otorgado_s")})
    return d


def stage_c():
    print("== C caída de la primaria con carga de reservas", flush=True)
    for i in range(1, 4):
        d = crash_under_load(f"C1-natural-{i}")
        print("   ", json.dumps({k: d[k] for k in ("RTO_escritura_s_desde_la_orden_de_caida", "RTO_lectura_s", "RPO_transacciones_confirmadas_al_cliente_PERDIDAS", "errores_http_escritura")}, ensure_ascii=False), flush=True)
    d = crash_under_load("C1-retraso-inducido", induce_s=3.0)
    check("C1 retraso inducido (replicación pausada 3 s antes de caer): se observan transacciones confirmadas al cliente que se pierden; ese es el RPO real bajo retraso",
          d["RPO_transacciones_confirmadas_al_cliente_PERDIDAS"] > 0, {k: d[k] for k in ("RPO_transacciones_confirmadas_al_cliente_PERDIDAS", "RPO_ventana_s_(caida_menos_la_confirmacion_perdida_mas_antigua)")})
    after_commit("C2a-natural", induce=False)


def after_commit(tag: str, induce: bool, sync: bool = False) -> dict:
    """Cae la BD DESPUÉS de confirmar la reserva y ANTES de que el cliente reciba la respuesta HTTP (un proxy retiene la respuesta y luego la descarta)."""
    log = fresh_lab(tag, sync=sync)
    L.dc("up", "-d", "cut-proxy")
    wait_until(lambda: fl.req(("127.0.0.1", 18091), "GET", "/held", timeout=2)[0] == 200, 30)
    u = new_user("cc", addr=("127.0.0.1", 18090))
    K = uuid.uuid4().hex
    if induce:
        sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
    out = {}
    def send():
        try:
            out["r"] = u._do("POST", f"/api/events/{EV_GENERAL}/reservations", {"quantity": 1}, {"Idempotency-Key": K, "X-Lab-Drop-Response": "1"}, ("127.0.0.1", 18090), timeout=30)
        except Exception as e:
            out["exc"] = type(e).__name__
    th = threading.Thread(target=send); th.start()
    held = wait_until(lambda: json.loads(fl.req(("127.0.0.1", 18091), "GET", "/held", timeout=2)[1])["held"] >= 1, 20)
    orig_id = q1("pg-aws", f"SELECT id FROM reservations WHERE idempotency_key='{K}'")
    if not induce:
        wait_until(lambda: q1("pg-oci", f"SELECT count(*) FROM reservations WHERE idempotency_key='{K}'") == "1", 20)
    replicated_before_crash = q1("pg-oci", f"SELECT count(*) FROM reservations WHERE idempotency_key='{K}'") == "1"
    t_kill = kill_node("pg-aws")
    fl.req(("127.0.0.1", 18091), "POST", "/release?mode=drop", timeout=3)
    th.join(30)
    # el cliente no recibió nada: reintenta con la MISMA clave por el borde
    u.addr = ("127.0.0.1", 18080)
    final, tries = None, []
    for _ in range(80):
        try:
            st, js, srv = u.reserve(EV_GENERAL, {"quantity": 1}, K, timeout=3)
            tries.append(st)
            if st < 500:
                final = (st, js); break
        except Exception as e:
            tries.append(type(e).__name__)
        time.sleep(0.25)
    t_final = time.time()
    t_lease = wait_until(lambda: ev_t(events(log), "lease_otorgado", t_kill) is not None, 60)
    ev = events(log)
    new_id = final[1].get("reservation_id") if final and final[1] else None
    rows = q1("pg-oci", f"SELECT count(*) FROM reservations WHERE idempotency_key='{K}'")
    d = {"respuesta_retenida_tras_confirmar": held is not None, "reserva_en_la_primaria_antes_de_caer": orig_id, "replicada_antes_de_caer": replicated_before_crash,
         "cliente_no_recibio_respuesta": "exc" in out, "reintentos_con_la_misma_clave": tries, "estado_final": None if not final else final[0],
         "replayed": None if not final else final[1].get("replayed"), "reservation_id_final": new_id, "misma_reserva": new_id == orig_id,
         "reservas_con_esa_clave_en_la_nueva_primaria": rows, "tiempo_hasta_respuesta_valida_s": round(t_final - t_kill, 1), "idempotency_key": K}
    DATA.setdefault("C2", {})[tag] = d
    if not induce:
        check("C2a caída tras confirmar y antes de responder (con la reserva ya replicada): el reintento con la misma clave devuelve 200 con LA MISMA reserva, sin duplicar",
              d["cliente_no_recibio_respuesta"] and replicated_before_crash and d["estado_final"] == 200 and d["replayed"] is True and d["misma_reserva"] and rows == "1", d)
    else:
        check("C2b caída tras confirmar y antes de responder SIN replicar: la reserva original se pierde con la primaria y el reintento crea OTRA (201); el cliente nunca vio dos, pero queda una huérfana en la antigua primaria",
              d["cliente_no_recibio_respuesta"] and not replicated_before_crash and d["estado_final"] == 201 and not d["misma_reserva"] and rows == "1", d)
    return d


# ================================================================== ETAPA D
def stage_d():
    print("== D failback manual seguro (parte del caso C2b: reserva confirmada y no replicada)", flush=True)
    log = events  # alias legible
    d0 = after_commit("D-prep", induce=True)
    evlog = OUT / "eventos-D-prep.jsonl"
    L.EVENT_LOG = str(OUT / "eventos-D-failback.jsonl"); Path(L.EVENT_LOG).unlink(missing_ok=True)
    n_prom0 = sum(1 for e in events(evlog) if e["ev"] == "promote_inicio")
    # D1: reinicio "a mano" de la antigua primaria (monitor en marcha, pero sin depender de él): arranca CERRADA y rechaza toda escritura real
    run("docker", "start", L.cname("pg-aws"))
    wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 40)
    win = []
    for _ in range(20):
        okw, ew = L.app_connect("pg-aws", write=True)
        oko, eo = L.app_connect("pg-aws", write=True, override=True)
        win.append((okw, oko, ew[:100])); time.sleep(0.25)
    boot = next((l for l in reversed(run("docker", "logs", L.cname("pg-aws")).stderr.splitlines()) if "[lab-entry]" in l), "")
    hap = L.hap_state()
    check("D1 la antigua primaria reiniciada a mano arranca CERRADA (witness: otro escritor), no recibe tráfico de HAProxy-BD y rechaza 20 intentos de escritura real directa, también con anulación del solo-lectura",
          "modo fenced" in boot and not any(w[0] or w[1] for w in win) and not hap.get("pg-aws", "").startswith("UP"),
          {"arranque": boot, "intentos": len(win), "aceptados": sum(1 for w in win if w[0] or w[1]), "ejemplo_de_rechazo": win[0][2], "haproxy_db": hap, "witness": L.witness_state()})
    # D2: rescatar lo que solo existe en la antigua primaria (fuera de Docker) antes de tocarla
    summ = L.orphans("pg-aws", "pg-oci", str(OUT))
    files = sorted(OUT.glob("huerfanas-pg-aws-*.json"))
    dup = summ["duplicados_logicos_por_idempotency_key"]
    check("D2 las filas confirmadas solo en la antigua primaria se exportan a un archivo FUERA de Docker y se detecta el duplicado lógico por Idempotency-Key (misma clave, otra reserva)",
          bool(files) and summ["tablas_con_huerfanas"].get("reservations", 0) >= 1 and any(x["idempotency_key"] == d0["idempotency_key"] for x in dup), {"archivo": files[-1].name if files else None, **summ})
    # D3: reconstruir la antigua primaria como seguidora (esto SÍ borra sus datos, ya rescatados)
    L.reseed("pg-aws", "pg-oci")
    tabs = L.published_tables("pg-oci")
    sync = wait_equal(tabs, 30) is not None
    app_w = L.probe_write("pg-aws")[0]
    wst = L.witness_state(); hap = L.hap_state()
    prom_now = sum(1 for e in events(evlog) if e["ev"] == "promote_inicio")
    check("D3 la antigua primaria se reconstruye como seguidora de la nueva (conteos idénticos), rechaza escrituras de la aplicación y el escritor sigue siendo pg-oci: no hubo retorno automático",
          sync and not app_w and wst["writer"] == "pg-oci" and not hap.get("pg-aws", "").startswith("UP") and prom_now == n_prom0, {"witness": wst, "haproxy_db": hap, "promociones_automaticas_desde_la_caida": prom_now - n_prom0})
    # D4: retorno PLANIFICADO a pg-aws con tráfico en curso
    errs = {"escritura": 0, "ok": 0}
    stop = threading.Event()
    uu = new_user("d4")
    def w():
        while not stop.is_set():
            try:
                st = uu.reserve(EV_GENERAL, {"quantity": 1}, uuid.uuid4().hex, timeout=3)[0]
                errs["ok" if st == 201 else "escritura"] += 1
            except Exception:
                errs["escritura"] += 1
            time.sleep(0.1)
    th = threading.Thread(target=w, daemon=True); th.start()
    time.sleep(2)
    t_s = time.time()
    with L.paused():
        ok = L.promote("pg-aws", planned=True)
    time.sleep(4); stop.set(); th.join()
    ev = events(Path(L.EVENT_LOG))
    t_l = ev_t(ev, "lease_otorgado", t_s)
    cnt_ok = edge_write_ok("d4b")
    wst = L.witness_state()
    summ2 = None
    summ2 = L.orphans("pg-oci", "pg-aws", str(OUT))
    L.reseed("pg-oci", "pg-aws")
    same = wait_equal(L.published_tables("pg-aws"), 30) is not None
    probe_aws = L.probe_write("pg-aws")[0]; probe_oci = L.probe_write("pg-oci")[0]
    DATA["D4"] = {"retorno_planificado_ok": ok, "escritura_interrumpida_s_aprox": None if t_l is None else round(t_l - t_s, 1), "intentos_ok": errs["ok"], "intentos_con_error": errs["escritura"],
                  "huerfanas_en_la_que_se_retira": summ2["tablas_con_huerfanas"] if summ2 else None, "witness": wst}
    check("D4 retorno planificado a pg-aws (drenado, conteos iguales, aislamiento verificado, lease con época nueva): la aplicación escribe, la antigua se reconstruye como seguidora sin huérfanas y solo pg-aws acepta escrituras",
          ok and cnt_ok and wst["writer"] == "pg-aws" and not summ2["tablas_con_huerfanas"] and same and probe_aws and not probe_oci, DATA["D4"])


# ================================================================== ETAPA E
def stage_e():
    print("== E causa del HTTP 500 con la BD no disponible", flush=True)
    fresh_lab("E")
    u = fl.User("e").register_login()
    stop_monitor()
    assert wait_until(lambda: not any(v.startswith("UP") for v in L.hap_state().values()), 30) is not None
    L.dc("up", "-d", "app-stale", "haproxy-db-stale")
    wait_until(lambda: fl.req(("127.0.0.1", 18003), "GET", "/health", timeout=2)[0] == 200, 40)
    paths = [("GET", "/health"), ("GET", "/ready"), ("GET", "/api/events"), ("GET", f"/api/events/{EV_SEATS}"), ("GET", "/api/auth/session"), ("GET", "/api/me/reservations"), ("POST", f"/api/events/{EV_GENERAL}/reservations")]
    table = {}
    for label, addr in (("imagen_actual_(codigo_del_repositorio)", ("127.0.0.1", 18001)), ("imagen_antigua_(nexoeventos-dev-backend:latest, 22-oct)", ("127.0.0.1", 18003))):
        row = {}
        for m, p in paths:
            try:
                if m == "GET":
                    st, js, _ = u._do("GET", p, addr=addr, timeout=8)
                else:
                    st, js, _ = u.reserve(EV_GENERAL, {"quantity": 1}, uuid.uuid4().hex, addr=addr, timeout=8)
            except Exception as e:
                st = type(e).__name__
            row[f"{m} {p}"] = st
        table[label] = row
    handlers = {}
    for c, nm in (("nexo-repl-lab-app-aws-1", "actual"), ("nexo-repl-lab-app-stale-1", "antigua")):
        handlers[nm] = run("docker", "exec", c, "python", "-c", "from app.main import app; print(sorted(k.__name__ for k in app.exception_handlers))").stdout.strip()
    md5s = {nm: run("docker", "exec", c, "md5sum", "/app/app/main.py").stdout.split()[0] for c, nm in (("nexo-repl-lab-app-aws-1", "actual"), ("nexo-repl-lab-app-stale-1", "antigua"))}
    repo_md5 = run("md5", "-q", str(HERE.parents[1] / "backend" / "app" / "main.py")).stdout.strip()
    created = run("docker", "image", "inspect", "-f", "{{.Created}}", "nexoeventos-dev-backend:latest").stdout.strip()
    commit = run("/usr/bin/git", "-C", str(HERE.parents[1]), "log", "-1", "--format=%h %ad %s", "--date=short", "-S", "database_unavailable", "--", "backend/app/main.py").stdout.strip()
    tb = run("docker", "logs", "--tail", "300", "nexo-repl-lab-app-stale-1").stderr
    last_exc = [l for l in tb.splitlines() if l.startswith(("sqlalchemy.exc.", "psycopg."))][-1:]
    L.dc("rm", "-sf", "haproxy-db-stale", "app-stale", check=False)
    DATA["E"] = {"codigos_http_con_la_BD_no_disponible": table, "manejadores_de_excepcion_registrados": handlers, "md5_main_py": {**md5s, "repositorio": repo_md5},
                 "imagen_antigua_creada": created, "commit_que_agrego_el_manejador": commit, "excepcion_final_en_la_imagen_antigua": last_exc}
    cur, old = table["imagen_actual_(codigo_del_repositorio)"], table["imagen_antigua_(nexoeventos-dev-backend:latest, 22-oct)"]
    check("E1 con el código ACTUAL del repositorio la BD no disponible produce 503 (no 500) en lecturas y escrituras, y 401/503 según haya sesión válida; /health sigue en 200",
          cur["GET /api/events"] == 503 and cur["POST /api/events/%d/reservations" % EV_GENERAL] == 503 and cur["GET /health"] == 200 and cur["GET /api/auth/session"] == 503, cur)
    check("E2 la imagen antigua usada en el laboratorio del 9-nov NO tenía los manejadores de BD y devolvía 500: el 500 era un artefacto de la imagen, no del código actual",
          old["GET /api/events"] == 500 and md5s["antigua"] != repo_md5 and md5s["actual"] == repo_md5, {"antigua": old, "md5": DATA["E"]["md5_main_py"], "manejadores": handlers})


# ================================================================== ETAPA F (estrategia síncrona) — PREPARADA, no ejecutada hasta autorización
class Writers:
    """Clientes ficticios que reservan sin parar (una clave de idempotencia por intención, reintentos con la misma clave) y anotan cada confirmación 200/201."""
    def __init__(self, tag: str, n: int = 8):
        self.users = [new_user(f"{tag}{i}") for i in range(n)]
        self.acked, self.att, self.stop, self.ths = [], [], threading.Event(), []

    def _w(self, u):
        while not self.stop.is_set():
            key = uuid.uuid4().hex
            for _ in range(60):
                t0 = time.time()
                try:
                    st, js, srv = u.reserve(EV_GENERAL, {"quantity": 1}, key, timeout=3)
                    self.att.append((t0, st, time.time()))
                    if st in (200, 201):
                        self.acked.append((time.time(), key, js["reservation_id"], st)); break
                    if st < 500: break
                except Exception:
                    self.att.append((t0, 0, time.time()))
                if self.stop.is_set(): break
                time.sleep(0.25)
            time.sleep(0.05)

    def start(self):
        for u in self.users:
            t = threading.Thread(target=self._w, args=(u,), daemon=True); t.start(); self.ths.append(t)

    def halt(self):
        self.stop.set(); [t.join(20) for t in self.ths]

    def lost_on(self, node: str):
        snapshot = list(self.acked)            # primero las confirmaciones conocidas y DESPUÉS la lectura de la BD (así una confirmación posterior no cuenta como perdida)
        ids = set(q1(node, f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
        return [a for a in snapshot if a[2] not in ids]


def _pct(v, p):
    v = sorted(v); return round(1000 * v[min(len(v) - 1, int(len(v) * p))], 2) if v else None



def f0_precheck():
    """F0 · ¿es la replicación realmente síncrona desde la perspectiva de la primaria? Se demuestra con una transacción real: con el seguidor retenido por un bloqueo de tabla, el COMMIT
    debe esperar (wait_event SyncRep), y al volver debe existir la fila en el seguidor con flush_lsn >= LSN de la transacción; el control asíncrono NO espera. Si falla, se detiene la etapa."""
    fresh_lab("F0", sync=True)
    r = {}
    r["synchronous_standby_names"] = q1("pg-aws", "SHOW synchronous_standby_names")
    r["synchronous_commit_de_la_primaria"] = q1("pg-aws", "SHOW synchronous_commit")
    r["fsync_primaria_y_seguidor"] = [q1("pg-aws", "SHOW fsync"), q1("pg-oci", "SHOW fsync")]
    r["suscripcion"] = q1("pg-oci", "SELECT subname||' synchronous_commit='||subsynccommit||' habilitada='||subenabled FROM pg_subscription")
    r["pg_stat_replication"] = q1("pg-aws", "SELECT application_name||' | '||state||' | '||sync_state||' | sent='||sent_lsn||' write='||write_lsn||' flush='||flush_lsn||' replay='||replay_lsn FROM pg_stat_replication WHERE application_name='sub_oci'")
    r["monitor_y_proteccion"] = L.prot_load().get("mode")
    script = ("BEGIN;\nINSERT INTO lab_bulk(payload) VALUES ('{p}') RETURNING id;\nSELECT 'LSN0='||pg_current_wal_insert_lsn();\nCOMMIT;\n")

    def trial(label):
        holder = subprocess.Popen(["docker", "exec", "-i", L.cname("pg-oci"), "psql", "-X", "-q", "-U", "postgres", "-d", "nexoeventos", "-c",
                                   "BEGIN; LOCK TABLE lab_bulk IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(4); COMMIT;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        box = {}
        def run_tx():
            t0 = time.time()
            rc, out, err = L.sql("pg-aws", script.format(p=label), stdin=script.format(p=label), timeout=30)
            box.update(rc=rc, out=out, dur=time.time() - t0)
            lsn_tx = next((l.split("=")[1] for l in out.splitlines() if l.startswith("LSN0=")), None)
            if lsn_tx:    # en el instante en que el COMMIT devolvió el control, ¿ya había confirmado el seguidor (flush) esa transacción?
                box["flush_ge_al_volver"] = q1("pg-aws", f"SELECT coalesce(flush_lsn >= '{lsn_tx}'::pg_lsn, false) FROM pg_stat_replication WHERE application_name='sub_oci'")
                box["flush_al_volver"] = q1("pg-aws", "SELECT flush_lsn FROM pg_stat_replication WHERE application_name='sub_oci'")
        th = threading.Thread(target=run_tx); th.start()
        time.sleep(2.0)
        mid = {"commit_sigue_esperando": th.is_alive(),
               "wait_event_en_pg_stat_activity": q1("pg-aws", "SELECT coalesce(string_agg(wait_event_type||'/'||wait_event, ','),'(ninguno)') FROM pg_stat_activity WHERE wait_event='SyncRep'"),
               "fila_en_el_seguidor_mientras_espera": q1("pg-oci", f"SELECT count(*) FROM lab_bulk WHERE payload='{label}'") if False else "no consultable (tabla bloqueada)"}
        th.join(30); holder.wait(30)
        t_ret = time.time()
        lsn0 = next((l.split("=")[1] for l in box.get("out", "").splitlines() if l.startswith("LSN0=")), None)
        row = q1("pg-oci", f"SELECT count(*) FROM lab_bulk WHERE payload='{label}'")
        flush = q1("pg-aws", "SELECT flush_lsn FROM pg_stat_replication WHERE application_name='sub_oci'")
        ok_lsn = q1("pg-aws", f"SELECT '{flush}'::pg_lsn >= '{lsn0}'::pg_lsn") if lsn0 and flush else None
        return {"duracion_del_commit_s": round(box.get("dur", 0), 2), "durante_la_espera": mid, "fila_en_el_seguidor_al_terminar_el_bloqueo": row, "LSN_de_la_transaccion": lsn0,
                "AL_VOLVER_EL_COMMIT_flush_lsn_del_seguidor": box.get("flush_al_volver"), "AL_VOLVER_EL_COMMIT_el_seguidor_ya_habia_confirmado_la_transaccion": box.get("flush_ge_al_volver"),
                "flush_lsn_confirmado_por_el_seguidor": flush, "flush_lsn_mayor_o_igual_que_el_LSN_de_la_transaccion": ok_lsn}

    r["COMMIT_SINCRONO_con_el_seguidor_retenido"] = trial("f0_sync")
    L.sync_names("pg-aws", "")
    r["CONTROL_ASINCRONO_con_el_seguidor_retenido"] = trial("f0_async")
    L.enable_sync("pg-aws")
    DATA["F0"] = r
    s, a = r["COMMIT_SINCRONO_con_el_seguidor_retenido"], r["CONTROL_ASINCRONO_con_el_seguidor_retenido"]
    ok = (r["synchronous_standby_names"] == "ANY 1 (sub_oci)" and r["synchronous_commit_de_la_primaria"] == "on" and "quorum" in r["pg_stat_replication"] and "synchronous_commit=on" in r["suscripcion"]
          and s["duracion_del_commit_s"] >= 2.5 and s["durante_la_espera"]["commit_sigue_esperando"] and "SyncRep" in s["durante_la_espera"]["wait_event_en_pg_stat_activity"]
          and s["fila_en_el_seguidor_al_terminar_el_bloqueo"] == "1" and s["AL_VOLVER_EL_COMMIT_el_seguidor_ya_habia_confirmado_la_transaccion"] == "t"
          and a["duracion_del_commit_s"] < 1.0 and a["AL_VOLVER_EL_COMMIT_el_seguidor_ya_habia_confirmado_la_transaccion"] == "f")
    check("F0 la replicación es síncrona desde la primaria: ajustes y pg_stat_replication en quorum; con el seguidor retenido el COMMIT espera (SyncRep) y al volver el seguidor YA había confirmado (flush_lsn >= LSN de la transacción); el control asíncrono NO espera y al volver el seguidor aún NO había confirmado",
          ok, r)
    if not ok:
        raise RuntimeError("F0 falló: la propiedad síncrona NO está demostrada; se detiene la etapa F (ver DATA['F0'])")


def stage_f():
    print("== F estrategia síncrona: protección de reservas confirmadas", flush=True)
    f0_precheck()
    # F1 mecanismo y coste
    with scenario("F1"):
        fresh_lab("F1", sync=True)
        st0 = L.standby_state("pg-aws")
        u = new_user("f1")
        def timeit(n=150):
            lat = []
            for _ in range(n):
                t = time.time(); u.reserve(EV_GENERAL, {"quantity": 1}, uuid.uuid4().hex, timeout=5); lat.append(time.time() - t)
            return {"p50_ms": _pct(lat, 0.5), "p95_ms": _pct(lat, 0.95)}
        lat_sync = timeit()
        L.sync_names("pg-aws", ""); lat_async = timeit(); L.enable_sync("pg-aws")
        L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci SET (synchronous_commit = 'off')"); time.sleep(1.5); lat_sub_off = timeit(30)
        L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci SET (synchronous_commit = 'on')"); time.sleep(1.5)
        DATA["F1"] = {"estado_del_seguidor_en_pg_stat_replication": st0, "latencia_de_confirmacion_sincrona": lat_sync, "latencia_asincrona": lat_async,
                      "sincrona_con_suscripcion_synchronous_commit_off_(configuracion_incorrecta)": lat_sub_off}
        check("F1 con la estrategia síncrona el seguidor figura como candidato síncrono (quorum) y la suscripción lleva synchronous_commit='on'; las latencias síncrona, asíncrona y con la opción en 'off' se registran como DATO (la diferencia con 'off' varió entre 10 y 224 ms de mediana según el patrón de carga: no se usa como criterio)",
              st0 in ("quorum", "sync") and "on" in q1("pg-oci", "SELECT subsynccommit FROM pg_subscription"), DATA["F1"])

    # F2 caída de la primaria con carga y seguidor sano: ninguna reserva CONFIRMADA debe perderse (3 repeticiones)
    with scenario("F2"):
        for i in range(1, 4):
            d = crash_under_load(f"F2-sync-{i}", sync=True)
            check(f"F2 {i}: con replicación síncrona y seguidor sano, 0 reservas confirmadas al cliente se pierden al caer la primaria (huérfanas inciertas: {d['huerfanas_NO_confirmadas_al_cliente_(INCIERTAS)']})",
                  d["RPO_transacciones_confirmadas_al_cliente_PERDIDAS"] == 0 and d["huerfanas_confirmadas_al_cliente_(perdidas)"] == 0,
                  {k: d[k] for k in ("RTO_escritura_s_desde_la_orden_de_caida", "RPO_transacciones_confirmadas_al_cliente_PERDIDAS", "huerfanas_NO_confirmadas_al_cliente_(INCIERTAS)", "errores_http_escritura", "escrituras_confirmadas_al_cliente")})

    # F2b el escenario de 3 s de retraso que con replicación asíncrona perdió 328 reservas confirmadas
    with scenario("F2b"):
        d = crash_under_load("F2b-retraso-de-3s", induce_s=3.0, sync=True)
        DATA["F2b_comparacion"] = {"asincrona_corrida_final_C": "328 reservas confirmadas perdidas (ventana 3,0 s)", "sincrona_ahora": d["RPO_transacciones_confirmadas_al_cliente_PERDIDAS"],
                                   "confirmaciones_durante_los_3_s": d["confirmaciones_al_cliente_durante_el_bloqueo_inducido"]}
        check("F2b el mismo escenario de 3 s (seguidor desconectado y caída de la primaria) con replicación síncrona: 0 reservas confirmadas ausentes (con asíncrona fueron 328)",
              d["RPO_transacciones_confirmadas_al_cliente_PERDIDAS"] == 0 and d["huerfanas_confirmadas_al_cliente_(perdidas)"] == 0, {k: d[k] for k in ("RPO_transacciones_confirmadas_al_cliente_PERDIDAS", "huerfanas_NO_confirmadas_al_cliente_(INCIERTAS)", "errores_http_escritura", "RTO_escritura_s_desde_la_orden_de_caida")})

    # F3 retraso REAL de aplicación en el seguidor (bloqueo de la tabla): los COMMIT esperan, nada se confirma sin copia
    with scenario("F3"):
        def lock_hook():
            t0 = time.time()
            subprocess.Popen(["docker", "exec", "-i", L.cname("pg-oci"), "psql", "-X", "-q", "-U", "postgres", "-d", "nexoeventos", "-c",
                              "BEGIN; LOCK TABLE reservations IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(4); COMMIT;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2.5)
            return (t0, t0 + 2.5)
        d = crash_under_load("F3-retraso-de-aplicacion", sync=True, hook=lock_hook)
        check("F3 con la aplicación retrasada en el seguidor (tabla bloqueada) y caída de la primaria a mitad: 0 reservas confirmadas perdidas, y no hubo confirmaciones al cliente mientras duraba el bloqueo",
              d["RPO_transacciones_confirmadas_al_cliente_PERDIDAS"] == 0 and d["confirmaciones_al_cliente_durante_el_bloqueo_inducido"] == 0,
              {k: d[k] for k in ("RPO_transacciones_confirmadas_al_cliente_PERDIDAS", "confirmaciones_al_cliente_durante_el_bloqueo_inducido", "huerfanas_NO_confirmadas_al_cliente_(INCIERTAS)", "RTO_escritura_s_desde_la_orden_de_caida")})

    # F4 seguidor NO disponible con política BLOQUEAR (por defecto): los COMMIT esperan; no se confirma nada sin copia
    with scenario("F4"):
        log = fresh_lab("F4", sync=True)
        w = Writers("f4"); w.start(); msleep(3)
        t_dis = time.time(); L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
        msleep(8)
        waiters = L.sql("pg-aws", "SELECT count(*) FROM pg_stat_activity WHERE wait_event='SyncRep'")[1]
        win_acks = [a for a in w.acked if a[0] > t_dis + 0.7]
        new_commit_acks = [a for a in win_acks if a[3] == 201]            # COMMIT nuevo confirmado con el seguidor caído: debe ser 0
        replay_acks = [a for a in win_acks if a[3] == 200]                # repeticiones de una clave cuya reserva ya estaba confirmada: válidas solo si ya existía en el seguidor
        ids_seguidor = set(q1("pg-oci", f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
        replays_con_copia = all(a[2] in ids_seguidor for a in replay_acks)
        acks_blocked = len(new_commit_acks)
        mode_blocked = L.prot_load().get("mode")
        promoted = ev_t(events(log), "promote_inicio", t_dis)
        L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci ENABLE"); t_en = time.time()
        msleep(5); w.halt()
        resumed = sum(1 for a in w.acked if a[0] > t_en + 1)
        DATA["F4"] = {"commits_esperando_en_SyncRep": waiters, "confirmaciones_201_(COMMIT_nuevo)_con_el_seguidor_caido": acks_blocked, "respuestas_200_repeticion_de_claves_ya_replicadas": len(replay_acks), "todas_las_repeticiones_ya_estaban_en_el_seguidor": replays_con_copia, "modo_de_proteccion": mode_blocked, "promociones": promoted is not None,
                      "confirmaciones_tras_volver_el_seguidor": resumed, "perdidas": len(w.lost_on("pg-aws"))}
        check("F4 con el seguidor no disponible y política BLOQUEAR: los COMMIT esperan (SyncRep), no se confirma nada al cliente, no se degrada ni se promueve (la primaria está viva) y al volver el seguidor se reanuda",
              int(waiters) > 0 and acks_blocked == 0 and replays_con_copia and mode_blocked == "protected" and promoted is None and resumed > 0 and DATA["F4"]["perdidas"] == 0, DATA["F4"])

    # F4b lo mismo con el seguidor DETENIDO (contenedor parado), no solo la suscripción deshabilitada
    with scenario("F4b"):
        log = fresh_lab("F4b", sync=True)
        w = Writers("f4b"); w.start(); msleep(3)
        t_st = time.time(); run("docker", "stop", "-t", "1", L.cname("pg-oci"))
        msleep(8)
        waiters_b = L.sql("pg-aws", "SELECT count(*) FROM pg_stat_activity WHERE wait_event='SyncRep'")[1]
        acks_b = sum(1 for a in w.acked if a[0] > t_st + 0.7)
        promoted_b = ev_t(events(log), "promote_inicio", t_st)
        run("docker", "start", L.cname("pg-oci")); t_up = time.time()
        wait_until(lambda: L.sql("pg-oci", "SELECT 1")[0] == 0, 40)
        wait_until(lambda: L.standby_state("pg-aws") in ("quorum", "sync"), 40)
        msleep(5); w.halt()
        resumed_b = sum(1 for a in w.acked if a[0] > t_up + 5)
        DATA["F4b"] = {"commits_esperando_en_SyncRep": waiters_b, "confirmaciones_al_cliente_con_el_seguidor_detenido": acks_b, "promociones": promoted_b is not None,
                       "confirmaciones_tras_reiniciar_el_seguidor": resumed_b, "perdidas": len(w.lost_on("pg-aws")), "modo": L.prot_load().get("mode")}
        check("F4b con el seguidor detenido: los COMMIT esperan, 0 confirmaciones sin copia, no se promueve (la primaria vive), y al reiniciar el seguidor se reanuda sin pérdidas",
              int(waiters_b) > 0 and acks_b == 0 and promoted_b is None and resumed_b > 0 and DATA["F4b"]["perdidas"] == 0, DATA["F4b"])

    # F5 seguidor no disponible con política DEGRADAR + caída de la primaria: la compuerta impide promover (y la promoción insegura explícita pierde justo lo confirmado sin protección)
    with scenario("F5"):
        log = fresh_lab("F5", sync=True, env={"LAB_DEGRADE_AFTER_S": "4"})
        w = Writers("f5"); w.start(); msleep(3)
        t_dis = time.time(); L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
        t_deg = wait_until(lambda: ev_t(events(log), "proteccion", t_dis, modo="degraded") is not None, 30)
        ev5a = events(log)
        t_intent = ev_t(ev5a, "proteccion", t_dis, modo="degrading")
        t_off = ev_t(ev5a, "sync_deshabilitada", t_dis)
        t_rec = ev_t(ev5a, "proteccion", t_dis, modo="degraded")
        order_ok = bool(t_intent and t_off and t_rec and t_intent < t_off <= t_rec)
        msleep(4)
        t_kill = kill_node("pg-aws")
        msleep(10)
        ev5 = events(log)
        blocked = ev_t(ev5, "promocion_bloqueada", t_kill) is not None
        no_lease = ev_t(ev5, "lease_otorgado", t_kill) is None
        at_risk = [a for a in w.acked if a[0] > (t_intent or time.time())]    # frontera: desde que el estado dejó de ser 'protected' (intención registrada)
        log2 = start_monitor("F5-promocion-insegura", env={"LAB_UNSAFE_PROMOTE": "1", "LAB_DEGRADE_AFTER_S": "4"})
        t_unsafe = time.time()
        t_prom = wait_until(lambda: ev_t(events(log2), "lease_otorgado", t_unsafe) is not None, 60)
        msleep(3); w.halt()
        lost = w.lost_on("pg-oci")
        DATA["F5"] = {"orden_intencion_desactivacion_registro": {"degrading": t_intent, "sync_deshabilitada": t_off, "degraded": t_rec, "orden_correcto": order_ok},
                      "degradado_tras_s": None if t_deg is None else round(t_deg, 1), "confirmadas_desde_que_el_estado_dejo_de_ser_protected": len(at_risk), "promocion_automatica_bloqueada": blocked and no_lease,
                      "promocion_insegura_ordenada_ok": t_prom is not None, "confirmadas_perdidas_tras_la_promocion_insegura": len(lost),
                      "primera_perdida_menos_registro_de_la_intencion_s": None if not lost else round(min(a[0] for a in lost) - (t_intent or 0), 3),
"todas_las_perdidas_son_posteriores_al_registro_de_la_intencion_degrading": all(a[0] > (t_intent or 0) for a in lost)}
        check("F5 la intención 'degrading' se registra ANTES de desactivar el síncrono y 'degraded' después; con la primaria caída la promoción automática queda bloqueada (con sus razones); la promoción insegura explícita pierde solo reservas confirmadas DESPUÉS de que el estado dejó de ser 'protected' (límite de la garantía, no un defecto)",
              order_ok and t_deg is not None and DATA["F5"]["promocion_automatica_bloqueada"] and t_prom is not None and len(lost) > 0 and DATA["F5"]["todas_las_perdidas_son_posteriores_al_registro_de_la_intencion_degrading"] and len(lost) <= len(at_risk), DATA["F5"])

    # F5c coordinación: degradar y promover concurrentes sobre el mismo estado (CAS en el witness): exactamente una gana
    with scenario("F5c"):
        fresh_lab("F5c", sync=True); stop_monitor()
        wins = {"degradar": 0, "promover": 0, "ninguna": 0, "ambas": 0}
        for i in range(30):
            stt = L.witness_state(); pr = stt["prot"]
            if pr["mode"] != "protected":
                assert L.prot_cas("protected", primario="pg-aws", motivo="F5c: restablecer")
                stt = L.witness_state(); pr = stt["prot"]
            res2, bar = {}, threading.Barrier(2)
            def cas(label, mode):
                bar.wait()
                res2[label] = L.w_req("POST", "/prot", {"expect_seq": pr["seq"], "mode": mode, "primario": "pg-aws", "epoch": stt["epoch"]})[0]
            ts = [threading.Thread(target=cas, args=("degradar", "degrading")), threading.Thread(target=cas, args=("promover", "promoting"))]
            [t.start() for t in ts]; [t.join() for t in ts]
            ok_n = sum(1 for v in res2.values() if v == 200)
            if ok_n == 1:
                wins["degradar" if res2["degradar"] == 200 else "promover"] += 1
            elif ok_n == 0:
                wins["ninguna"] += 1
            else:
                wins["ambas"] += 1
            # restablecer para el siguiente intento: del estado ganador a 'protected'
            st3 = L.witness_state()
            L.w_req("POST", "/prot", {"expect_seq": st3["prot"]["seq"], "mode": "protected", "primario": "pg-aws", "epoch": st3["epoch"]})
        DATA["F5c"] = wins
        check("F5c en 30 carreras simultáneas entre degradar y promover sobre el mismo estado, exactamente UNA transición gana siempre (nunca ambas)", wins["ambas"] == 0 and wins["ninguna"] == 0 and sum(wins.values()) == 30, wins)

    # F5x fallos provocados en los puntos críticos de la degradación, con carga: el controlador cae (exit) o cae la primaria (kill_primary) justo después de la intención, de desactivar el síncrono y del registro
    for point in ("after_intent", "after_disable", "after_record"):
        for action in ("exit", "kill_primary"):
            tag = f"F5x-{point}-{action}"
            with scenario(tag):
                FLAGS["mon_death_ok"] = action == "exit"
                log = fresh_lab(tag, sync=True, env={"LAB_DEGRADE_AFTER_S": "3", "LAB_FAULT": f"{point}:{action}"})
                w = Writers("fx"); w.start(); msleep(2)
                t_dis = time.time(); L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
                t_fault = wait_until(lambda: ev_t(events(log), "fallo_inyectado", t_dis) is not None, 30)
                msleep(2)
                if action == "exit":                         # el controlador murió en ese punto: se le reinicia (sin fallo) y luego cae la primaria
                    MON_ALIVE = MON.poll() is None if MON else False
                    FLAGS["mon_death_ok"] = False
                    log = start_monitor(tag + "-reinicio", env={"LAB_DEGRADE_AFTER_S": "3", "LAB_FAULT": ""})
                    msleep(4)
                else:
                    MON_ALIVE = MON.poll() is None if MON else False
                t_kill = kill_node("pg-aws") if action == "exit" else time.time()
                msleep(10)
                ev_all = events(log) + (events(OUT / f"eventos-{tag}.jsonl") if action == "exit" else [])
                blocked = any(e["ev"] == "promocion_bloqueada" and e["t"] >= t_kill for e in ev_all)
                lease = any(e["ev"] == "lease_otorgado" and e["t"] >= t_kill for e in ev_all)
                promo = any(e["ev"] in ("promote_inicio", "promocion_insegura_ordenada") and e["t"] >= t_kill for e in ev_all)
                acks_after = sum(1 for a in w.acked if a[0] > t_kill + 2)
                modes = [e.get("modo") for e in ev_all if e["ev"] == "proteccion" and e["t"] >= t_dis]
                w.halt()
                FLAGS["mon_death_ok"] = False
                DATA.setdefault("F5x", {})[tag] = {"fallo_inyectado": t_fault is not None, "controlador_vivo_tras_el_fallo": MON_ALIVE, "transiciones_de_estado": modes, "promocion_bloqueada": blocked,
                                                    "lease_a_pg-oci": lease, "promocion_iniciada": promo, "confirmaciones_al_cliente_tras_la_caida": acks_after}
                check(f"F5x {point}/{action}: con la primaria caída tras el fallo en ese punto NO se promueve automáticamente (compuerta bloqueada, sin lease ni promoción) y no se confirma nada más",
                      t_fault is not None and blocked and not lease and not promo and acks_after == 0, DATA["F5x"][tag])

    # F6 conmutación -> UNPROTECTED -> reconstrucción -> PROTECTED -> retorno planificado sin pérdida; la antigua primaria no vuelve sola como escritora y su síncrono obsoleto se limpia
    with scenario("F6"):
        log = fresh_lab("F6", sync=True)
        w = Writers("f6"); w.start(); msleep(3)
        t_kill = kill_node("pg-aws")
        t_l = wait_until(lambda: ev_t(events(log), "lease_otorgado", t_kill) is not None, 60)
        msleep(3)
        prot_after = L.prot_load()
        names_after = L.sql("pg-oci", "SHOW synchronous_standby_names")[1]
        acks_unprot = sum(1 for a in w.acked if a[0] > t_kill + 6)
        lost_failover = w.lost_on("pg-oci")
        n_prom_before = sum(1 for e in events(log) if e["ev"] == "promote_inicio")
        run("docker", "start", L.cname("pg-aws"))                     # la antigua primaria vuelve sola (sin procedimiento)
        wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 60)
        stale_names = L.sql("pg-aws", "SHOW synchronous_standby_names")[1]
        old_write = [L.app_connect("pg-aws", write=True)[0], L.app_connect("pg-aws", write=True, override=True)[0]]
        writer_after_return = L.witness_state()["writer"]
        t_rs = time.time()
        L.reseed("pg-aws", "pg-oci")
        reseed_s = round(time.time() - t_rs, 1)
        names_cleaned = L.sql("pg-aws", "SHOW synchronous_standby_names")[1]
        wait_until(lambda: L.prot_load().get("mode") == "protected", 40)       # la reprotección (barrera de LSN) puede tardar unos segundos tras la reconstrucción, con carga activa
        prot_reseed = L.prot_load(); st_reseed = L.standby_state("pg-oci")
        msleep(3); w.halt()
        w2 = Writers("f6b"); w2.start(); msleep(2)
        with L.paused():
            ok_back = L.promote("pg-aws", planned=True)
        msleep(4); w2.halt()
        ids_back = set(q1("pg-aws", f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
        lost_back = [a for a in w.acked + w2.acked if a[2] not in ids_back]
        n_prom_after = sum(1 for e in events(log) if e["ev"] == "promote_inicio")
        DATA["F6"] = {"modo_tras_la_conmutacion": prot_after.get("mode"), "synchronous_standby_names_en_la_nueva_primaria": names_after, "confirmaciones_sin_proteccion": acks_unprot,
                      "perdidas_en_la_conmutacion": len(lost_failover),
                      "antigua_primaria_reiniciada_sola": {"synchronous_standby_names_obsoleto": stale_names, "escrituras_directas_aceptadas": old_write, "escritor_en_el_witness": writer_after_return,
                                                            "promociones_automaticas_hacia_ella": n_prom_after - n_prom_before},
                      "reconstruccion": {"duracion_s": reseed_s, "synchronous_standby_names_tras_limpiar": names_cleaned, "modo_de_proteccion": prot_reseed.get("mode"), "estado_del_seguidor": st_reseed},
                      "retorno_planificado_ok": ok_back, "perdidas_en_el_retorno": len(lost_back)}
        check("F6 conmutación: queda UNPROTECTED sin síncrono heredado; la antigua primaria que reaparece sola conserva un síncrono OBSOLETO pero NO escribe (arranca cerrada) y el escritor sigue siendo pg-oci; la reconstrucción limpia el síncrono (verificado), no se bloquea y devuelve PROTECTED; el retorno planificado no pierde reservas confirmadas",
              t_l is not None and prot_after.get("mode") == "unprotected" and names_after == "" and stale_names != "" and not any(old_write) and writer_after_return == "pg-oci" and n_prom_after == n_prom_before
              and names_cleaned == "" and reseed_s < 60 and prot_reseed.get("mode") == "protected" and st_reseed in ("quorum", "sync") and ok_back and not lost_back and not lost_failover, DATA["F6"])

    # F7 caída simultánea de AMBOS nodos y reinicio: durabilidad local de lo confirmado (no es una garantía de disponibilidad)
    with scenario("F7"):
        log = fresh_lab("F7", sync=True)
        w = Writers("f7"); w.start(); msleep(4)
        stop_monitor()
        ts = [threading.Thread(target=lambda n=n: run("docker", "kill", L.cname(n))) for n in L.NODES]
        [t.start() for t in ts]; [t.join() for t in ts]
        w.halt()
        run("docker", "start", L.cname("pg-aws"))
        wait_until(lambda: L.sql("pg-aws", "SELECT 1")[0] == 0, 60)
        lost7 = w.lost_on("pg-aws")
        run("docker", "start", L.cname("pg-oci"))
        DATA["F7"] = {"confirmadas": len(w.acked), "perdidas_tras_reiniciar_la_primaria": len(lost7)}
        check("F7 caída simultánea de ambos nodos: tras reiniciar la primaria, 0 reservas confirmadas ausentes (durabilidad local con fsync); NO implica disponibilidad ni cubre pérdida de disco", len(lost7) == 0 and len(w.acked) > 0, DATA["F7"])

    # F8 incertidumbre sobre la durabilidad (el controlador pierde su registro de protección) y cae la primaria: NO se promueve
    with scenario("F8"):
        log = fresh_lab("F8", sync=True)
        w = Writers("f8"); w.start(); msleep(3)
        L.PAUSE.parent.mkdir(parents=True, exist_ok=True); L.PAUSE.write_text("F8"); time.sleep(1.0)     # el monitor no actúa: así la incertidumbre se mantiene hasta la caída
        assert L.prot_cas("unknown", expect=("protected",), primario="pg-aws", motivo="F8: el estado de protección se vuelve incierto"), "no se pudo provocar la incertidumbre"
        t_kill = kill_node("pg-aws")
        time.sleep(0.5); L.PAUSE.unlink(missing_ok=True)          # se reanuda el monitor con la primaria ya caída y el estado en 'unknown'
        msleep(10)
        ev8 = events(log)
        blocked8 = ev_t(ev8, "promocion_bloqueada", t_kill) is not None
        lease8 = ev_t(ev8, "lease_otorgado", t_kill)
        acks_after = sum(1 for a in w.acked if a[0] > t_kill + 1.5)
        w.halt()
        DATA["F8"] = {"promocion_bloqueada": blocked8, "lease_otorgado": lease8 is not None, "confirmaciones_al_cliente_tras_la_caida": acks_after,
                      "motivo": next((e.get("motivo") for e in ev8 if e["ev"] == "promocion_bloqueada"), None)}
        check("F8 con incertidumbre sobre si lo confirmado tiene copia (registro de protección ausente) y la primaria caída: no se promueve, se registra el motivo y no se confirma nada más (falla segura)",
              blocked8 and lease8 is None and acks_after == 0, DATA["F8"])

    # F9 caída después de confirmar y antes de responder, con replicación síncrona
    with scenario("F9"):
        d9 = after_commit("F9a-sync-tras-confirmar", induce=False, sync=True)
        check("F9a con replicación síncrona, la respuesta HTTP solo existe si la reserva ya está en el seguidor: tras la caída, el reintento con la misma clave devuelve la MISMA reserva (200) y no hay duplicado",
              d9["replicada_antes_de_caer"] and d9["estado_final"] == 200 and d9["misma_reserva"] and d9["reservas_con_esa_clave_en_la_nueva_primaria"] == "1", d9)
        log = fresh_lab("F9b", sync=True)
        L.dc("up", "-d", "cut-proxy")
        wait_until(lambda: fl.req(("127.0.0.1", 18091), "GET", "/held", timeout=2)[0] == 200, 30)
        ub = new_user("cb", addr=("127.0.0.1", 18090))
        Kb = uuid.uuid4().hex
        sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE")
        outb = {}
        def send_b():
            try:
                outb["r"] = ub._do("POST", f"/api/events/{EV_GENERAL}/reservations", {"quantity": 1}, {"Idempotency-Key": Kb}, ("127.0.0.1", 18090), timeout=40)
            except Exception as e:
                outb["exc"] = type(e).__name__
        thb = threading.Thread(target=send_b); thb.start()
        waiting = wait_until(lambda: int(L.sql("pg-aws", "SELECT count(*) FROM pg_stat_activity WHERE wait_event='SyncRep'")[1]) >= 1, 20)
        t_kill = kill_node("pg-aws")
        thb.join(45)
        ub.addr = ("127.0.0.1", 18080)
        finalb, triesb = None, []
        for _ in range(80):
            try:
                stb, jsb, _s = ub.reserve(EV_GENERAL, {"quantity": 1}, Kb, timeout=3)
                triesb.append(stb)
                if stb < 500:
                    finalb = (stb, jsb); break
            except Exception as e:
                triesb.append(type(e).__name__)
            time.sleep(0.25)
        wait_until(lambda: ev_t(events(log), "lease_otorgado", t_kill) is not None, 60)
        sumb = L.orphans("pg-aws", "pg-oci", str(OUT / "huerfanas-F9b"))
        DATA["F9b"] = {"commit_esperando_al_seguidor_cuando_cayo_la_primaria": waiting is not None, "cliente_recibio_respuesta_original": "r" in outb and outb["r"][0] < 500,
                       "reintento_con_la_misma_clave": None if not finalb else finalb[0], "reintento_replayed": None if not finalb else finalb[1].get("replayed"),
                       "huerfanas_en_la_antigua_primaria": sumb["tablas_con_huerfanas"], "duplicados_logicos": sumb["duplicados_logicos_por_idempotency_key"], "Idempotency_Key": Kb}
        check("F9b caída con el COMMIT esperando al seguidor: el cliente NO recibió confirmación; el reintento crea la reserva en la nueva primaria (201); la fila de la antigua es una transacción INCIERTA (huérfana, duplicado lógico detectado), nunca una confirmación perdida",
              waiting is not None and not DATA["F9b"]["cliente_recibio_respuesta_original"] and finalb and finalb[0] == 201 and any(x["idempotency_key"] == Kb for x in sumb["duplicados_logicos_por_idempotency_key"]), DATA["F9b"])



def stage_f4r():
    print("== F4R repetición del escenario 'seguidor no disponible' con el invariante exacto", flush=True)
    DATA["F4R"] = {}
    for i in range(1, 6):
        tag = f"F4R-{i}"
        with scenario(tag):
            log = fresh_lab(tag, sync=True)
            w = Writers("f4r"); w.start(); msleep(3)
            L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci DISABLE"); t_off = time.time()      # el comando ya volvió: el apply worker está parado
            msleep(8)
            win = [a for a in w.acked if a[0] > t_off]
            ids_seg = set(q1("pg-oci", f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
            absent = [a for a in win if a[2] not in ids_seg]
            waiters = L.sql("pg-aws", "SELECT count(*) FROM pg_stat_activity WHERE wait_event='SyncRep'")[1]
            L.sql("pg-oci", "ALTER SUBSCRIPTION sub_oci ENABLE")
            msleep(4); w.halt()
            DATA["F4R"][tag] = {"commits_esperando_en_SyncRep": waiters, "confirmaciones_al_cliente_tras_el_DISABLE": len(win),
                                "de_ellas_ausentes_en_el_seguidor_(confirmadas_sin_copia)": len(absent),
                                "instante_y_estado_de_cada_una_(s_tras_el_DISABLE, http)": [(round(a[0] - t_off, 2), a[3]) for a in win][:40],
                                "ausentes_detalle": [(round(a[0] - t_off, 2), a[3], a[2]) for a in absent][:20], "modo": L.prot_load().get("mode")}
            check(f"F4R {i}: tras deshabilitar el seguidor ninguna reserva confirmada al cliente carece de copia en el seguidor (hubo {len(win)} confirmaciones en la ventana; ausentes: {len(absent)})",
                  len(absent) == 0 and int(waiters) > 0, DATA["F4R"][tag])


# ================================================================== main
def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    OUT = Path(a.out); OUT.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, a.only.split(",")))
    stages = {"A": stage_a, "B": stage_b, "C": stage_c, "D": stage_d, "E": stage_e, "F0": f0_precheck, "F": stage_f, "F4R": stage_f4r}
    try:
        for k, fn in stages.items():
            if not only or k in only:
                fn()
    finally:
        stop_monitor()
        (OUT / f"resultados-{'-'.join(sorted(only)) or 'todo'}.json").write_text(json.dumps({"pruebas": RES, "datos": DATA}, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(f"\n{sum(r['ok'] for r in RES)} de {len(RES)} comprobaciones OK")
    sys.exit(0 if all(r["ok"] for r in RES) else 1)


if __name__ == "__main__":
    main()
