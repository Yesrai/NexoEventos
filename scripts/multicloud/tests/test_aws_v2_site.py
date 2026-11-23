"""AWS V2: dos EC2 del MISMO sitio detrás de un ALB frente al lease de escritura del sitio (PostgreSQL 18 desechable con el vallado real instalado).
Una sola instancia (líder, bloqueo consultivo) habla con el lease entre nubes; la otra (miembro) recibe la autoridad que la BASE ya tiene concedida. La seguridad NO depende de la elección."""
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pg_fence_hardening import PGBIN, run, start_cluster  # noqa: E402,F401

import psycopg  # noqa: E402
from app.failover.gate import WriteGate  # noqa: E402
from app.failover.lease import LeaseClient, LeaseConfig, init_lease  # noqa: E402
from app.failover.pg_fence import PgFence, install_sql  # noqa: E402
from app.failover.site_member import SiteElection  # noqa: E402
from app.failover.store import InMemoryStore  # noqa: E402

pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")
CFG = dict(ttl_s=1.2, margin_s=0.3)


@pytest.fixture(scope="module")
def cl(tmp_path_factory):
    ctx, t, sock = start_cluster(tmp_path_factory, "v2s")
    ctx["ex"]("master_like")(install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper", event_trigger=False))
    yield ctx
    run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


class PgConn:
    """Conexión dedicada del bloqueo (psycopg, autocommit) con la interfaz mínima que pide SiteElection."""
    def __init__(self, cl): self.c = psycopg.connect(host=cl["sock"], port=cl["port"], dbname="hard", user="nexo_fence_keeper", autocommit=True)
    def scalar(self, sql, params): return self.c.execute(sql, params).fetchone()[0]
    def close(self): self.c.close()


class Site:
    """Un sitio con N instancias: el mismo almacén de lease, la misma identidad de sitio («aws») y la misma base."""
    def __init__(self, cl, n=2, elect=True):
        self.cl, self.store = cl, InMemoryStore(); self.store.verified = True; init_lease(self.store)
        self.fences, self.gates = [], []
        for _ in range(n):
            f = PgFence(cl["ex"]("nexo_fence_keeper"), app_role="nexoeventos_app"); f.grants = 0
            orig = f.grant
            def counted(e, h, s, f=f, orig=orig): f.grants += 1; return orig(e, h, s)
            f.grant = counted
            el = SiteElection(lambda: PgConn(cl), "aws", check_every_s=0.0) if elect else None
            g = WriteGate(LeaseClient(self.store, LeaseConfig(**CFG), holder_id="aws"), role="primary", db_fence=f, election=el, clock_tolerance_s=0.5)
            self.fences.append(f); self.gates.append(g)

    def write(self, gate, tag):
        """Una escritura REAL como la aplicación: la transacción declara la época de SU autoridad; la base valida al COMMIT."""
        ep = gate.lease.epoch or 0
        with psycopg.connect(host=self.cl["sock"], port=self.cl["port"], dbname="hard", user="nexoeventos_app") as c:
            c.execute("SELECT set_config('nexo.writer_epoch', %s, true)", (str(ep),)); c.execute("INSERT INTO reservas(v) VALUES (%s)", (tag,))

    def close(self):
        for g in self.gates:
            g.stop()


@pytest.fixture
def clean(cl):
    reset = lambda: cl["ex"]("postgres")("UPDATE nexo_fence.writer_fence SET epoch = 0, valid_until = '-infinity', holder = NULL WHERE id = 1; SET session_replication_role = replica; TRUNCATE reservas; DELETE FROM nexo_fence.commit_log")
    reset(); yield; reset()


def test_dos_instancias_un_solo_lider_ambas_escriben_con_la_misma_epoca_y_el_miembro_no_toca_el_lease(cl, clean):
    s = Site(cl); a, b = s.gates
    try:
        a.keeper_step(); b.keeper_step()
        assert a.election.is_leader and not b.election.is_leader and b.is_site_member()
        assert a.allows_writes() and b.allows_writes() and a.lease.epoch == b.lease.epoch == 1          # ambas pueden atender ESCRITURAS con la misma época
        s.write(a, "desde-a"); s.write(b, "desde-b")                                                    # y la base las acepta
        assert [r[0] for r in cl["ex"]("postgres")("SELECT v FROM reservas ORDER BY id")] == ["desde-a", "desde-b"]
        assert s.fences[1].grants == 0 and b.own_lease._etag is None, "el miembro NO debe conceder ni tomar el lease"
        seq0 = a.own_lease._seq
        for _ in range(3): a.keeper_step(); b.keeper_step()
        assert a.own_lease._seq == seq0 + 3 and b.own_lease._etag is None and a.lease.epoch == b.lease.epoch == 1       # la época NO cambia: no hay «peleas» por el lease
        st = b.status(); assert st["site"] == {"leader": False, "member": True} and st["holds_lease"] is True
    finally: s.close()


def test_el_miembro_nunca_tiene_mas_autoridad_que_la_base_revocacion_y_caducidad(cl, clean):
    s = Site(cl); a, b = s.gates
    try:
        a.keeper_step(); b.keeper_step(); assert b.allows_writes()
        s.fences[0].revoke(a.lease.epoch)                                    # la base pierde la autoridad (revocación)
        b.keeper_step(); assert not b.allows_writes()                          # el miembro la retira en su siguiente ciclo
        with pytest.raises(psycopg.Error): s.write(b, "sin-autoridad")           # y aunque insistiera, la BASE rechaza (la época 0 no es la vigente)
        a.keeper_step(); b.keeper_step(); assert b.allows_writes()             # el líder vuelve a conceder: el miembro la recupera
        time.sleep(1.2); assert not b.allows_writes()                        # sin más ciclos (líder caído, red cortada) la autoridad del miembro caduca SOLA (monótono local)
    finally: s.close()


def test_si_el_lider_cae_el_miembro_toma_el_liderazgo_tras_caducar_el_lease_y_con_epoca_nueva(cl, clean):
    s = Site(cl); a, b = s.gates
    try:
        a.keeper_step(); b.keeper_step(); s.write(a, "antes"); e1 = a.lease.epoch
        a.election.resign()                                                   # el líder muere (su conexión se cierra, el bloqueo cae)
        deadline = time.time() + 12
        while time.time() < deadline and not (b.election.is_leader and b.own_lease.is_valid()):
            b.keeper_step(); time.sleep(0.2)
        assert b.election.is_leader and b.lease is b.own_lease and b.lease.epoch > e1          # nuevo líder, época NUEVA (nunca reutiliza la del antiguo)
        s.write(b, "despues")
        assert [r[0] for r in cl["ex"]("postgres")("SELECT v FROM reservas ORDER BY id")] == ["antes", "despues"]
    finally: s.close()


def test_la_eleccion_no_produce_dos_lideres_ni_con_carreras(cl):
    for _ in range(15):
        els = [SiteElection(lambda: PgConn(cl), "aws-race", check_every_s=0.0) for _ in range(4)]
        res = []
        ths = [threading.Thread(target=lambda e=e: res.append(e.step())) for e in els]; [t.start() for t in ths]; [t.join() for t in ths]
        assert sum(res) == 1
        [e.resign() for e in els]


def test_la_seguridad_no_depende_de_la_eleccion_dos_lideres_forzados_solo_uno_tiene_el_lease(cl, clean):
    s = Site(cl, elect=False); a, b = s.gates                                # sin elección: AMBAS compiten por el lease (el comportamiento anterior)
    try:
        a.keeper_step(); b.keeper_step()
        assert a.allows_writes() and not b.allows_writes()                      # el lease (CAS) deja pasar a UNA: la otra no tiene autoridad
        with pytest.raises(psycopg.Error): s.write(b, "intruso")
        for _ in range(3): a.keeper_step(); b.keeper_step()
        assert a.lease.epoch == 1 and not b.allows_writes()                    # sin pelea de épocas
    finally: s.close()


def test_el_miembro_exige_el_vallado_de_la_base(cl):
    store = InMemoryStore(); store.verified = True; init_lease(store)
    with pytest.raises(ValueError, match="vallado"):
        WriteGate(LeaseClient(store, LeaseConfig(**CFG), holder_id="aws"), role="primary", election=object())
