"""PAUSA LARGA DEL SERVIDOR: mecanismo que NO depende de un presupuesto máximo de pausa. Dos PostgreSQL 18, backend real (WriteGate + install_db_guard con SQLAlchemy).
Una pausa del servidor entre la comprobación del commit y su fin MÁS LARGA que cualquier presupuesto SÍ puede dejar un commit huérfano en la base antigua (la prueba de control lo demuestra). Lo que se garantiza:
  · BARRERA DE RECONOCIMIENTO: ningún commit se reconoce al cliente (HTTP 2xx) si el COMMIT volvió después de perderse la autoridad con la que empezó → ningún reconocimiento se solapa con el otro nodo.
  · DETECCIÓN: la base registra cada transacción aceptada (commit_log) y `late_commits()` enumera las que terminaron tras vencer la autoridad (con track_commit_timestamp=on): son huérfanas y se descartan en el failback.
Control negativo: con la barrera neutralizada, SÍ hay reconocimientos posteriores al primer commit del nuevo escritor."""
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pg_fence_hardening import PGBIN, run, start_cluster  # noqa: E402,F401
from test_two_db_tamper import Node, wait_for, TTL, MARGIN  # noqa: E402
from test_two_db_pauses import install_stall_trigger, remove_stall_trigger, admin, BUDGET  # noqa: E402
from app.failover.gate import WriteFenceError, WriteOutcomeUnknown, install_db_guard  # noqa: E402
from app.failover.lease import init_lease  # noqa: E402
from app.failover.pg_fence import PgFence, install_sql  # noqa: E402
from app.failover.store import InMemoryStore  # noqa: E402

pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")


@pytest.fixture(scope="module")
def dbs2(tmp_path_factory):
    out, stops = {}, []
    for side in ("aws", "oci"):
        ctx, t, sock = start_cluster(tmp_path_factory, f"ab{side}", "-c track_commit_timestamp=on")
        ctx["ex"]("master_like")(install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper", event_trigger=False))
        out[side] = ctx; stops.append((ctx, t, sock))
    yield out
    for ctx, t, sock in stops:
        run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


def escenario(dbs2, stall, barrera=True, hilos=6):
    for ctx in dbs2.values():
        admin(ctx, "UPDATE nexo_fence.writer_fence SET epoch = 0, valid_until = '-infinity', holder = NULL WHERE id = 1")
        admin(ctx, "SET session_replication_role = replica; TRUNCATE reservas RESTART IDENTITY; DELETE FROM nexo_fence.commit_log")
    store = InMemoryStore(); store.verified = True; init_lease(store, ttl_s=TTL, margin_s=MARGIN)
    aws, oci = Node("aws", dbs2["aws"], store), Node("oci", dbs2["oci"], store)
    ctx = dbs2["aws"]
    engine = create_engine(f"postgresql+psycopg://nexoeventos_app@/hard?host={ctx['sock']}&port={ctx['port']}", pool_pre_ping=False)
    SL = sessionmaker(engine, expire_on_commit=False); install_db_guard(engine, SL, aws.gate)
    if not barrera:
        aws.gate.ack_ok = lambda begin: True                                           # control negativo: se neutraliza SOLO la barrera
    install_stall_trigger(ctx)
    try:
        aws.gate.start(); assert wait_for(lambda: aws.lease.is_valid() and aws.gate.last_db_sync_ok, 15), "AWS no obtuvo autoridad"
        oci.start()
        stop = threading.Event(); res: list[tuple[str, float]] = []
        def app_writer(i):
            time.sleep(i * stall / hilos)
            while not stop.is_set():
                try:
                    with SL() as s:
                        s.execute(text("SELECT set_config('nexo_test.stall', :v, true)"), {"v": str(stall)}); s.execute(text("INSERT INTO reservas(v) VALUES ('app')")); s.commit()
                    res.append(("ack", time.time()))
                except WriteOutcomeUnknown: res.append(("desconocido", time.time()))
                except WriteFenceError: res.append(("cerrado", time.time())); time.sleep(0.05)
                except Exception: res.append(("rechazado", time.time())); time.sleep(0.05)
        ts = [threading.Thread(target=app_writer, args=(i,), daemon=True) for i in range(hilos)]; [t.start() for t in ts]
        time.sleep(stall + 1.0); aws.store.down = True                                 # con el almacén sano la autoridad es continua y los commits lentos SÍ se reconocen
        assert wait_for(lambda: len(oci.accepted()) >= 3, 30), "OCI no tomó el lease"
        time.sleep(stall + 1.0); stop.set(); [t.join(stall + 4) for t in ts]
        late = PgFence(ctx["ex"]("nexo_fence_keeper")).late_commits()
        return res, oci.accepted()[0], late, aws, oci
    finally:
        remove_stall_trigger(ctx); aws.gate._stop.set(); aws.stop(); oci.stop(); engine.dispose()


def test_con_una_pausa_muy_superior_a_cualquier_presupuesto_nada_se_reconoce_despues_del_nuevo_escritor_y_los_huerfanos_se_detectan(dbs2):
    res, primero_oci, late, aws, oci = escenario(dbs2, stall=BUDGET * 6)                       # ≈ 2,7 s ≫ presupuesto 0,45 s
    acks = [t for k, t in res if k == "ack"]; desconocidos = [t for k, t in res if k == "desconocido"]
    assert acks, "la prueba no tuvo efecto: nadie confirmó con autoridad"
    assert max(acks) < primero_oci, f"se reconoció un commit {max(acks) - primero_oci:.3f} s DESPUÉS de que el nuevo escritor empezara"
    assert desconocidos, "la barrera debía haberse activado (commits que terminaron tras perder la autoridad)"
    assert late and all(x["late_by_s"] > 0 for x in late), "la base debía haber registrado los commits huérfanos (terminaron tras vencer la autoridad)"
    assert aws.gate.status()["blocked"]["unacknowledged"] >= 1


def test_control_negativo_sin_la_barrera_SI_se_reconocen_commits_despues_del_nuevo_escritor(dbs2):
    res, primero_oci, late, aws, oci = escenario(dbs2, stall=BUDGET * 6, barrera=False)
    acks = [t for k, t in res if k == "ack"]
    assert acks and max(acks) > primero_oci, "sin barrera debería haberse reconocido un commit posterior (si no, la prueba no discrimina)"
    assert late                                                                          # y la base sigue registrando el huérfano


def test_commit_dentro_del_plazo_se_reconoce_y_no_figura_como_tardio(dbs2):
    res, primero_oci, late, aws, oci = escenario(dbs2, stall=0.05, hilos=2)
    assert sum(1 for k, _ in res if k == "ack") >= 3 and max(t for k, t in res if k == "ack") < primero_oci
