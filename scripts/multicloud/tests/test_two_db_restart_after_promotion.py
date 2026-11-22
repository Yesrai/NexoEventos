"""REINICIO DEL PRIMARIO TRAS LA PROMOCIÓN: RDS detenida → OCI promovida → la RDS vuelve a encender (sola a los 7 días, o alguien) → AWS (backend, guardián, Auto Scaling) intenta escribir.
Protecciones PERSISTENTES y verificables que no dependen de la memoria ni de un archivo de la EC2: (1) SELLO de promoción firmado en el almacén de OCI (fuera de AWS); (2) CERROJO en la base, puesto por la guardia de
reinicio en cuanto la RDS responde. Dos PostgreSQL 18 reales (la de AWS se detiene y se vuelve a arrancar de verdad). Control negativo: sin sello ni cerrojo AWS SÍ recupera el lease y escribe sobre datos viejos."""
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "failover"))
from test_pg_fence_hardening import PGBIN, run, start_cluster  # noqa: E402,F401
from test_two_db_tamper import Node, wait_for, TTL, MARGIN  # noqa: E402
from test_two_db_hard_fence import commit_ts, reset  # noqa: E402
from app.failover.lease import Ed25519Auth, init_lease  # noqa: E402
from app.failover.pg_fence import PgFence, install_sql  # noqa: E402
from app.failover.seal import SealGuard, seal, unseal  # noqa: E402
from app.failover.store import InMemoryStore  # noqa: E402
from promotion_gate import StrongFence  # noqa: E402
from restart_guard import RestartGuard  # noqa: E402

pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")
raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


@pytest.fixture(scope="module")
def dbs4(tmp_path_factory):
    out, meta = {}, {}
    for side in ("aws", "oci"):
        ctx, t, sock = start_cluster(tmp_path_factory, f"rs{side}", "-c track_commit_timestamp=on")
        ctx["ex"]("postgres")("GRANT pg_signal_backend TO master_like")
        ctx["ex"]("master_like")(install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper", event_trigger=False))
        out[side] = ctx; meta[side] = (t, sock)
    def stop(side): run([str(PGBIN / "pg_ctl"), "-D", str(meta[side][0] / "pg"), "-m", "fast", "stop"], env=out[side]["env"])
    def start(side):
        c = out[side]
        r = run([str(PGBIN / "pg_ctl"), "-D", str(meta[side][0] / "pg"), "-o", f"-c listen_addresses= -c unix_socket_directories={c['sock']} -c port={c['port']} -c fsync=off -c track_commit_timestamp=on", "-l", str(meta[side][0] / "log2"), "-w", "start"], env=c["env"])
        assert r.returncode == 0, r.stderr
    out["_stop"], out["_start"] = stop, start
    yield out
    for side in ("aws", "oci"):
        run([str(PGBIN / "pg_ctl"), "-D", str(meta[side][0] / "pg"), "-m", "immediate", "stop"], env=out[side]["env"]); shutil.rmtree(meta[side][1], ignore_errors=True)


def mundo(dbs4, with_seal=True):
    reset({"aws": dbs4["aws"], "oci": dbs4["oci"]})
    k = {n: Ed25519PrivateKey.generate() for n in ("aws", "oci", "operator")}; pubs = {n: [pub(v)] for n, v in k.items()}
    auth = {n: Ed25519Auth(n, raw(k[n]), pubs) for n in k}
    ls = InMemoryStore(); ls.verified = True; init_lease(ls, ttl_s=TTL, margin_s=MARGIN)
    ss = InMemoryStore(); ss.verified = True; unseal(ss, auth["operator"], 0)                    # despliegue: sello inicializado «unsealed» por el operador
    return ls, ss, auth


def aws_node(dbs4, ls, ss, auth, with_seal=True):
    kw = {"authenticator": auth["aws"]}
    if with_seal: kw["acquire_guard"] = SealGuard(ss, auth["aws"], cache_s=0.2)
    return Node("aws", dbs4["aws"], ls, lease_kw=kw)


class GatedOci:
    def __init__(self, dbs4, ls, auth):
        allowed = self.allowed = threading.Event()
        class G(PgFence):
            def grant(self, epoch, holder, seconds):
                if not allowed.is_set(): raise RuntimeError("promoción no autorizada")
                return super().grant(epoch, holder, seconds)
        self.node = Node("oci", dbs4["oci"], ls, fence_cls=G, lease_kw={"authenticator": auth["oci"]})


def promote(dbs4, g, ss, auth, rds_state="stopped"):
    """Orquestador: lease de OCI → evidencia fuerte (RDS `stopped`: la base no responde) → SELLAR → habilitar."""
    assert wait_for(lambda: g.node.lease.is_valid(), 40), "OCI no tomó el lease"
    def sin_base(): raise ConnectionError("RDS detenida")
    r = StrongFence(hard_fence=sin_base, aws_read=lambda: {"ec2": "stopped", "rds": rds_state}).establish()
    assert r["strong"] and r["evidence"][0]["kind"] == "rds_stopped_confirmed", r
    seal(ss, auth["oci"], g.node.lease._epoch)                                               # ANTES de habilitar escrituras
    g.allowed.set()


def secuencia(dbs4, with_seal, with_latch):
    ls, ss, auth = mundo(dbs4)
    a1 = aws_node(dbs4, ls, ss, auth, with_seal); a1.start(); assert wait_for(lambda: len(a1.accepted()) >= 3, 15)
    dbs4["_stop"]("aws"); a1.stop()                                                           # RDS detenida y EC2 detenida (el proceso muere SIN liberar el lease)
    g = GatedOci(dbs4, ls, auth); g.node.start(); promote(dbs4, g, ss, auth)
    assert wait_for(lambda: len(g.node.accepted()) >= 3, 15), "OCI no escribió tras la promoción"
    dbs4["_start"]("aws")                                                                     # la RDS REINICIA
    estado = {"rds": "available"}; alertas = []
    guard = RestartGuard(aws_read=lambda: dict(estado), hard_fence=lambda: PgFence(dbs4["aws"]["ex"]("nexo_fence_keeper")).hard_fence("reinicio", wait_s=2.0), alert=lambda s, m: alertas.append(m))
    if with_latch: guard.step()                                                               # la guardia de reinicio valla la base en cuanto responde
    a2 = aws_node(dbs4, ls, ss, auth, with_seal); a2.start()                                  # el backend / el guardián / una instancia nueva de Auto Scaling intentan escribir
    return ls, ss, auth, a1, a2, g, guard, alertas


@pytest.mark.parametrize("con_sello, con_cerrojo", [(True, True), (True, False), (False, True)])
def test_secuencia_completa_AWS_no_escribe_tras_el_reinicio_ni_aunque_OCI_deje_de_renovar(dbs4, con_sello, con_cerrojo):
    """Cada protección BASTA por separado (defensa en profundidad): sello sin cerrojo (la base aún no respondía), cerrojo sin sello (el almacén del sello inaccesible o no consultado)."""
    ls, ss, auth, a1, a2, g, guard, alertas = secuencia(dbs4, with_seal=con_sello, with_latch=con_cerrojo)
    try:
        time.sleep(TTL + MARGIN + 2.0)
        assert not a2.accepted() and not a2.lease.is_valid(), "AWS escribió tras el reinicio con OCI como escritor"
        assert guard.latched == con_cerrojo and (not con_cerrojo or any("volvió a estar" in m for m in alertas))
        g.node.gate._stop.set(); g.node.lease._deadline = None                                # OCI deja de renovar (falla): el lease queda libre/caducable…
        time.sleep(TTL + MARGIN + 3.0)
        assert not a2.accepted() and not a2.lease.is_valid(), "AWS recuperó la autoridad sola cuando OCI dejó de renovar"
        assert (con_cerrojo and a2.gate.status()["db_fence"]["latched"] is True) or (con_sello and "sellado" in a2.lease.acquire().reason)
        a_aws, o = commit_ts(dbs4["aws"], "aws"), commit_ts(dbs4["oci"], "oci")
        assert a_aws and o and max(a_aws) < min(o), "los commits de AWS deben ser todos anteriores a los de OCI"
    finally:
        a2.stop(); g.node.stop(); a1.stop()


def test_failback_manual_firma_del_operador_y_cerrojo_levantado_AWS_vuelve_solo_entonces(dbs4):
    ls, ss, auth, a1, a2, g, guard, alertas = secuencia(dbs4, with_seal=True, with_latch=True)
    try:
        time.sleep(TTL + 1.0); assert not a2.accepted()
        g.node.stop(); a2.stop()                                                              # se apaga el escritor OCI y la instancia de AWS (decisión humana de volver)
        k = PgFence(dbs4["aws"]["ex"]("nexo_fence_keeper"))
        epoch = g.node.lease._epoch or 1
        unseal(ss, auth["operator"], epoch)                                                    # 1) levantar el SELLO (clave del operador, fuera de los nodos)
        k.release_latch("LIBERAR CERROJO DEL VALLADO")                                         # 2) levantar el CERROJO en la base
        a3 = aws_node(dbs4, ls, ss, auth, True); a3.start()
        try: assert wait_for(lambda: len(a3.accepted()) >= 2, 30), "con sello y cerrojo levantados AWS debía poder volver"
        finally: a3.stop()
    finally:
        a1.stop(); a2.stop(); g.node.stop()


def test_control_negativo_sin_sello_ni_cerrojo_AWS_recupera_el_lease_y_escribe_sobre_datos_viejos(dbs4):
    ls, ss, auth, a1, a2, g, guard, alertas = secuencia(dbs4, with_seal=False, with_latch=False)
    try:
        g.node.gate._stop.set()                                                                # OCI deja de renovar
        assert wait_for(lambda: len(a2.accepted()) >= 1, 30), "(control) sin sello ni cerrojo AWS debía recuperar la autoridad: si no, la prueba no discrimina"
    finally:
        a2.stop(); g.node.stop(); a1.stop()
