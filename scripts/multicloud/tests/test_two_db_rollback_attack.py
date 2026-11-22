"""ROLLBACK SIMULTÁNEO con dos PostgreSQL 18 reales: el atacante restaura lease + registro del sello (coherentes y firmados) y la base de AWS a un snapshot antiguo; arranca una instancia AWS NUEVA. Se mide lo que importa:
si se ESCRIBEN reservas en la base de AWS. Versión vulnerable (sin testigo): SÍ se escriben (control negativo). Versión corregida (testigo de frescura independiente): ni se adquiere autoridad ni se escribe nada."""
import sys
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "failover"))
from test_two_db_restart_after_promotion import dbs4, GatedOci, TTL, MARGIN, wait_for, Node, PgFence  # noqa: E402,F401
from test_two_db_hard_fence import commit_ts, reset  # noqa: E402
from test_two_db_seal_log import keeper_ratchet  # noqa: E402
from app.failover.lease import Ed25519Auth, init_lease  # noqa: E402
from app.failover.seal_log import InMemoryLog, LogGuard, append, make_sealer  # noqa: E402
from app.failover.store import InMemoryStore  # noqa: E402
from app.failover.witness import CompositeGuard, LocalWitnessClient, Witness, WitnessGuard, make_report  # noqa: E402
from promotion_gate import StrongFence  # noqa: E402

raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def filas_aws(dbs4): return dbs4["aws"]["ex"]("postgres")("SELECT count(*) FROM reservas")[0][0]


def historia(dbs4, tmp_path):
    reset({"aws": dbs4["aws"], "oci": dbs4["oci"]}); dbs4["aws"]["ex"]("postgres")("UPDATE nexo_fence.seal_ratchet SET seq = 0")
    ks = {n: Ed25519PrivateKey.generate() for n in ("aws", "oci", "operator", "witness")}; pubs = {n: [pub(v)] for n, v in ks.items()}
    auth = {n: Ed25519Auth(n, raw(ks[n]), pubs) for n in ks}
    ls = InMemoryStore(); ls.verified = True; init_lease(ls, ttl_s=TTL, margin_s=MARGIN); log = InMemoryLog(worm=False)
    wit = Witness(tmp_path / "testigo.jsonl", auth["witness"], auth["witness"]); wc = LocalWitnessClient(wit)
    g = append(log, auth["operator"], "operator", "unsealed", 0)
    assert wit.report(*make_report(auth["operator"], "operator", kind="genesis", lease_epoch=0, seal_seq=1, seal_digest=g.digest()))[0]
    rep = lambda n: (lambda ep: wit.report(*make_report(auth[n], n, kind="lease_epoch", lease_epoch=ep)))
    a1 = Node("aws", dbs4["aws"], ls, lease_kw={"authenticator": auth["aws"], "epoch_reporter": rep("aws")}); a1.start(); assert wait_for(lambda: len(a1.accepted()) >= 3, 15)
    old_lease, old_log = ls.read().data, dict(log.objs)                                                       # copias del atacante (con AWS como titular legítimo, época 1)
    dbs4["_stop"]("aws"); a1.stop()
    go = GatedOci(dbs4, ls, auth); go.node.lease.epoch_reporter = rep("oci"); go.node.start(); assert wait_for(lambda: go.node.lease.is_valid(), 40)
    def sin_base(): raise ConnectionError("RDS detenida")
    assert StrongFence(hard_fence=sin_base, aws_read=lambda: {"rds": "stopped"}).establish()["strong"]
    make_sealer(log, auth["oci"], witness_report=lambda seq, dig, ep: wit.report(*make_report(auth["oci"], "oci", kind="seal_head", seal_seq=seq, seal_digest=dig)))(go.node.lease._epoch)
    go.allowed.set(); assert wait_for(lambda: len(go.node.accepted()) >= 3, 15)
    dbs4["_start"]("aws")                                                                                     # la RDS vuelve
    return ls, log, auth, wit, wc, go, old_lease, old_log


def ataque(dbs4, ls, log, old_lease, old_log):
    with ls._lock: ls._gen += 1; ls._data = old_lease                                                          # lease antiguo (firma válida)
    log.objs = dict(old_log)                                                                                    # registro del sello antiguo (cadena válida)
    x = dbs4["aws"]["ex"]("postgres")                                                                           # base de AWS «restaurada de un snapshot antiguo»: sin autoridad, época y trinquete viejos, sin cerrojo
    x("UPDATE nexo_fence.writer_fence SET epoch = 0, valid_until = '-infinity', holder = NULL WHERE id = 1; UPDATE nexo_fence.latch SET latched = false, since = NULL, reason = NULL; UPDATE nexo_fence.seal_ratchet SET seq = 0")


def instancia_nueva(dbs4, ls, log, auth, guard):
    n = Node("aws", dbs4["aws"], ls, lease_kw={"authenticator": auth["aws"], "acquire_guard": guard}); n.lease.holder_id = "aws-instancia-nueva"; return n


def test_VULNERABLE_la_instancia_nueva_adquiere_con_informacion_antigua_y_ESCRIBE_reservas_en_AWS(dbs4, tmp_path):
    ls, log, auth, wit, wc, go, old_lease, old_log = historia(dbs4, tmp_path)
    try:
        antes = filas_aws(dbs4); ataque(dbs4, ls, log, old_lease, old_log)
        go.node.gate._stop.set()                                                                               # OCI pierde su lease por la restauración (su CAS ya no coincide)
        n = instancia_nueva(dbs4, ls, log, auth, LogGuard(log, auth["aws"], keeper_ratchet(dbs4)))              # guardia vulnerable: registro + trinquete (vacío: base «restaurada»)
        n.start()
        assert wait_for(lambda: len(n.accepted()) >= 1, 40), "(control negativo) la versión vulnerable debía permitir escribir con información antigua"
        assert filas_aws(dbs4) > antes, "se escribieron reservas en AWS sobre una historia anterior a la promoción de OCI"
        n.stop()
    finally:
        go.node.stop()


def test_CORREGIDA_ni_se_adquiere_autoridad_ni_se_escribe_ninguna_reserva_con_nodo_nuevo_y_base_antigua(dbs4, tmp_path):
    ls, log, auth, wit, wc, go, old_lease, old_log = historia(dbs4, tmp_path)
    try:
        antes = filas_aws(dbs4); ataque(dbs4, ls, log, old_lease, old_log); go.node.gate._stop.set()
        g = CompositeGuard(WitnessGuard(wc, auth["aws"], log), LogGuard(log, auth["aws"], keeper_ratchet(dbs4)))
        n = instancia_nueva(dbs4, ls, log, auth, g); n.start()
        time.sleep(TTL + MARGIN + 4.0)
        assert not n.lease.is_valid() and not n.accepted(), "la versión corregida adquirió autoridad con información antigua"
        assert filas_aws(dbs4) == antes, "se escribieron reservas en AWS"
        assert any("TRUNCAMIENTO" in x or "RETROCESO" in x for x in g.guards[0].rejects)
        # con el testigo CAÍDO tampoco hay autoridad (falla cerrado), aunque el estado fuera legítimo
        wit.down = True; time.sleep(2.0); assert not n.lease.is_valid() and not n.accepted() and filas_aws(dbs4) == antes
        n.stop()
    finally:
        go.node.stop()


def test_CORREGIDA_tras_un_reinicio_completo_de_la_instancia_nueva_sigue_bloqueada(dbs4, tmp_path):
    ls, log, auth, wit, wc, go, old_lease, old_log = historia(dbs4, tmp_path)
    try:
        antes = filas_aws(dbs4); ataque(dbs4, ls, log, old_lease, old_log); go.node.gate._stop.set()
        for _ in range(2):                                                                                       # dos instancias nuevas consecutivas (reinicio): sin memoria compartida
            n = instancia_nueva(dbs4, ls, log, auth, CompositeGuard(WitnessGuard(wc, auth["aws"], log), LogGuard(log, auth["aws"], keeper_ratchet(dbs4)))); n.start()
            time.sleep(TTL + MARGIN + 2.0); assert not n.lease.is_valid() and not n.accepted(); n.stop()
        assert filas_aws(dbs4) == antes
    finally:
        go.node.stop()
