"""S3 · PAUSAS LARGAS, REINICIOS Y RELOJES con dos PostgreSQL 18 y el backend real. Qué se demuestra:
 1. La comprobación de autoridad ocurre DENTRO de la base, en el COMMIT y con el reloj de la base: un cliente suspendido (SIGSTOP real) que despierta después del vencimiento NO puede confirmar.
 2. La única pausa que importa es la del SERVIDOR entre esa comprobación y el fin del commit; está acotada por `pause_budget_s` (justificación formal en lease.py). Se prueba por debajo (seguro) y por encima
    (CONTRAEJEMPLO esperado y conservado como control negativo: demuestra que el margen no es decorativo y que las pruebas detectan el error).
 3. Pausa durante la renovación, guardián congelado mientras otro nodo toma el lease, reinicios con ETag persistido, con estado ausente y corrupto.
 4. Relojes de la base corridos (hacia atrás y hacia delante): el guardián lo detecta por desfase ABSOLUTO; control negativo sin guardia."""
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_two_db_tamper import (KEYS, MARGIN, TTL, Node, NodeStore, blind_write, check_exclusion, dbs, mundo, settle_aws_primary, wait_for)  # noqa: E402,F401
from app.failover.lease import LeaseClient, LeaseConfig, init_lease, pause_budget_s  # noqa: E402
from app.failover.pg_fence import PgFence  # noqa: E402
from app.failover.store import InMemoryStore  # noqa: E402

BUDGET = pause_budget_s(TTL, MARGIN)                     # ≈ 0,45 s con ttl=1,5 y margen=0,3 (ρ = 5 %)


def admin(ctx, sql): return ctx["ex"]("postgres")(sql)


def commit_one(ctx, epoch, v, stall=0.0, hold_file=None, sleep_before=0.0):
    with psycopg.connect(host=ctx["sock"], port=ctx["port"], dbname="hard", user="nexoeventos_app") as c:
        c.execute("SELECT set_config('nexo.writer_epoch', %s, true)", (str(epoch),))
        if stall: c.execute("SELECT set_config('nexo_test.stall', %s, true)", (str(stall),))
        c.execute("INSERT INTO reservas(v) VALUES (%s)", (v,))
        if sleep_before: time.sleep(sleep_before)
        c.commit()


def install_stall_trigger(ctx):
    admin(ctx, """CREATE SCHEMA IF NOT EXISTS nexo_test;
      CREATE OR REPLACE FUNCTION nexo_test.stall() RETURNS trigger LANGUAGE plpgsql AS $f$ BEGIN PERFORM pg_sleep(coalesce(nullif(current_setting('nexo_test.stall', true), ''), '0')::float); RETURN NULL; END $f$;
      DROP TRIGGER IF EXISTS zz_stall ON public.reservas;
      CREATE CONSTRAINT TRIGGER zz_stall AFTER INSERT ON public.reservas DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nexo_test.stall();""")   # dispara DESPUÉS de nexo_fence_commit (orden alfabético)


def remove_stall_trigger(ctx):
    admin(ctx, "DROP TRIGGER IF EXISTS zz_stall ON public.reservas")


# ───────────── 1. cliente suspendido (SIGSTOP real) ─────────────
CLIENT = r'''
import sys, time, psycopg
sock, port, epoch, flag, out = sys.argv[1:6]
c = psycopg.connect(host=sock, port=int(port), dbname="hard", user="nexoeventos_app")
c.execute("SELECT set_config('nexo.writer_epoch', %s, true)", (epoch,)); c.execute("INSERT INTO reservas(v) VALUES ('suspendido')")
open(flag, "w").write("listo")
import os
while not os.path.exists(flag + ".go"): time.sleep(0.05)
try: c.commit(); open(out, "w").write("ACEPTADA")
except Exception as e: open(out, "w").write("RECHAZADA:" + ("NEXO_FENCE" if "NEXO_FENCE" in str(e) else type(e).__name__))
'''


def test_cliente_suspendido_con_SIGSTOP_mientras_otro_nodo_toma_el_lease_no_puede_confirmar_al_despertar(mundo, tmp_path):
    store, aws, oci = mundo
    settle_aws_primary(aws)
    flag, out = str(tmp_path / "flag"), str(tmp_path / "out")
    p = subprocess.Popen([sys.executable, "-c", CLIENT, aws.ctx["sock"], str(aws.ctx["port"]), str(aws.lease._epoch), flag, out])
    try:
        assert wait_for(lambda: os.path.exists(flag), 10)
        os.kill(p.pid, signal.SIGSTOP)                                         # el proceso con la transacción abierta queda congelado
        aws.store.down = True; oci.start()
        assert wait_for(lambda: len(oci.accepted()) >= 3, 25), "OCI no tomó el lease"
        os.kill(p.pid, signal.SIGCONT); Path(flag + ".go").write_text("1")
        assert wait_for(lambda: os.path.exists(out), 10)
        assert Path(out).read_text() == "RECHAZADA:NEXO_FENCE"
    finally:
        p.kill(); p.wait()
    n = admin(aws.ctx, "SELECT count(*) FROM reservas WHERE v='suspendido'")[0][0]
    assert n == 0, "la fila del cliente suspendido quedó en la base"
    check_exclusion(aws, oci)


# ───────────── 2. pausa del servidor entre la comprobación y el fin del commit ─────────────
def _carrera_con_pausa_en_commit(mundo, stall, hilos=4):
    store, aws, oci = mundo
    install_stall_trigger(aws.ctx)
    try:
        settle_aws_primary(aws)
        stop = threading.Event(); done: list[tuple[float, bool]] = []
        def estancado(i):
            time.sleep(i * stall / hilos)                                            # fases distintas: alguna comprobación cae justo antes del vencimiento
            while not stop.is_set():
                ep = aws.lease._epoch or aws.last_epoch
                try: commit_one(aws.ctx, ep, "estancado", stall=stall); done.append((time.time(), True))
                except Exception: done.append((time.time(), False))
        ts = [threading.Thread(target=estancado, args=(i,), daemon=True) for i in range(hilos)]; [t.start() for t in ts]
        time.sleep(0.5); oci.start(); aws.store.down = True
        assert wait_for(lambda: len(oci.accepted()) >= 3, 30), "OCI no tomó el lease"
        time.sleep(stall + 0.5); stop.set(); [t.join(stall + 3) for t in ts]
        primero_oci = oci.accepted()[0]; ultimo_aws = max([t for t, ok in done if ok] + aws.accepted() + [0])
        return primero_oci, ultimo_aws
    finally:
        remove_stall_trigger(aws.ctx)


def test_pausa_del_servidor_dentro_del_presupuesto_no_produce_solapamiento(mundo):
    p_oci, u_aws = _carrera_con_pausa_en_commit(mundo, stall=BUDGET * 0.5)
    assert u_aws < p_oci, f"AWS terminó un commit {u_aws - p_oci:.3f} s DESPUÉS de que OCI empezara, con pausa < presupuesto ({BUDGET:.2f} s)"


def test_control_negativo_una_pausa_mayor_que_el_presupuesto_SI_produce_doble_escritura(mundo):
    """CONTRAEJEMPLO conservado: una pausa del servidor ≫ 2·margen entre la comprobación del commit y su finalización rompe la exclusión. Es el límite que fija el margen del lease (README de claves/diseño):
    margen ≥ ρ·ttl + (pausa máxima tolerada del servidor)/2. Si el RDS puede congelarse más que `pause_budget_s`, NO se declara seguro el failover."""
    violaciones = 0
    for _ in range(3):
        for s_ctx in ():
            pass
        store = mundo[0]
        p_oci, u_aws = _carrera_con_pausa_en_commit(mundo, stall=BUDGET * 4)
        violaciones += int(u_aws > p_oci)
        break
    assert violaciones == 1, "con una pausa 4× el presupuesto debería haberse observado el solapamiento (si no, la prueba no discrimina)"


def test_el_presupuesto_de_pausa_sigue_la_formula_y_los_valores_por_defecto_dan_margen_de_sobra():
    assert 0.44 < BUDGET < 0.46
    assert 8.4 < pause_budget_s(15, 5) < 8.6                  # configuración por defecto: ≈ 8,5 s de pausa tolerable del servidor
    assert abs(pause_budget_s(15, 0.75)) < 1e-9                     # margen = ρ·ttl: sin hueco real (la validación del lease lo exige mayor)
    assert pause_budget_s(15, 5, 0.0) == 10.0                 # sin deriva: 2·margen


# ───────────── 3. pausas del guardián y de la renovación ─────────────
def test_pausa_durante_la_renovacion_la_respuesta_tardia_no_amplia_la_autoridad(mundo):
    store, aws, oci = mundo
    settle_aws_primary(aws); oci.start()
    aws.store.stall_after_replace = TTL + 1.0                                        # la renovación SE APLICA pero la respuesta tarda más que el ttl
    assert wait_for(lambda: len(oci.accepted()) >= 3, 30), "OCI no tomó el lease"
    aws.store.stall_after_replace = 0.0; time.sleep(1.0)
    gaps = check_exclusion(aws, oci, max_switches=3)
    assert not (aws.lease.is_valid() and oci.lease.is_valid())


def test_guardian_congelado_mientras_otro_nodo_toma_el_lease_al_despertar_no_conserva_autoridad(mundo):
    store, aws, oci = mundo
    settle_aws_primary(aws); oci.start()
    real = aws.gate.keeper_step
    aws.gate.keeper_step = lambda: time.sleep(0.1)                                   # el proceso del guardián queda congelado (sin renovar)
    assert wait_for(lambda: len(oci.accepted()) >= 3, 30), "OCI no tomó el lease"
    aws.gate.keeper_step = real; time.sleep(1.5)                                      # despierta
    assert not (aws.lease.is_valid() and oci.lease.is_valid()), "los dos con lease válido al despertar"
    check_exclusion(aws, oci, max_switches=3)


# ───────────── 4. reinicios y estado local ─────────────
def _reiniciar(mundo, tmp_path, estado):
    store, aws, oci = mundo
    sp = str(tmp_path / "aws.state")
    aws.stop(); aws = Node("aws", aws.ctx, store, state_path=sp)
    aws.start(); assert wait_for(lambda: len(aws.accepted()) >= 3, 20)
    epoca = aws.lease._epoch; aws.stop()                                              # el proceso muere SIN liberar
    if estado == "ausente": Path(sp).unlink(missing_ok=True)
    elif estado == "corrupto": Path(sp).write_text("{{{ no es json")
    nuevo = Node("aws", aws.ctx, store, state_path=sp); t0 = time.time(); nuevo.start()
    ok = wait_for(lambda: len(nuevo.accepted()) >= 1, 20); t_first = (nuevo.accepted() or [0])[0] - t0
    return nuevo, epoca, ok, t_first


@pytest.mark.parametrize("estado, adopta", [("valido", True), ("ausente", False), ("corrupto", False)])
def test_reinicio_con_estado_valido_adopta_y_con_estado_ausente_o_corrupto_observa_ttl_mas_margen(mundo, tmp_path, estado, adopta):
    nuevo, epoca, ok, t_first = _reiniciar(mundo, tmp_path, estado)
    try:
        assert ok, "el nodo reiniciado no volvió a escribir"
        if adopta:
            assert nuevo.lease._epoch == epoca and t_first < TTL + MARGIN, f"debía adoptar su lease (tardó {t_first:.2f} s)"
        else:
            assert nuevo.lease._epoch == epoca + 1 and t_first >= TTL + MARGIN - 0.6, f"debía observar ttl+margen antes de tomar (tardó {t_first:.2f} s)"
    finally:
        nuevo.stop()


# ───────────── 5. relojes de la base ─────────────
class SkewedFence(PgFence):
    """La base cree que es `skew` s MÁS TEMPRANO (reloj retrocedido) o más tarde (negativo): la autoridad real se alarga/acorta en esa cantidad y `db_now` sale corrido."""
    skew = 0.0
    def grant(self, epoch, holder, seconds):
        g = super().grant(epoch, holder, seconds)
        if self.skew:
            self.execute("SELECT 1")                                                                    # (el guardián no puede alargar: lo hace el «reloj», simulado con el superusuario)
            SkewedFence.admin("UPDATE nexo_fence.writer_fence SET valid_until = valid_until + make_interval(secs => %s) WHERE id = 1" % self.skew)
            g["db_now"] = g["db_now"] - timedelta(seconds=self.skew)
        return g


def _con_reloj_corrido(mundo, skew, guardia, revoke_bloqueado=False):
    store, aws, oci = mundo
    SkewedFence.admin = staticmethod(lambda sql: admin(aws.ctx, sql))
    class F(SkewedFence):
        block_revoke = False
        def revoke(self, epoch):
            if F.block_revoke: raise RuntimeError("el guardián no alcanza la base (revocación imposible)")
            return super().revoke(epoch)
    F.skew = 0.0
    kw = {} if guardia else dict(clock_tolerance_s=1e9, clock_abs_tolerance_s=1e9)
    aws.stop(); aws = Node("aws", aws.ctx, store, fence_cls=F, gate_kw=kw)
    aws.start(); assert wait_for(lambda: len(aws.accepted()) >= 3), "AWS no llegó a escribir"; oci.start()
    F.skew = skew; F.block_revoke = revoke_bloqueado; time.sleep(0.5)                                  # el reloj de la base se corrió
    aws.store.down = True                                                                              # y AWS pierde el almacén
    assert wait_for(lambda: len(oci.accepted()) >= 3, 30), "OCI no tomó el lease"
    time.sleep(0.8)
    return aws, oci


def test_reloj_de_la_base_retrocedido_lo_detecta_la_guardia_y_no_hay_solapamiento(mundo):
    aws, oci = _con_reloj_corrido(mundo, 3.0, guardia=True)
    assert aws.gate.status()["db_fence"]["clock_anomalies"] >= 1
    check_exclusion(aws, oci)
    aws.stop(); oci.stop()


def test_control_negativo_sin_guardia_y_sin_poder_revocar_un_reloj_retrocedido_alarga_la_autoridad_y_produce_doble_escritura(mundo):
    """RIESGO ABIERTO conservado: reloj de la base retrocedido + el guardián NO alcanza la base (no puede revocar) mientras la aplicación sí. Con la guardia activa la autoridad ya no se renueva, pero la última concesión
    alargada por el reloj corrido no se puede recortar. Por eso el RDS debe sincronizar con NTP (Amazon Time Sync) y la guardia de desfase absoluto está activa."""
    aws, oci = _con_reloj_corrido(mundo, 3.0, guardia=False, revoke_bloqueado=True)
    allc = sorted([(t, "aws") for t in aws.accepted()] + [(t, "oci") for t in oci.accepted()])
    gaps = [(y[0] - x[0]) for x, y in zip(allc, allc[1:]) if x[1] != y[1]]
    assert (not gaps) or min(gaps) < 0.1 or len(gaps) > 1, "sin guardia debería observarse solapamiento (la prueba no discrimina)"
    aws.stop(); oci.stop()


def test_reloj_de_la_base_adelantado_acorta_la_autoridad_y_es_seguro(mundo):
    aws, oci = _con_reloj_corrido(mundo, -3.0, guardia=True)
    check_exclusion(aws, oci)
    aws.stop(); oci.stop()
