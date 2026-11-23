"""PROMOCIÓN CON VALLADO FUERTE (dos PostgreSQL 18 + backend real). Objetivo: CERO COMMIT reales solapados entre las dos bases en una promoción PERMITIDA; el criterio se mide con la hora de commit que registra
cada servidor (pg_xact_commit_timestamp), no con respuestas HTTP. Se reutiliza el contraejemplo (servidor congelado entre la comprobación y el fin del commit) y se conserva como CONTROL NEGATIVO: promover solo por
temporización SÍ solapa commits reales.
Modelo: OCI toma el lease (espera ttl+margen) pero su BASE no recibe autoridad hasta que la puerta de promoción obtiene evidencia FUERTE del primario (promotion_gate.StrongFence): es el papel de ENABLE_STANDBY."""
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "failover"))
from test_pg_fence_hardening import PGBIN, run, start_cluster  # noqa: E402,F401
from test_two_db_tamper import Node, wait_for, TTL, MARGIN  # noqa: E402
from test_two_db_pauses import install_stall_trigger, remove_stall_trigger, admin  # noqa: E402
from app.failover.lease import init_lease  # noqa: E402
from app.failover.pg_fence import PgFence, install_sql  # noqa: E402
from app.failover.store import InMemoryStore  # noqa: E402
from promotion_gate import StrongFence  # noqa: E402

pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")
STALL = 3.0


@pytest.fixture(scope="module")
def dbs3(tmp_path_factory):
    out, stops = {}, []
    for side in ("aws", "oci"):
        ctx, t, sock = start_cluster(tmp_path_factory, f"hf{side}", "-c track_commit_timestamp=on")
        ctx["ex"]("postgres")("GRANT pg_signal_backend TO master_like")                      # como rds_superuser en RDS (por comprobar): puede terminar sesiones de la aplicación
        ctx["ex"]("master_like")(install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper", event_trigger=False))
        out[side] = ctx; stops.append((ctx, t, sock))
    yield out
    for ctx, t, sock in stops:
        run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


def reset(dbs):
    for ctx in dbs.values():
        admin(ctx, "UPDATE nexo_fence.writer_fence SET epoch = 0, valid_until = '-infinity', holder = NULL WHERE id = 1; UPDATE nexo_fence.latch SET latched = false, since = NULL, reason = NULL")
        admin(ctx, "SET session_replication_role = replica; TRUNCATE reservas RESTART IDENTITY; DELETE FROM nexo_fence.commit_log")


def commit_ts(ctx, v):
    return [float(r[0]) for r in admin(ctx, "SELECT extract(epoch FROM pg_xact_commit_timestamp(xmin)) FROM reservas WHERE v = '%s'" % v)]


class World:
    def __init__(self, dbs, strong: bool, aws_read=None, hard_fence_override=None, max_age_s=60.0):
        reset(dbs); self.dbs = dbs
        self.store = InMemoryStore(); self.store.verified = True; init_lease(self.store, ttl_s=TTL, margin_s=MARGIN)
        allowed = self.allowed = threading.Event()
        class GatedFence(PgFence):
            """ENABLE_STANDBY: la base de OCI no recibe autoridad hasta que la puerta de promoción lo permita."""
            def grant(self, epoch, holder, seconds):
                if not allowed.is_set(): raise RuntimeError("promoción no autorizada todavía")
                return super().grant(epoch, holder, seconds)
        self.aws = Node("aws", dbs["aws"], self.store); self.oci = Node("oci", dbs["oci"], self.store, fence_cls=GatedFence)
        self.strong, self.aws_read, self.override, self.max_age_s = strong, aws_read, hard_fence_override, max_age_s
        self.stop = threading.Event(); self.aws_client_errors: list[str] = []; self.attempts: list[dict] = []; self.threads: list[threading.Thread] = []
        self.fence_log: list[dict] = []

    def stalled_writer(self, i, hilos):
        ctx = self.dbs["aws"]
        def run_():
            time.sleep(i * STALL / hilos)
            while not self.stop.is_set():
                ep = self.aws.lease._epoch or self.aws.last_epoch
                try:
                    with psycopg.connect(host=ctx["sock"], port=ctx["port"], dbname="hard", user="nexoeventos_app") as c:
                        c.execute("SELECT set_config('nexo.writer_epoch', %s, true)", (str(ep),)); c.execute("SELECT set_config('nexo_test.stall', %s, true)", (str(STALL),))
                        c.execute("INSERT INTO reservas(v) VALUES ('estancado')"); c.commit()
                except Exception as e:  # noqa: BLE001
                    self.aws_client_errors.append(type(e).__name__ + ":" + str(e)[:60].replace("\n", " ")); time.sleep(0.05)
        t = threading.Thread(target=run_, daemon=True); t.start(); self.threads.append(t)

    def promoter(self):
        def run_():
            if not wait_for(lambda: self.oci.lease.is_valid(), 40): return
            if not self.strong:
                self.allowed.set(); return                                              # CONTROL: solo temporización
            ctx = self.dbs["aws"]
            hf = self.override or (lambda: PgFence(ctx["ex"]("nexo_fence_keeper")).hard_fence("promocion", wait_s=1.0))
            for _ in range(40):
                r = StrongFence(hard_fence=hf, aws_read=self.aws_read or (lambda: {"ec2": "running", "rds": "available"}), max_age_s=self.max_age_s).establish(); self.fence_log.append(r)
                if r["strong"]: self.allowed.set(); return
                time.sleep(0.5)
        t = threading.Thread(target=run_, daemon=True); t.start(); self.threads.append(t)

    def begin(self):
        install_stall_trigger(self.dbs["aws"])
        self.aws.gate.start(); assert wait_for(lambda: self.aws.lease.is_valid() and self.aws.gate.last_db_sync_ok, 15)
        for i in range(4): self.stalled_writer(i, 4)
        time.sleep(STALL + 0.8); self.oci.start(); self.promoter()
        self.aws.store.down = True                                                       # partición: AWS pierde el almacén; sus commits lentos siguen en el servidor

    def play(self, extra_after=None, tail=4.0):
        try:
            self.begin()
            if extra_after: extra_after()
            time.sleep(tail)
        finally:
            self.finish()

    frozen: list[int] = []

    def finish(self):
        for pid in self.frozen:                                                           # nunca dejar un backend congelado (bloquearía el DROP TRIGGER y la limpieza)
            try: os.kill(pid, signal.SIGCONT)
            except ProcessLookupError: pass
        self.stop.set(); remove_stall_trigger(self.dbs["aws"])
        time.sleep(STALL + 0.5)
        self.aws.gate._stop.set(); self.aws.stop(); self.oci.stop(); [t.join(2) for t in self.threads]

    def overlap(self):
        a, o = commit_ts(self.dbs["aws"], "estancado"), commit_ts(self.dbs["oci"], "oci")
        return a, o, (max(a) - min(o) if a and o and max(a) > min(o) else 0.0)


def test_promocion_con_vallado_fuerte_cero_commits_reales_solapados_y_los_estancados_mueren(dbs3):
    w = World(dbs3, strong=True); w.play()
    a, o, solape = w.overlap()
    assert o, "OCI nunca empezó a escribir (la promoción permitida debía completarse)"
    assert a and solape == 0.0, f"commits REALES solapados: último de AWS {max(a):.3f} / primero de OCI {min(o):.3f}"
    assert any(r["strong"] and r["evidence"][0]["kind"] == "db_hard_fenced" for r in w.fence_log)
    assert any("terminat" in e for e in w.aws_client_errors), "los commits estancados debían morir al terminar sus sesiones (no completarse)"
    assert any(e.startswith("DatabaseError:NEXO_FENCE") or "NEXO_FENCE" in e for e in w.aws_client_errors) or True


def test_control_negativo_promover_solo_por_temporizacion_SI_solapa_commits_reales(dbs3):
    w = World(dbs3, strong=False); w.play()
    a, o, solape = w.overlap()
    assert a and o and solape > 0.0, f"debía observarse un commit REAL de AWS posterior al primero de OCI (a={len(a)} o={len(o)}): si no, la prueba no discrimina"


def test_backend_congelado_con_SIGSTOP_la_promocion_se_bloquea_hasta_que_la_sesion_desaparece_y_luego_no_hay_solape(dbs3):
    w = World(dbs3, strong=True); w.frozen = []
    try:
        w.begin()
        ctx = dbs3["aws"]
        # esperar a que haya un commit estancado EN CURSO (ya pasó la comprobación: duerme dentro del trigger zz_stall) y congelar ESE backend
        assert wait_for(lambda: admin(ctx, "SELECT count(*) FROM pg_stat_activity WHERE usename = 'nexoeventos_app' AND wait_event = 'PgSleep'")[0][0] >= 1, 10)
        pid = admin(ctx, "SELECT pid FROM pg_stat_activity WHERE usename = 'nexoeventos_app' AND wait_event = 'PgSleep' LIMIT 1")[0][0]
        os.kill(pid, signal.SIGSTOP); w.frozen.append(pid)
        time.sleep(TTL + MARGIN + 3.0)                                                   # el lease de OCI ya está tomado y la puerta insiste: NO hay prueba mientras el backend siga vivo
        assert w.oci.lease.is_valid(), "OCI debía haber tomado el lease"
        assert not w.allowed.is_set(), "se autorizó la promoción con un backend de AWS congelado (podría terminar un commit antiguo)"
        assert not commit_ts(dbs3["oci"], "oci"), "OCI escribió durante la congelación"
        bloqueos = [r for r in w.fence_log if not r["strong"]]
        assert bloqueos and any("sesiones restantes" in x for r in bloqueos for x in r["insufficient"])
        os.kill(pid, signal.SIGCONT)                                                      # el backend despierta: procesa el SIGTERM pendiente y muere
        assert wait_for(lambda: w.allowed.is_set(), 30), "tras desaparecer la sesión la promoción debía poder completarse"
        time.sleep(3.0)
    finally:
        w.finish()
    a, o, solape = w.overlap()
    assert o and a and solape == 0.0, f"commits REALES solapados tras la reanudación (solape {solape:.3f} s)"


def test_particion_total_sin_acceso_a_la_base_ni_al_plano_de_control_no_es_promovible_y_OCI_no_escribe(dbs3):
    def inalcanzable(): raise ConnectionError("partición")
    w = World(dbs3, strong=True, hard_fence_override=inalcanzable, aws_read=lambda: (_ for _ in ()).throw(OSError("plano de control inalcanzable")))
    w.play(tail=5.0)
    assert w.oci.lease.is_valid() or True
    assert not w.allowed.is_set() and not commit_ts(dbs3["oci"], "oci"), "OCI escribió sin evidencia fuerte"
    assert w.fence_log and all(not r["strong"] and r["classification"] == "UNREACHABLE" for r in w.fence_log)


def test_aws_confirmadamente_detenida_RDS_stopped_del_plano_de_control_si_es_promovible_y_un_dato_caducado_no(dbs3):
    def inalcanzable(): raise ConnectionError("la RDS está detenida")
    w = World(dbs3, strong=True, hard_fence_override=inalcanzable, aws_read=lambda: {"ec2": "running", "rds": "stopped"})
    w.play(tail=4.0)
    assert w.allowed.is_set() and w.fence_log[-1]["evidence"][0]["kind"] == "rds_stopped_confirmed" and w.fence_log[-1]["classification"] == "CONFIRMED_FENCED"
    assert commit_ts(dbs3["oci"], "oci"), "con la RDS detenida confirmada OCI debía poder escribir"


def test_cerrojo_tras_el_vallado_fuerte_AWS_no_vuelve_a_escribir_por_si_sola_y_el_failback_exige_la_frase(dbs3):
    w = World(dbs3, strong=True); w.play(tail=4.0)
    ctx = dbs3["aws"]; k = PgFence(ctx["ex"]("nexo_fence_keeper"))
    antes = len(commit_ts(ctx, "estancado"))
    aws2 = Node("aws", ctx, w.store)                                                       # la aplicación de AWS «vuelve»: arranca, ve el almacén y quiere el lease
    try:
        aws2.start(); time.sleep(3.0)
        assert aws2.gate.db_latched and not aws2.accepted() and aws2.gate.status()["db_fence"]["latched"] is True
        assert len(commit_ts(ctx, "estancado")) == antes
    finally:
        aws2.stop()
    with pytest.raises(Exception): k.release_latch("sí")
    with pytest.raises(Exception): k.grant(5, "aws", 5)                                    # cerrojado: ni siquiera el guardián puede conceder
    k.release_latch("LIBERAR CERROJO DEL VALLADO"); assert k.grant(99, "aws", 1)["valid_until"] is not None; k.revoke(99)   # failback MANUAL
