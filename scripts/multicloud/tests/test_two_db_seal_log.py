"""SELLO ANTIRRETROCESO integrado con la puerta de promoción y el bloqueo de AWS: dos PostgreSQL 18 reales, registro de sello de apéndice encadenado y firmado (Ed25519) con o sin retención WORM, trinquete persistente en la BASE de AWS
(nexo_fence.ratchet_seal), guardia de reinicio que lo sube cuando la RDS vuelve. Secuencia: RDS detenida → OCI promovida y sella → RDS vuelve → un atacante con permiso de sobrescritura/borrado intenta devolver un «unsealed» antiguo →
AWS (que reinicia sus procesos) debe seguir sin poder escribir aunque OCI deje de renovar. Controles negativos: sin retención NI trinquete NI cerrojo el retroceso por borrado SÍ devuelve la autoridad a AWS."""
import sys
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "failover"))
from test_two_db_restart_after_promotion import dbs4, GatedOci, TTL, MARGIN, wait_for, Node, PgFence  # noqa: E402,F401
from test_two_db_hard_fence import commit_ts, reset  # noqa: E402
from app.failover.lease import Ed25519Auth, init_lease  # noqa: E402
from app.failover.seal_log import InMemoryLog, LogGuard, PgRatchet, _name, append, make_sealer  # noqa: E402
from app.failover.store import InMemoryStore, PreconditionFailed  # noqa: E402
from promotion_gate import StrongFence  # noqa: E402
from restart_guard import RestartGuard  # noqa: E402

raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def keeper_ratchet(dbs4):
    from pg_standby import PsycopgExecutor
    c = dbs4["aws"]; return PgRatchet(PsycopgExecutor(host=c["sock"], port=c["port"], dbname="hard", user="nexo_fence_keeper"))


def mundo(dbs4, worm):
    reset({"aws": dbs4["aws"], "oci": dbs4["oci"]}); dbs4["aws"]["ex"]("postgres")("UPDATE nexo_fence.seal_ratchet SET seq = 0")
    k = {n: Ed25519PrivateKey.generate() for n in ("aws", "oci", "operator")}; pubs = {n: [pub(v)] for n, v in k.items()}
    auth = {n: Ed25519Auth(n, raw(k[n]), pubs) for n in k}
    ls = InMemoryStore(); ls.verified = True; init_lease(ls, ttl_s=TTL, margin_s=MARGIN)
    log = InMemoryLog(worm=worm); append(log, auth["operator"], "operator", "unsealed", 0)
    return ls, log, auth


class GuardiaIngenua(LogGuard):
    """CONTROL NEGATIVO: solo mira el ÚLTIMO estado firmado (sin trinquete y sin atar el «unsealed» a la época del lease): lo que haría el sello de un solo objeto."""
    def check(self, lease_epoch, lease_head=None):
        names = self.log.names(); last = __import__("app.failover.seal_log", fromlist=["Entry"]).Entry.load(self.log.read(names[-1])) if names else None
        return (bool(last) and last.state == "unsealed" and self.verifier.verify(last.signer, last.canonical(), last.sig), "ingenua")


def aws_node(dbs4, ls, log, auth, guard_cls=LogGuard):
    return Node("aws", dbs4["aws"], ls, lease_kw={"authenticator": auth["aws"], "acquire_guard": guard_cls(log, auth["aws"], keeper_ratchet(dbs4))})


def secuencia(dbs4, worm, latch, ratchet):
    ls, log, auth = mundo(dbs4, worm)
    a1 = aws_node(dbs4, ls, log, auth); a1.start(); assert wait_for(lambda: len(a1.accepted()) >= 3, 15)
    dbs4["_stop"]("aws"); a1.stop()                                                                      # RDS y EC2 detenidas
    g = GatedOci(dbs4, ls, auth); g.node.start()
    assert wait_for(lambda: g.node.lease.is_valid(), 40)
    def sin_base(): raise ConnectionError("RDS detenida")
    assert StrongFence(hard_fence=sin_base, aws_read=lambda: {"rds": "stopped"}).establish()["strong"]
    make_sealer(log, auth["oci"], keeper_ratchet(dbs4) if ratchet else None)(g.node.lease._epoch)       # SELLAR antes de habilitar (el trinquete falla en silencio: la RDS está detenida)
    g.allowed.set(); assert wait_for(lambda: len(g.node.accepted()) >= 3, 15)
    dbs4["_start"]("aws")                                                                                # la RDS REINICIA
    rg = RestartGuard(aws_read=lambda: {"rds": "available"}, hard_fence=(lambda: PgFence(dbs4["aws"]["ex"]("nexo_fence_keeper")).hard_fence("reinicio", wait_s=2.0)) if latch else None,
                      ratchet=(lambda: keeper_ratchet(dbs4).observe(len(log.names()))) if ratchet else None)
    rg.step()
    a2 = aws_node(dbs4, ls, log, auth); a2.start()
    return ls, log, auth, a1, a2, g, rg


def deja_de_renovar_oci(g): g.node.gate._stop.set(); g.node.lease._deadline = None


@pytest.mark.parametrize("worm", [True, False])
def test_con_trinquete_y_guardia_de_reinicio_ningun_ataque_ni_reinicio_devuelve_la_autoridad_a_AWS(dbs4, worm):
    ls, log, auth, a1, a2, g, rg = secuencia(dbs4, worm, latch=False, ratchet=True)                       # SOLO sello+trinquete (sin cerrojo): el sello debe bastar por sí solo
    try:
        assert keeper_ratchet(dbs4).observe(0) == 2, "el trinquete de la base de AWS debía quedar en la entrada 2 (sello)"
        viejo = log.read(_name(1))
        # (1) REPRODUCCIÓN: añadir el «unsealed» antiguo como entrada nueva (nombre nuevo, permitido por un PAR)
        log.objs[_name(3)] = viejo
        # (2) RESTAURAR una versión antigua sobre la entrada 2  /  (3) ELIMINAR el final
        if worm:
            for atacar in (lambda: log.put_blind(_name(2), viejo), lambda: log.delete(_name(2))):
                with pytest.raises(PreconditionFailed): atacar()
        else:
            log.objs.pop(_name(3)); log.delete(_name(2))                                                # sin retención el borrado SÍ se ejecuta…
        # (4) FIRMA INVÁLIDA: el «unsealed» firmado por AWS haciéndose pasar por el operador
        from app.failover.seal_log import Entry
        n = len(log.names()) + 1
        if n == 3:
            e = Entry(3, "unsealed", 99, Entry.load(log.read(log.names()[-1])).digest(), 1.0, "operator"); e.sig = auth["aws"].sign("operator", e.canonical()); log.objs[_name(3)] = e.dump()
        # REINICIO de ambos lados: guardia y nodo de AWS nuevos (sin memoria) y OCI deja de renovar
        a2.stop(); deja_de_renovar_oci(g)
        a2 = aws_node(dbs4, ls, log, auth); a2.start()
        time.sleep(TTL + MARGIN + 3.0)
        ok, why = a2.lease.acquire_guard(None); assert not ok, why                                      # (con borrado sin WORM: «RETROCESO»; con WORM: «SELLADO»; con entradas falsas: inválida)
        assert not a2.accepted() and not a2.lease.is_valid(), "AWS recuperó la autoridad"
        a_aws, o = commit_ts(dbs4["aws"], "aws"), commit_ts(dbs4["oci"], "oci")
        assert a_aws and o and max(a_aws) < min(o)
        if not worm: assert "RETROCESO" in why
    finally:
        a2.stop(); g.node.stop(); a1.stop()


def test_control_negativo_sin_retencion_ni_trinquete_ni_cerrojo_el_borrado_del_sello_devuelve_la_autoridad_a_AWS(dbs4):
    ls, log, auth, a1, a2, g, rg = secuencia(dbs4, worm=False, latch=False, ratchet=False)
    try:
        log.delete(_name(2))                                                                              # el atacante con permiso de borrado revierte al «unsealed» inicial
        a2.stop(); a2 = aws_node(dbs4, ls, log, auth, guard_cls=GuardiaIngenua); deja_de_renovar_oci(g); a2.start()   # AWS reinicia (sin memoria) y OCI deja de renovar
        assert wait_for(lambda: len(a2.accepted()) >= 1, 40), "(control) sin las tres protecciones AWS debía recuperar la autoridad: si no, la prueba no discrimina"
    finally:
        a2.stop(); g.node.stop(); a1.stop()


def test_failback_manual_firma_del_operador_y_la_entrada_nueva_levanta_el_sello_solo_para_esa_epoca(dbs4):
    ls, log, auth, a1, a2, g, rg = secuencia(dbs4, worm=True, latch=True, ratchet=True)
    try:
        time.sleep(TTL + 1.0); assert not a2.accepted()
        epoca = g.node.lease._epoch; g.node.stop(); a2.stop()
        append(log, auth["operator"], "operator", "unsealed", epoca)                                       # FAILBACK MANUAL: entrada nueva firmada por el operador (clave fuera de los nodos)
        PgFence(dbs4["aws"]["ex"]("nexo_fence_keeper")).release_latch("LIBERAR CERROJO DEL VALLADO")
        a3 = aws_node(dbs4, ls, log, auth); a3.start()
        try: assert wait_for(lambda: len(a3.accepted()) >= 2, 40), "con el sello levantado (firma del operador) y el cerrojo liberado AWS debía poder volver"
        finally: a3.stop()
    finally:
        a1.stop(); a2.stop(); g.node.stop()
