"""EXCLUSIÓN MUTUA ENTRE DOS BASES con un almacén de lease MANIPULABLE. Dos PostgreSQL 18 desechables (el «AWS» y el «OCI»), el backend real (WriteGate + LeaseClient + PgFence con vallado en la base,
sin event triggers, administrador tipo RDS) y un almacén compartido en el que un atacante o un controlador defectuoso sobrescribe sin If-Match. En CADA escenario hay escritores que intentan confirmar
sin parar en las DOS bases (con la época que creen tener, aunque ya no la tengan) y se exige: nunca confirmaciones de ambos lados solapadas ni alternadas (A…B…A), y el escritor anterior rechazado."""
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
from app.failover.store import InMemoryStore, StoreUnavailable  # noqa: E402

pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")
TTL, MARGIN = 1.5, 0.3
KEYS = {"aws": b"clave-aws-" * 3, "oci": b"clave-oci-" * 3, "mal": b"clave-mal-" * 3}


@pytest.fixture(scope="module")
def dbs(tmp_path_factory):
    out, stops = {}, []
    for side in ("aws", "oci"):
        ctx, t, sock = start_cluster(tmp_path_factory, f"td{side}")
        ctx["ex"]("master_like")(install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper", event_trigger=False))
        out[side] = ctx; stops.append((ctx, t, sock))
    yield out
    for ctx, t, sock in stops:
        run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


class NodeStore:
    """Vista de un nodo sobre el almacén compartido; `down` simula partición/pérdida de acceso al almacén."""
    verified = True; ATOMIC_CREATE = True
    def __init__(self, inner): self.inner, self.down = inner, False
    def _chk(self):
        if self.down: raise StoreUnavailable("partición simulada")
    def read(self): self._chk(); return self.inner.read()
    def create(self, d): self._chk(); return self.inner.create(d)
    stall_after_replace = 0.0
    def replace(self, e, d):
        self._chk(); r = self.inner.replace(e, d)
        if self.stall_after_replace: time.sleep(self.stall_after_replace)          # la escritura SE APLICÓ en el servidor pero la respuesta llega tarde (pausa durante la renovación)
        return r


class Node:
    def __init__(self, name, ctx, store, keys=KEYS, lease_cls=None, state_path=None, fence_cls=None, gate_kw=None, lease_kw=None):
        self.name, self.ctx = name, ctx
        self.store = NodeStore(store)
        self.lease = (lease_cls or LeaseClient)(self.store, LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id=name, auth_keys=(None if (lease_kw or {}).get("authenticator") else keys), state_path=state_path, **(lease_kw or {}))
        self.gate = WriteGate(self.lease, role="primary", db_fence=(fence_cls or PgFence)(ctx["ex"]("nexo_fence_keeper"), app_role="nexoeventos_app"), **{**dict(keeper_interval_s=0.2, attach_every_s=0.5, clock_tolerance_s=0.5), **(gate_kw or {})})
        self.last_epoch = 0; self.commits: list[tuple[float, bool, str]] = []; self._stop = threading.Event(); self.threads: list[threading.Thread] = []

    def start(self):
        self.gate.start()
        def writer():
            while not self._stop.wait(0.03):
                e = self.lease._epoch or self.last_epoch; self.last_epoch = max(self.last_epoch, e)
                if not e: continue
                try:
                    with psycopg.connect(host=self.ctx["sock"], port=self.ctx["port"], dbname="hard", user="nexoeventos_app") as c:
                        c.execute("SELECT set_config('nexo.writer_epoch', %s, true)", (str(e),))
                        c.execute("INSERT INTO reservas(v) VALUES (%s)", (self.name,)); c.commit()
                    self.commits.append((time.time(), True, self.name))
                except Exception as ex:  # noqa: BLE001
                    self.commits.append((time.time(), False, "NEXO_FENCE" if "NEXO_FENCE" in str(ex) else type(ex).__name__))
        t = threading.Thread(target=writer, daemon=True); t.start(); self.threads.append(t)

    def stop(self):
        self._stop.set(); self.gate._stop.set()
        for t in self.threads: t.join(2)
        if self.gate._thread: self.gate._thread.join(2)
        try: self.ctx["ex"]("nexo_fence_keeper")("SELECT nexo_fence.revoke_authority(%s)", (self.last_epoch or 1,))
        except Exception: pass

    def accepted(self): return [t for t, ok, _ in self.commits if ok]


@pytest.fixture
def mundo(dbs):
    for side, ctx in dbs.items():                                           # estado limpio: sin autoridad, época 0, sin datos
        ctx["ex"]("postgres")("UPDATE nexo_fence.writer_fence SET epoch = 0, valid_until = '-infinity', holder = NULL WHERE id = 1"); ctx["ex"]("postgres")("SET session_replication_role = replica; TRUNCATE reservas RESTART IDENTITY")
    store = InMemoryStore(); store.verified = True; init_lease(store, ttl_s=TTL, margin_s=MARGIN)
    aws, oci = Node("aws", dbs["aws"], store), Node("oci", dbs["oci"], store)
    yield store, aws, oci
    aws.stop(); oci.stop()


def blind_write(store, **f):
    import json
    base = dict(v=1, holder=None, epoch=0, seq=0, ttl_s=TTL, margin_s=MARGIN, released=False, signer=None); base.update(f)
    with store._lock:
        store._gen += 1; store._data = json.dumps(base).encode()


def wait_for(cond, timeout=15.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if cond(): return True
        time.sleep(step)
    return False


def check_exclusion(aws, oci, max_switches=1, min_gap=0.1):
    """Orden total de las confirmaciones aceptadas de las dos bases. Un cambio de lado exige un HUECO sin escritor ≥ min_gap (los escritores intentan cada 30 ms: un solapamiento real de autoridades
    produciría confirmaciones de ambos lados separadas por milisegundos). Se limita además el número de cambios de lado."""
    allc = sorted([(t, "aws") for t in aws.accepted()] + [(t, "oci") for t in oci.accepted()])
    gaps = [(y[0] - x[0]) for x, y in zip(allc, allc[1:]) if x[1] != y[1]]
    assert len(gaps) <= max_switches, f"demasiados cambios de lado ({len(gaps)})"
    assert all(g >= min_gap for g in gaps), f"confirmaciones de ambas bases con huecos de {[round(g, 3) for g in gaps]} s: DOBLE ESCRITURA"
    return gaps


def settle_aws_primary(aws):
    aws.start(); assert wait_for(lambda: len(aws.accepted()) >= 3), "AWS no llegó a escribir"


def test_traspaso_legitimo_aws_pierde_el_almacen_oci_toma_despues_de_caducar_y_nunca_se_solapan(mundo):
    store, aws, oci = mundo
    settle_aws_primary(aws); oci.start()
    aws.store.down = True                                                                  # partición: AWS sigue VIVO y sigue intentando escribir
    assert wait_for(lambda: len(oci.accepted()) >= 3, 20), "OCI no tomó el lease"
    time.sleep(1.0)
    gaps = check_exclusion(aws, oci); a, o = aws.accepted(), oci.accepted()
    assert gaps and gaps[0] >= 2 * MARGIN - 0.2, f"el hueco ({gaps}) debe ser ≥ 2·margen (teórico): OCI esperó ttl+margen y la autoridad de AWS caduca a ttl−margen"
    rechazos = [r for t, ok, r in aws.commits if not ok and t > o[0]]
    assert rechazos and all(r == "NEXO_FENCE" for r in rechazos), "tras perder la autoridad el escritor anterior debe ser rechazado POR LA BASE"


def test_sobrescritura_ciega_con_liberacion_o_titular_falsificado_no_da_autoridad_a_oci_mientras_AWS_la_tiene(mundo):
    store, aws, oci = mundo
    settle_aws_primary(aws); oci.start()
    for forged in (dict(holder=None, epoch=aws.lease._epoch, seq=10**6, released=True), dict(holder="oci", epoch=aws.lease._epoch, seq=10**6)):
        blind_write(store, **forged); time.sleep(0.4)
        assert not (aws.lease.is_valid() and oci.lease.is_valid()), "dos controladores con lease válido"
    assert wait_for(lambda: len(oci.accepted()) >= 3, 25), "OCI debería poder tomar por el camino honesto tras observar ttl+margen"
    time.sleep(1.0)
    check_exclusion(aws, oci, max_switches=3)


def test_liberacion_falsificada_con_AWS_incomunicado_no_produce_doble_escritura(mundo):
    """El mismo escenario que el control negativo de abajo (que SÍ falla con un cliente ingenuo), con el cliente real."""
    store, aws, oci = mundo
    settle_aws_primary(aws); oci.start(); time.sleep(0.5)
    aws.store.down = True
    blind_write(store, holder=None, epoch=aws.lease._epoch, seq=10**6, released=True)
    assert wait_for(lambda: len(oci.accepted()) >= 3, 25), "OCI debería tomar por el camino honesto tras observar ttl+margen"
    time.sleep(0.5)
    gaps = check_exclusion(aws, oci)
    assert gaps and gaps[0] >= 2 * MARGIN - 0.2


def test_reutilizacion_de_un_registro_antiguo_no_devuelve_la_autoridad_a_AWS(mundo):
    store, aws, oci = mundo
    settle_aws_primary(aws); viejo = store.read().data
    oci.start(); aws.store.down = True
    assert wait_for(lambda: len(oci.accepted()) >= 3, 20)
    with store._lock:
        store._gen += 1; store._data = viejo                                               # el atacante restaura el registro viejo de AWS
    aws.store.down = False                                                                 # y AWS vuelve a ver el almacén
    time.sleep(0.8)
    assert not aws.lease.is_valid() or not oci.lease.is_valid(), "los dos con lease válido tras el registro reutilizado"
    assert not any(ok and t > time.time() - 0.7 for t, ok, _ in aws.commits), "AWS confirmó justo tras la reutilización (adopción instantánea)"
    time.sleep(6.0)                                                      # después, por el camino honesto, AWS puede volver a tomar el lease LIBRE (OCI lo perdió por la manipulación)
    check_exclusion(aws, oci, max_switches=4)


def test_controlador_defectuoso_que_envia_operaciones_incorrectas_no_rompe_la_exclusion(mundo):
    store, aws, oci = mundo
    settle_aws_primary(aws)
    mal = LeaseClient(NodeStore(store), LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id="mal", auth_keys=KEYS)
    stop = threading.Event()
    def spam():
        while not stop.is_set():
            try:
                rv = store.read()
                store.replace("etag-inventado", b"{}")                                     # CAS con ETag falso
            except Exception: pass
            try: store.replace(rv.etag + "x", b"basura")
            except Exception: pass
            mal.acquire(); mal.renew(); time.sleep(0.02)
    t = threading.Thread(target=spam, daemon=True); t.start()
    oci.start(); time.sleep(4.0); stop.set(); t.join(2)
    check_exclusion(aws, oci, max_switches=0)                                       # AWS conserva el lease: OCI jamás escribe
    assert not oci.accepted()
    assert not (aws.lease.is_valid() and oci.lease.is_valid())


def test_particion_total_ambos_pierden_el_almacen_nadie_escribe_tras_caducar_y_al_volver_solo_uno(mundo):
    store, aws, oci = mundo
    settle_aws_primary(aws); oci.start()
    aws.store.down = oci.store.down = True
    time.sleep(TTL + 1.0); n_aws = len(aws.accepted()); n_oci = len(oci.accepted()); time.sleep(1.0)
    assert len(aws.accepted()) == n_aws and len(oci.accepted()) == n_oci, "alguien siguió confirmando sin lease"
    aws.store.down = oci.store.down = False
    assert wait_for(lambda: len(aws.accepted()) > n_aws or len(oci.accepted()) > n_oci, 25), "nadie recuperó el lease tras la partición"
    time.sleep(1.5); check_exclusion(aws, oci, max_switches=3)


def test_transaccion_iniciada_con_autoridad_y_confirmada_despues_de_perderla_es_rechazada_por_la_base(mundo):
    store, aws, oci = mundo
    settle_aws_primary(aws)
    ctx = aws.ctx; epoch = aws.lease._epoch
    c = psycopg.connect(host=ctx["sock"], port=ctx["port"], dbname="hard", user="nexoeventos_app")
    c.execute("SELECT set_config('nexo.writer_epoch', %s, true)", (str(epoch),)); c.execute("INSERT INTO reservas(v) VALUES ('larga')")
    aws.store.down = True                                                                  # se pierde el lease mientras la transacción está abierta
    time.sleep(TTL + 0.5)
    with pytest.raises(psycopg.Error) as ei:
        c.commit()
    assert "NEXO_FENCE" in str(ei.value)
    c.close()
    n = psycopg.connect(host=ctx["sock"], port=ctx["port"], dbname="hard", user="postgres").execute("SELECT count(*) FROM reservas WHERE v='larga'").fetchone()[0]
    assert n == 0, "la fila de la transacción rechazada quedó en la base"


class IngenuoClient(LeaseClient):
    """CONTROL NEGATIVO = el diseño anterior: se fía del CONTENIDO del almacén (cualquier liberación vale, el ttl publicado manda). Con él la misma sobrescritura ciega SÍ produce doble escritura:
    demuestra que las pruebas de arriba discriminan y que las defensas (no fiarse del contenido, esperar ttl+margen locales) son las que protegen."""
    def _authentic(self, rec): return True
    def _need(self, rec): return 0.05


def test_control_negativo_un_cliente_que_se_fia_del_contenido_SI_permite_doble_escritura(dbs):
    for side, ctx in dbs.items():
        ctx["ex"]("postgres")("UPDATE nexo_fence.writer_fence SET epoch = 0, valid_until = '-infinity', holder = NULL WHERE id = 1"); ctx["ex"]("postgres")("SET session_replication_role = replica; TRUNCATE reservas RESTART IDENTITY")
    store = InMemoryStore(); store.verified = True; init_lease(store, ttl_s=TTL, margin_s=MARGIN)
    aws, oci = Node("aws", dbs["aws"], store, lease_cls=IngenuoClient), Node("oci", dbs["oci"], store, lease_cls=IngenuoClient)
    try:
        settle_aws_primary(aws); oci.start(); time.sleep(0.5)
        aws.store.down = True                                                                       # AWS no ve el almacén (no se entera de nada) pero su base sigue con autoridad vigente
        blind_write(store, holder=None, epoch=aws.lease._epoch, seq=10**6, released=True)           # «el titular se fue» (falso)
        wait_for(lambda: len(oci.accepted()) >= 3, 10); time.sleep(0.5)
        with pytest.raises(AssertionError):
            check_exclusion(aws, oci, max_switches=3)
    finally:
        aws.stop(); oci.stop()
