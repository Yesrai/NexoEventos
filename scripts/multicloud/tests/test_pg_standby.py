"""Standby REAL sobre PostgreSQL 18 DESECHABLE + API FastAPI real con WRITE_GATE_MODE=enforce + vallado en la base (pg_fence). Sin nubes. Dos bases del mismo clúster hacen de «AWS» (primario) y «OCI»
(standby); el almacén del lease es en memoria (la semántica If-Match ya se prueba aparte). TTL real corto (3 s, margen 0,6 s): hay esperas reales porque la autoridad de la base caduca con SU reloj.
Cubre: standby solo lectura, promoción válida, vencimiento/pérdida, partición con primario activo, dos candidatos, transacción en curso, reinicio, fallo parcial, retorno de AWS, privilegios."""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "scripts/multicloud/failover"))
PGBIN = next((Path(p) for p in ("/opt/homebrew/opt/postgresql@18/bin", "/usr/local/opt/postgresql@18/bin") if (Path(p) / "postgres").exists()), None)
pytestmark = pytest.mark.skipif(PGBIN is None or not (ROOT / "backend/.venv/bin/alembic").exists(), reason="requiere PostgreSQL 18 local y backend/.venv")
os.environ.setdefault("TICKET_ENCRYPTION_KEY", "xo6GkYk8m0vZ8k7cV0t8pG3m1o2cX9Yh7w4ZJb0qLxs=")
os.environ.setdefault("SECURITY_HASH_KEY", "test-hash-key-" + "0" * 40)

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.failover.gate import WriteGate  # noqa: E402
from app.failover.lease import LeaseClient, LeaseConfig, init_lease  # noqa: E402
from app.failover.pg_fence import FenceAttestation, PgFence, install_sql  # noqa: E402
from app.failover.store import InMemoryStore, StoreUnavailable  # noqa: E402
from app.main import create_app  # noqa: E402
from fenced_db import FencedOut  # noqa: E402
from pg_standby import PgStandby, PsycopgExecutor  # noqa: E402

CFG = LeaseConfig(ttl_s=3.0, margin_s=0.6)
_STATE_DIR = tempfile.mkdtemp()


def state_for(store, holder):
    """Archivo de estado del titular (ETag de su última escritura confirmada): permite adoptar su propio lease tras un reinicio sin fiarse del contenido del almacén."""
    return os.path.join(_STATE_DIR, f"{id(store)}-{holder}.state")
ORIGIN = {"Origin": "http://testserver"}
PW = "Contrasena-segura-123!"


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    t = Path(tmp_path_factory.mktemp("pgs", numbered=True)); os.chmod(t, 0o700)
    sock = Path("/tmp") / f"pgs{os.getpid()}"; sock.mkdir(mode=0o700, exist_ok=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "PGHOST": str(sock), "PGPORT": str(port), "PGUSER": "postgres", "LC_ALL": "en_US.UTF-8"}
    run([str(PGBIN / "initdb"), "-D", str(t / "pg"), "-U", "postgres", "-E", "UTF8", "--locale=C", "-A", "trust"], env=env, check=True)
    assert run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-o", f"-c listen_addresses= -c unix_socket_directories={sock} -c port={port} -c fsync=off -c max_connections=200", "-l", str(t / "log"), "-w", "start"], env=env).returncode == 0
    psql = lambda db, sql, **k: run([str(PGBIN / "psql"), "-q", "-v", "ON_ERROR_STOP=1", "-d", db], input=sql, env=env, **k)
    assert psql("postgres", "CREATE ROLE nexoeventos_owner NOLOGIN; CREATE ROLE nexoeventos_app LOGIN; CREATE ROLE nexo_fence_keeper LOGIN;").returncode == 0
    ctx = dict(sock=str(sock), port=port, env=env, psql=psql, tmp=t)

    def url(db, user="nexoeventos_app"):
        return f"postgresql+psycopg://{user}@/{db}?host={sock}&port={port}"
    ctx["url"] = url

    def mkdb(db):
        assert run([str(PGBIN / "psql"), "-q", "-d", "postgres", "-c", f"CREATE DATABASE {db} OWNER nexoeventos_owner"], env=env).returncode == 0
        assert psql("postgres", f"REVOKE ALL ON DATABASE {db} FROM PUBLIC; GRANT CONNECT ON DATABASE {db} TO nexoeventos_app, nexo_fence_keeper;").returncode == 0
    mkdb("nexo_aws")
    assert run([str(ROOT / "backend/.venv/bin/alembic"), "upgrade", "head"], cwd=ROOT / "backend", env={**os.environ, "MIGRATION_DATABASE_URL": url("nexo_aws", "postgres")}).returncode == 0
    assert run([str(ROOT / "backend/.venv/bin/python"), str(ROOT / "scripts/seed-demo-catalog.py"), "--database-url", url("nexo_aws", "postgres")]).returncode == 0
    # un cliente con sesión REAL creado en «AWS» (sin vallado todavía) y luego copiado a «OCI» como lo haría la recuperación (dump → restore)
    _saved_env = {k: os.environ.get(k) for k in ("DATABASE_URL", "WRITE_GATE_MODE", "WRITE_GATE_DB_FENCE")}   # se restauran al terminar: sin esto, otras pruebas del mismo proceso apuntan a este clúster ya borrado
    os.environ["DATABASE_URL"] = url("nexo_aws")
    for k in ("WRITE_GATE_MODE", "WRITE_GATE_DB_FENCE"): os.environ.pop(k, None)
    c = TestClient(create_app(url("nexo_aws")))
    assert c.post("/api/auth/register", headers=ORIGIN, json={"email": "cliente@example.com", "display_name": "Cliente", "password": PW}).status_code == 201
    assert c.post("/api/auth/login", headers=ORIGIN, json={"email": "cliente@example.com", "password": PW}).status_code == 200
    ctx["cookies"] = dict(c.cookies)
    ev = None
    for e in run([str(PGBIN / "psql"), "-d", "nexo_aws", "-At", "-c", "select id from events where status='published' and capacity-reserved_count>50 and ticket_mode='general' and sales_start_at is null and not queue_enabled order by id limit 5"], env=env).stdout.split():
        r = c.post(f"/api/events/{e}/reservations", headers={**ORIGIN, "X-CSRF-Token": c.cookies.get("nexoeventos_csrf"), "Idempotency-Key": "prueba-previa-" + e}, json={"quantity": 1})
        if r.status_code in (200, 201): ev = int(e); break
    assert ev, "no se encontró un evento reservable en la base de prueba"
    ctx["event"] = ev
    dump = subprocess.run([str(PGBIN / "pg_dump"), "-Fc", "--no-owner", "--no-acl", "-d", "nexo_aws"], capture_output=True, env=env, check=True).stdout
    mkdb("nexo_oci")
    assert subprocess.run([str(PGBIN / "pg_restore"), "-d", "nexo_oci", "--no-owner", "--no-acl", "--exit-on-error"], input=dump, capture_output=True, env=env).returncode == 0
    for db in ("nexo_aws", "nexo_oci"):
        assert psql(db, "GRANT USAGE ON SCHEMA public TO nexoeventos_app; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexoeventos_app; GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO nexoeventos_app;").returncode == 0
        r = psql(db, install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper")); assert r.returncode == 0, r.stderr
    yield ctx
    for k, v in _saved_env.items():
        if v is None: os.environ.pop(k, None)
        else: os.environ[k] = v
    run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=env)
    shutil.rmtree(sock, ignore_errors=True)


def new_store():
    s = InMemoryStore(); s.verified = True; init_lease(s); return s


def keeper_exec(pg, db): return PsycopgExecutor(host=pg["sock"], port=pg["port"], dbname=db, user="nexo_fence_keeper")
def app_exec(pg, db): return PsycopgExecutor(host=pg["sock"], port=pg["port"], dbname=db, user="nexoeventos_app")
def admin_exec(pg, db): return PsycopgExecutor(host=pg["sock"], port=pg["port"], dbname=db, user="postgres")


def make_gate(pg, db, store, holder, role, pf, store_wrap=None):
    lease = LeaseClient(store_wrap or store, CFG, holder_id=holder, state_path=state_for(store, holder))
    return WriteGate(lease, role=role, promote_file=str(pf), db_fence=PgFence(keeper_exec(pg, db), app_role="nexoeventos_app"))


def make_app(pg, db, gate):
    os.environ["DATABASE_URL"] = pg["url"](db)
    app = create_app(pg["url"](db), write_gate=gate)
    c = TestClient(app)
    for k, v in pg["cookies"].items(): c.cookies.set(k, v)
    return app, c


def reserve(pg, c, key=None):
    return c.post(f"/api/events/{pg['event']}/reservations", headers={**ORIGIN, "X-CSRF-Token": c.cookies.get("nexoeventos_csrf"), "Idempotency-Key": key or "k-" + uuid.uuid4().hex}, json={"quantity": 1})


def count(pg, db, table="reservations"): return int(admin_exec(pg, db)(f"select count(*) from {table}")[0][0])


@contextmanager
def keeping(*steps, every=0.4):
    """Hilo guardián que ejecuta los pasos periódicamente (lo que hace WriteGate.start())."""
    stop = threading.Event()
    def loop():
        while not stop.wait(every):
            for s in steps:
                try: s()
                except Exception: pass
    th = threading.Thread(target=loop, daemon=True); th.start()
    try: yield
    finally: stop.set(); th.join(timeout=3)


def reset_fence(pg, db):
    """Entre pruebas: la base vuelve a «sin autoridad» (como un standby recién restaurado) y se limpian filas de prueba."""
    k = keeper_exec(pg, db)
    k("SELECT nexo_fence.reset_after_restore()")
    admin_exec(pg, db)("UPDATE nexo_fence.writer_fence SET epoch = 0, holder = NULL, valid_until = '-infinity' WHERE id = 1")      # (solo pruebas: cada una usa un almacén de lease nuevo, con épocas desde 1)


# ───────────────────────────── 1. el standby es de solo lectura hasta que se promueve ─────────────────────────────
def test_standby_bloquea_reservas_antes_de_promover_y_ninguna_via_se_salta_la_compuerta(pg, tmp_path):
    reset_fence(pg, "nexo_oci"); before = count(pg, "nexo_oci")
    gate = make_gate(pg, "nexo_oci", new_store(), "oci-1", "standby", tmp_path / "promote"); app, c = make_app(pg, "nexo_oci", gate)
    gate.keeper_step()                                                      # el standby NO toma el lease ni autoridad en la base
    assert c.get("/api/me/reservations").status_code == 200                 # lecturas sí
    r = reserve(pg, c); assert r.status_code == 503 and r.json()["code"] == "write_gate_closed"       # capa HTTP
    assert count(pg, "nexo_oci") == before
    # vías que intentan saltarse la compuerta de la aplicación: el SERVIDOR las rechaza
    e = app_exec(pg, "nexo_oci")
    with pytest.raises(psycopg.errors.Error) as ex: e.tx_insert_probe(1, "directo")                          # escritura directa con el rol de la aplicación y época declarada
    assert "NEXO_FENCE" in str(ex.value)
    for sql, frag in (("SELECT nexo_fence.grant_authority(99,'x',60)", "permission denied"), ("SELECT nexo_fence.revoke_authority(99)", "permission denied"),
                      ("UPDATE nexo_fence.writer_fence SET valid_until='infinity'", "permission denied"), ("ALTER TABLE reservations DISABLE TRIGGER ALL", "must be owner"),
                      ("DROP TRIGGER nexo_fence_commit ON reservations", "must be owner"), ("SET session_replication_role = replica", "permission denied"),
                      ("TRUNCATE reservations", "permission denied"), ("CREATE TABLE zz(i int)", "permission denied")):
        with pytest.raises(psycopg.errors.Error) as ex: e(sql)
        assert frag in str(ex.value), (sql, str(ex.value))
    adm = admin_exec(pg, "nexo_oci")          # ni siquiera un SUPERUSUARIO escribe sin autoridad en la base (solo desactivando triggers o session_replication_role, que es administración deliberada)
    for sql in ("TRUNCATE nexo_fence.write_probe", "UPDATE reservations SET quantity = quantity"):
        with pytest.raises(psycopg.errors.Error) as ex: adm(sql)
        assert "NEXO_FENCE" in str(ex.value), sql
    with psycopg.connect(host=pg["sock"], port=pg["port"], dbname="nexo_oci", user="nexoeventos_app") as conn:       # ni siquiera «forzando» la época vigente de la base
        cur = conn.cursor(); cur.execute("SELECT set_config('nexo.writer_epoch', (SELECT epoch::text FROM nexo_fence.fence_status()), true)")
        cur.execute("INSERT INTO nexo_fence.write_probe (epoch, payload) VALUES (0, 'forzada')")
        with pytest.raises(psycopg.errors.Error): conn.commit()
    att = PgFence(keeper_exec(pg, "nexo_oci")).attest(); assert att["ok"] is True and att["uncovered"] == [] and att["app_role_can_change_fence"] is False


# ───────────────────────────── 2. promoción válida y 3. pérdida / vencimiento ─────────────────────────────
def promote(pg, db, store, tmp_path, holder="oci-1"):
    """Como el orquestador: toma el lease, PgStandby.enable; luego la API (mismo holder) adopta el lease y renueva."""
    lease = LeaseClient(store, CFG, holder_id=holder, state_path=state_for(store, holder)); st = PgStandby(lease, PgFence(keeper_exec(pg, db)), tmp_path / "promote", app_exec(pg, db), "oci")
    deadline = time.monotonic() + 15
    while not lease.acquire().ok:
        assert time.monotonic() < deadline, "no se obtuvo el lease"; time.sleep(0.4)
    st.enable(lease.epoch)
    return lease, st


def test_promocion_valida_habilita_escrituras_y_su_perdida_o_vencimiento_las_bloquea(pg, tmp_path):
    reset_fence(pg, "nexo_oci"); store = new_store(); pf = tmp_path / "promote"
    lease, st = promote(pg, "nexo_oci", store, tmp_path)
    assert st.writes_permitted() and st.status()["db_authority_valid"] and st.status()["fence_epoch"] == lease.epoch
    gate = make_gate(pg, "nexo_oci", store, "oci-1", "standby", pf); app, c = make_app(pg, "nexo_oci", gate)
    before = count(pg, "nexo_oci")
    gate.keeper_step()                                                       # la API adopta el lease (mismo holder) y renueva la autoridad de la base
    assert gate.lease.is_valid() and gate.lease.epoch == lease.epoch
    with keeping(gate.keeper_step, every=0.3):
        r = reserve(pg, c); assert r.status_code in (200, 201), r.text
        assert count(pg, "nexo_oci") == before + 1
        assert st.write("sintetica") > 0                                    # escritura sintética REAL con el rol de la aplicación
    # sin guardián (se detiene la renovación): la autoridad de la base CADUCA SOLA (reloj de la base) y las escrituras se bloquean
    time.sleep(CFG.ttl_s - CFG.margin_s + 0.6)
    assert not gate.lease.is_valid() and not st.writes_permitted()
    r = reserve(pg, c); assert r.status_code == 503
    with pytest.raises(FencedOut): st.write("tras-vencer")
    e = app_exec(pg, "nexo_oci")
    with pytest.raises(psycopg.errors.Error) as ex: e.tx_insert_probe(lease.epoch, "epoca-correcta-pero-vencida")    # época correcta, autoridad vencida en la BASE
    assert "NEXO_FENCE" in str(ex.value) and count(pg, "nexo_oci") == before + 1


# ───────────────────────────── 6. transacción en curso durante la pérdida de lease ─────────────────────────────
def test_transaccion_larga_iniciada_con_autoridad_no_confirma_despues_de_perderla_ni_con_la_compuerta_de_la_app_engañada(pg, tmp_path):
    reset_fence(pg, "nexo_oci"); store = new_store()
    lease, st = promote(pg, "nexo_oci", store, tmp_path)
    before = count(pg, "nexo_oci", "nexo_fence.write_probe")
    # (a) la transacción empieza con autoridad y se queda abierta más que la autoridad: el servidor rechaza el COMMIT (pausa del proceso)
    with pytest.raises(psycopg.errors.Error) as ex: app_exec(pg, "nexo_oci").tx_insert_probe(lease.epoch, "larga", sleep_s=CFG.ttl_s + 1.0)
    assert "NEXO_FENCE" in str(ex.value) and count(pg, "nexo_oci", "nexo_fence.write_probe") == before
    # (b) con la API real: la comprobación de la APLICACIÓN se «engaña» (devuelve siempre True, como un proceso pausado con una decisión vieja): la BASE igualmente rechaza al COMMIT
    store2 = new_store(); reset_fence(pg, "nexo_oci"); lease2, st2 = promote(pg, "nexo_oci", store2, tmp_path / "b", holder="oci-2") if (tmp_path / "b").mkdir() is None else (None, None)
    gate = make_gate(pg, "nexo_oci", store2, "oci-2", "standby", tmp_path / "b" / "promote"); app, c = make_app(pg, "nexo_oci", gate)
    gate.keeper_step(); gate.allows_writes = lambda: True
    for sess in (app.state.session_factory(),):
        from sqlalchemy import text
        sess.execute(text("INSERT INTO auth_rate_limits (key_hash, failed_count, window_started_at) VALUES ('pg-standby-long', 1, now())"))
        time.sleep(CFG.ttl_s + 1.0)                                          # nadie renueva: la autoridad de la base vence con la transacción abierta
        with pytest.raises(Exception) as ex: sess.commit()
        sess.close(); assert "NEXO_FENCE" in str(ex.value) or "commit" in str(ex.value).lower()
    assert int(admin_exec(pg, "nexo_oci")("select count(*) from auth_rate_limits where key_hash='pg-standby-long'")[0][0]) == 0


# ───────────────────────────── 4./5. partición con primario activo, dos candidatos ─────────────────────────────
class Partitionable:
    """Almacén que se puede aislar para UN cliente (el primario particionado ve StoreUnavailable)."""
    verified = True; ATOMIC_CREATE = True
    def __init__(self, inner): self.inner, self.down = inner, False
    def read(self):
        if self.down: raise StoreUnavailable("partición")
        return self.inner.read()
    def create(self, d):
        if self.down: raise StoreUnavailable("partición")
        return self.inner.create(d)
    def replace(self, e, d):
        if self.down: raise StoreUnavailable("partición")
        return self.inner.replace(e, d)


def test_particion_de_red_con_primario_activo_nunca_hay_dos_escritores_y_el_aislado_pierde_la_autoridad_en_su_base(pg, tmp_path):
    reset_fence(pg, "nexo_aws"); reset_fence(pg, "nexo_oci")
    store = new_store(); primary_view = Partitionable(store)
    pgate = make_gate(pg, "nexo_aws", store, "aws-1", "primary", tmp_path / "p0", store_wrap=primary_view)
    pgate.keeper_step()
    assert pgate.lease.is_valid(); e_aws, e_oci = app_exec(pg, "nexo_aws"), app_exec(pg, "nexo_oci")
    assert e_aws.tx_insert_probe(pgate.lease.epoch, "aws-vivo") > 0
    viol, oks = [], {"aws": 0, "oci": 0}
    stop = threading.Event()
    def hammer():       # el primario SIGUE ACTIVO intentando escribir (con su época), y el standby con la suya, a cada instante
        while not stop.is_set():
            a = o = False
            try:
                ep = pgate.lease.epoch or pgate._fence_epoch or 1; e_aws.tx_insert_probe(ep, "aws"); a = True; oks["aws"] += 1
            except Exception: pass
            try:
                if lease_s is not None and lease_s.epoch: e_oci.tx_insert_probe(lease_s.epoch, "oci"); o = True; oks["oci"] += 1
            except Exception: pass
            if a and o: viol.append(time.time())
            time.sleep(0.05)
    lease_s = None; primary_view.down = True                                 # el primario queda aislado del almacén del lease (y no puede renovar)
    th = threading.Thread(target=hammer, daemon=True); th.start()
    with keeping(pgate.keeper_step, every=0.3):
        lease_s_obj = LeaseClient(store, CFG, holder_id="oci-1", state_path=state_for(store, "oci-1")); st = PgStandby(lease_s_obj, PgFence(keeper_exec(pg, "nexo_oci")), tmp_path / "promote", e_oci, "oci")
        t0 = time.monotonic()
        while not lease_s_obj.acquire().ok:
            assert time.monotonic() - t0 < 20; time.sleep(0.4)
        waited = time.monotonic() - t0
        assert waited >= CFG.ttl_s + CFG.margin_s - 0.9, "el standby tomó el lease ANTES de que caducara el del primario"
        st.enable(lease_s_obj.epoch); lease_s = lease_s_obj
        time.sleep(1.5)
    stop.set(); th.join(timeout=3)
    assert viol == [], "DOS ESCRITORES al mismo tiempo"                     # RECHAZO OBLIGATORIO del split-brain
    assert oks["aws"] > 0 and oks["oci"] > 0                                 # ambos escribieron, pero NUNCA a la vez
    st_aws = PgFence(keeper_exec(pg, "nexo_aws")).status(); assert not st_aws["valid"]       # la base del primario aislado perdió la autoridad por sí sola
    with pytest.raises(psycopg.errors.Error): e_aws.tx_insert_probe(1, "aislado-despues")


def test_dos_candidatos_simultaneos_solo_uno_obtiene_autoridad_y_la_base_no_baja_de_epoca(pg, tmp_path):
    reset_fence(pg, "nexo_oci"); store = new_store(); res = {}
    def cand(name):
        lease = LeaseClient(store, CFG, holder_id=name)
        st = PgStandby(lease, PgFence(keeper_exec(pg, "nexo_oci")), tmp_path / f"promote-{name}", app_exec(pg, "nexo_oci"), name)
        try:
            ok = lease.acquire().ok
            if not ok: res[name] = "sin lease"; return
            st.enable(lease.epoch); res[name] = ("promovido", lease.epoch)
        except FencedOut as e:
            res[name] = "rechazado"
    ths = [threading.Thread(target=cand, args=(n,)) for n in ("cand-A", "cand-B")]; [t.start() for t in ths]; [t.join() for t in ths]
    winners = [v for v in res.values() if isinstance(v, tuple)]
    assert len(winners) == 1, res
    fence = PgFence(keeper_exec(pg, "nexo_oci"))
    with pytest.raises(Exception) as ex: fence.grant(winners[0][1] - 1, "intruso", 30)                     # una época menor se rechaza en la BASE
    assert "NEXO_FENCE" in str(ex.value) and fence.status()["epoch"] == winners[0][1]


# ───────────────────────────── 7. reinicio del backend tras la promoción ─────────────────────────────
def test_reinicio_del_backend_tras_la_promocion_adopta_el_lease_y_mantiene_la_epoca(pg, tmp_path):
    reset_fence(pg, "nexo_oci"); store = new_store(); pf = tmp_path / "promote"
    lease, st = promote(pg, "nexo_oci", store, tmp_path); epoch = lease.epoch
    g1 = make_gate(pg, "nexo_oci", store, "oci-1", "standby", pf); g1.keeper_step(); assert g1.lease.epoch == epoch
    # el proceso muere SIN liberar el lease; arranca otro con el mismo holder_id y el mismo archivo de promoción
    g2 = make_gate(pg, "nexo_oci", store, "oci-1", "standby", pf); app, c = make_app(pg, "nexo_oci", g2)
    assert not g2.lease.is_valid() and reserve(pg, c).status_code == 503              # recién arrancado: aún sin lease (fail-closed)
    g2.keeper_step()
    assert g2.lease.is_valid() and g2.lease.epoch == epoch
    with keeping(g2.keeper_step, every=0.3): assert reserve(pg, c).status_code in (200, 201)
    # otro dueño tomó el lease mientras el backend estaba caído: NO adopta, NO escribe
    time.sleep(CFG.ttl_s + 0.5); rival = LeaseClient(store, CFG, holder_id="rival")
    t0 = time.monotonic()
    while not rival.acquire().ok:
        assert time.monotonic() - t0 < 15; time.sleep(0.4)
    g3 = make_gate(pg, "nexo_oci", store, "oci-1", "standby", pf); g3.keeper_step()
    assert not g3.lease.is_valid(); app3, c3 = make_app(pg, "nexo_oci", g3); assert reserve(pg, c3).status_code == 503
    assert rival.epoch > epoch


# ───────────────────────────── 8. fallo parcial de la promoción ─────────────────────────────
def test_fallo_parcial_de_la_promocion_es_reanudable_y_nunca_deja_escritura_a_medias(pg, tmp_path, monkeypatch):
    reset_fence(pg, "nexo_oci"); store = new_store()
    lease = LeaseClient(store, CFG, holder_id="oci-1", state_path=state_for(store, "oci-1")); st = PgStandby(lease, PgFence(keeper_exec(pg, "nexo_oci")), tmp_path / "promote", app_exec(pg, "nexo_oci"), "oci")
    while not lease.acquire().ok: time.sleep(0.3)
    import pg_standby as PS
    # (a) muere entre conceder la autoridad en la base y escribir el archivo de promoción
    real = os.replace
    monkeypatch.setattr(PS.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("crash simulado")))
    with pytest.raises(OSError): st.enable(lease.epoch)
    monkeypatch.setattr(PS.os, "replace", real)
    assert not st.promote_permitted() and not st.writes_permitted()          # la autoridad está en la base pero NO el permiso: sin escritura a medias
    st.enable(lease.epoch); st.enable(lease.epoch)                           # reanudar y repetir es idempotente
    assert st.writes_permitted() and st.promote_epoch() == lease.epoch
    # (b) la base no responde al conceder: no se crea ningún permiso
    st.disable(); assert not st.promote_permitted()
    broken = PgStandby(lease, PgFence(lambda *a, **k: (_ for _ in ()).throw(OSError("base caída"))), tmp_path / "promote2", app_exec(pg, "nexo_oci"), "oci")
    with pytest.raises(FencedOut): broken.enable(lease.epoch)
    assert not (tmp_path / "promote2").exists()
    # (c) una época posterior ya promovida no se retrocede
    st.enable(lease.epoch); (tmp_path / "promote").write_text(str(lease.epoch + 5))
    with pytest.raises(FencedOut): st.enable(lease.epoch)


# ───────────────────────────── 9./10. retorno del primario AWS, failback, privilegios ─────────────────────────────
def test_retorno_del_primario_aws_queda_vallado_y_el_failback_no_es_automatico(pg, tmp_path):
    import failback as FB
    reset_fence(pg, "nexo_aws"); reset_fence(pg, "nexo_oci"); store = new_store()
    lease, st = promote(pg, "nexo_oci", store, tmp_path)                    # OCI es el escritor (época 1+)
    pgate = make_gate(pg, "nexo_aws", store, "aws-1", "primary", tmp_path / "p0")
    with keeping(st.keeper_step, every=0.3):
        for _ in range(4):                                                   # AWS «vuelve»: intenta recuperar el lease una y otra vez
            pgate.keeper_step(); time.sleep(0.4)
        assert not pgate.lease.is_valid() and not PgFence(keeper_exec(pg, "nexo_aws")).status()["valid"]
        app, c = make_app(pg, "nexo_aws", pgate); assert reserve(pg, c).status_code == 503
        with pytest.raises(psycopg.errors.Error): app_exec(pg, "nexo_aws").tx_insert_probe(1, "retorno-aws")
        assert st.writes_permitted()                                         # el único escritor sigue siendo OCI
        plan = FB.plan_failback(ledger_state="PROMOTED", primary_fenced=True, primary_data_status="DESCONOCIDO", standby_is_writer=True, human_approved=False)
        assert not plan["automatic"] and not plan["allowed"] and any("aprobación" in b for b in plan["blockers"])


def test_atestacion_publicada_vence_y_exige_cobertura_completa(pg, tmp_path):
    store = new_store(); clock = {"t": 1000.0}
    att = FenceAttestation(store, wall=lambda: clock["t"])
    assert att.read()["ok"] is False                                        # sin publicar: no hay garantía
    a = PgFence(keeper_exec(pg, "nexo_aws")).attest(); att.publish(a, 3)
    assert att.read(max_age_s=120, min_epoch=3)["ok"] is True
    clock["t"] += 500; assert att.read(max_age_s=120)["reason"] == "atestación vencida" and att.read(max_age_s=120)["ok"] is False
    clock["t"] = 1000.0; assert att.read(min_epoch=4)["ok"] is False        # de una época anterior
    # una tabla nueva sin trigger (creada saltándose el evento) o un permiso de más rompen la atestación: el evento DDL la cubre automáticamente
    admin_exec(pg, "nexo_aws")("CREATE TABLE public.zz_nueva(i int)")
    assert PgFence(keeper_exec(pg, "nexo_aws")).attest()["ok"] is True and PgFence(keeper_exec(pg, "nexo_aws")).attest()["tables_covered"] == a["tables_covered"] + 1
    admin_exec(pg, "nexo_aws")("GRANT EXECUTE ON FUNCTION nexo_fence.grant_authority(bigint,text,double precision) TO nexoeventos_app")
    bad = PgFence(keeper_exec(pg, "nexo_aws")).attest(); assert bad["ok"] is False and bad["app_role_can_change_fence"] is True
    admin_exec(pg, "nexo_aws")("REVOKE EXECUTE ON FUNCTION nexo_fence.grant_authority(bigint,text,double precision) FROM nexoeventos_app; DROP TABLE public.zz_nueva")


def test_operaciones_sin_privilegios_suficientes_son_rechazadas_por_la_api_y_por_la_base(pg, tmp_path):
    reset_fence(pg, "nexo_oci"); store = new_store(); lease, st = promote(pg, "nexo_oci", store, tmp_path)
    gate = make_gate(pg, "nexo_oci", store, "oci-1", "standby", tmp_path / "promote"); app, c = make_app(pg, "nexo_oci", gate); gate.keeper_step()
    with keeping(gate.keeper_step, every=0.3):
        assert c.get("/api/ops/overview").status_code in (403, 404)         # una cuenta de cliente no ve el estado operativo
        assert c.post(f"/api/events/{pg['event']}/reservations", headers={**ORIGIN, "Idempotency-Key": "sin-csrf-1234"}, json={"quantity": 1}).status_code in (401, 403)   # sin CSRF
        anon = TestClient(app); assert anon.get(f"/api/me/reservations").status_code in (401, 403)
        assert anon.post("/api/auth/register", headers=ORIGIN, json={"email": "x@example.com", "display_name": "X", "password": PW}).status_code in (201, 409, 422, 429)   # promovido: registrar es legítimo
    with pytest.raises(psycopg.errors.Error): app_exec(pg, "nexo_oci")("SELECT nexo_fence.grant_authority(1000,'cliente',60)")      # la aplicación no puede concederse autoridad


def test_la_compuerta_publica_la_atestacion_del_vallado_de_su_base(pg, tmp_path):
    reset_fence(pg, "nexo_aws"); store, astore = new_store(), InMemoryStore()
    gate = make_gate(pg, "nexo_aws", store, "aws-1", "primary", tmp_path / "p0"); gate.attestation = FenceAttestation(astore); gate.attest_every_s = 0
    gate.keeper_step()
    got = FenceAttestation(astore).read(max_age_s=60, min_epoch=gate.lease.epoch)
    assert got["ok"] is True and gate.status()["db_fence"] == {"enabled": True, "latched": False, "last_sync_ok": True, "sync_errors": 0, "clock_anomalies": 0}


def test_extremo_a_extremo_el_orquestador_promueve_con_postgres_real_leyendo_antes_de_escribir(pg, tmp_path):
    """El orquestador REAL (orden I8) con el standby REAL: API en solo lectura → salud → habilitar → escritura real; el primario (AWS) queda aislado del almacén y su base pierde la autoridad."""
    from orchestrator import Adapters, Config, Orchestrator, State
    import evidence as EV
    reset_fence(pg, "nexo_aws"); reset_fence(pg, "nexo_oci"); store = new_store(); pview = Partitionable(store)
    pgate = make_gate(pg, "nexo_aws", store, "aws-1", "primary", tmp_path / "p0", store_wrap=pview); pgate.keeper_step()
    pview.down = True                                                        # el primario queda aislado del almacén del lease (sigue vivo)
    lease = LeaseClient(store, CFG, holder_id="oci-1", state_path=state_for(store, "oci-1")); st = PgStandby(lease, PgFence(keeper_exec(pg, "nexo_oci")), tmp_path / "promote", app_exec(pg, "nexo_oci"), "oci")
    sgate = make_gate(pg, "nexo_oci", store, "oci-1", "standby", tmp_path / "promote"); app, c = make_app(pg, "nexo_oci", sgate)
    order, seen = [], {}

    class A(Adapters):
        def precheck(self): return {"almacen_verificado": True, "standby_listo": True}
        def probe_all(self): return [False, False, False]
        def incident(self): return {"kind": "INSTANCE_DOWN", "promotable": True, "reasons": ["prueba"], "signals": {"ec2": "stopped"}}
        def restore_latest(self): order.append("restore"); return {"fingerprint_ok": True, "backup_age_s": 60.0, "backup": "c04"}
        def lease_acquire(self):
            order.append("lease"); r = lease.acquire(); return (r.ok, r.reason, lease.epoch if r.ok else None, r.wait_s)
        def lease_release(self): lease.release(); st.disable()
        def fencing_assessment(self):
            order.append("fencing"); return EV.assess_fencing(gate=None, aws={"ec2": "stopped", "rds": "available"}, gate_attested=True, db_attested=True, lease_held=lease.is_valid())
        def primary_gate_attested(self): return True
        def standby_readiness(self):
            order.append("health"); seen["write_before_promote"] = reserve(pg, c).status_code                    # la API del standby: lecturas sí, escrituras NO
            return {"livez": c.get("/health").status_code == 200, "ready": c.get("/ready").status_code == 200, "api": c.get("/api/events").status_code == 200}
        def enable_standby(self, epoch): order.append("enable"); st.enable(epoch)
        def standby_status(self): return {"holds_lease": lease.is_valid(), "epoch": lease.epoch}
        def dns_plan(self): return {"destino": "oci"}
        def dns_apply(self): raise AssertionError("DNS en modo de prueba: no se aplica")
        def probe_new_endpoint(self): return True
        def synthetic_write_ok(self):
            order.append("write")
            try: return st.write("orquestador") > 0
            except FencedOut: return False
        def old_can_write(self): return None
        def alert(self, severity, message): seen.setdefault("alerts", []).append(severity)
        def now(self): return time.monotonic()
        def sleep(self, s): time.sleep(min(s, 0.5))

    cfg = Config(quorum=2, rounds=1, round_interval_s=0.1, acquire_timeout_s=30, poll_s=0.4, max_backup_age_s=3600)
    with keeping(pgate.keeper_step, every=0.3):
        res = Orchestrator(A(), cfg, State(tmp_path / "estado.json", "run-pg"), dry_run=True).run()
    assert res["outcome"] == "DONE", res.get("abort_reason")
    import itertools
    assert [k for k, _ in itertools.groupby(order)] == ["restore", "lease", "fencing", "health", "enable", "health", "write"]                       # I8: datos → lease → vallado → salud → escrituras
    assert seen["write_before_promote"] == 503                                                          # antes de promover, la API rechaza escribir
    assert res["fencing"]["verdict"] == "FENCED" and res["incident"]["kind"] == "INSTANCE_DOWN"
    assert st.writes_permitted() and not PgFence(keeper_exec(pg, "nexo_aws")).status()["valid"]        # OCI escribe; la base del primario aislado perdió la autoridad
    with keeping(st.keeper_step, every=0.3):
        sgate.keeper_step(); assert reserve(pg, c).status_code in (200, 201)                           # ya promovido: la API real escribe


def test_un_volcado_tomado_con_autoridad_vigente_se_restaura_sin_autoridad(pg, tmp_path):
    """El volcado del primario trae SU estado del vallado: sin el reset posterior a la restauración, el standby heredaría una autoridad ajena todavía vigente."""
    reset_fence(pg, "nexo_aws"); keeper_exec(pg, "nexo_aws")("SELECT nexo_fence.grant_authority(7, 'aws-1', 60)")
    dump = subprocess.run([str(PGBIN / "pg_dump"), "-Fc", "--no-owner", "--no-acl", "-d", "nexo_aws"], capture_output=True, env=pg["env"], check=True).stdout
    run([str(PGBIN / "psql"), "-q", "-d", "postgres", "-c", "DROP DATABASE IF EXISTS nexo_rest"], env=pg["env"])
    assert run([str(PGBIN / "psql"), "-q", "-d", "postgres", "-c", "CREATE DATABASE nexo_rest OWNER nexoeventos_owner"], env=pg["env"]).returncode == 0
    assert subprocess.run([str(PGBIN / "pg_restore"), "-d", "nexo_rest", "--no-owner", "--no-acl", "--exit-on-error"], input=dump, capture_output=True, env=pg["env"]).returncode == 0
    pg["psql"]("nexo_rest", "GRANT USAGE ON SCHEMA nexo_fence TO nexoeventos_app, nexo_fence_keeper;")
    heredado = admin_exec(pg, "nexo_rest")("SELECT epoch, valid_until > clock_timestamp() FROM nexo_fence.writer_fence")[0]
    assert heredado == (7, True)                                              # SIN el reset, el standby restaurado nace con la autoridad (y época) del primario
    script = (ROOT / "scripts/multicloud/oci-drill/remote-restore.sh").read_text()
    import re
    line = next(l for l in script.splitlines() if "reset_after_restore" in l)
    sql = re.search(r'-c "(.*)"\s*$', line).group(1).replace("\\$", "$")        # la sentencia REAL del script de restauración
    assert "reset_after_restore" in sql
    r = run([str(PGBIN / "psql"), "-d", "nexo_rest", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", sql], env=pg["env"]); assert r.returncode == 0, r.stderr
    after = admin_exec(pg, "nexo_rest")("SELECT epoch, valid_until > clock_timestamp() FROM nexo_fence.writer_fence")[0]
    assert after == (7, False)                                                # sin autoridad, época conservada (nunca baja)
    run([str(PGBIN / "psql"), "-q", "-d", "postgres", "-c", "DROP DATABASE nexo_rest"], env=pg["env"]); reset_fence(pg, "nexo_aws")
