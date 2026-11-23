"""Sello de promoción: falla cerrado, firmas, anti-reutilización y guardia del lease."""
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.failover.lease import Ed25519Auth, LeaseClient, LeaseConfig, init_lease
from app.failover.seal import SealGuard, SealRecord, seal, unseal
from app.failover.store import InMemoryStore, StoreUnavailable

raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


class Clock:
    def __init__(self, t=1000.0): self.t = t
    def __call__(self): return self.t
    def advance(self, s): self.t += s


@pytest.fixture
def keys():
    k = {n: Ed25519PrivateKey.generate() for n in ("aws", "oci", "operator", "intruso")}
    pubs = {n: [pub(v)] for n, v in k.items() if n != "intruso"}
    return {"aws": Ed25519Auth("aws", raw(k["aws"]), pubs), "oci": Ed25519Auth("oci", raw(k["oci"]), pubs), "operator": Ed25519Auth("operator", raw(k["operator"]), pubs),
            "intruso": Ed25519Auth("intruso", raw(k["intruso"]), pubs)}


def store():
    s = InMemoryStore(); s.verified = True; return s


def test_estados_y_fallo_cerrado(keys):
    st = store(); g = SealGuard(st, keys["aws"], cache_s=0)
    assert not g(None)[0] and "sin registro" in g(None)[1]                                   # ausente
    unseal(st, keys["operator"], 0); assert g(None)[0]                                       # inicializado (unsealed, época 0)
    seal(st, keys["oci"], 3); ok, why = g(None); assert not ok and "SELLADO" in why
    st2 = store(); st2.create(b"basura"); assert not SealGuard(st2, keys["aws"], cache_s=0)(None)[0]
    class Caido(InMemoryStore):
        def read(self): raise StoreUnavailable("caído")
    assert not SealGuard(Caido(), keys["aws"], cache_s=0)(None)[0]                           # almacén inaccesible


def test_firmas_nadie_falsifica_el_sello_ni_el_levantamiento(keys):
    st = store(); unseal(st, keys["operator"], 0); g = SealGuard(st, keys["aws"], cache_s=0)
    seal(st, keys["oci"], 2); assert not g(None)[0]
    # AWS (o un intruso) intenta escribir «unsealed» firmado por sí mismo / por el operador falso
    for falso in (keys["aws"], keys["intruso"]):
        rv = st.read(); rec = SealRecord("unsealed", 99, SealRecord.load(rv.data).seq + 1, 0.0, "operator", falso.sign("operator", b"x"))
        rec.sig = falso.sign("operator", rec.canonical()); st.replace(rv.etag, rec.dump())
        assert not g(None)[0] and "firma" in g(None)[1], "un levantamiento con firma que no es del operador debe rechazarse"
        seal(st, keys["oci"], 2)                                                              # OCI lo vuelve a sellar (secuencia creciente)


def test_levantar_el_sello_solo_vale_para_la_epoca_actual_y_un_unsealed_viejo_reutilizado_no(keys):
    st = store(); g = SealGuard(st, keys["aws"], cache_s=0)
    unseal(st, keys["operator"], 0); viejo = st.read().data                                  # «unsealed» de la instalación (época 0)
    seal(st, keys["oci"], 4)                                                                  # promoción en la época 4
    with st._lock:
        st._gen += 1; st._data = viejo                                                        # el atacante restaura el «unsealed» antiguo, que SÍ tiene firma válida
    assert not g(4)[0] and "reutilizado" in g(4)[1], "un unsealed anterior a la última promoción no levanta el sello"
    unseal(st, keys["operator"], 4)                                                           # failback MANUAL del operador para la época 4
    assert g(4)[0]


def test_la_guardia_impide_adquirir_y_renovar_el_lease_y_el_failback_manual_lo_devuelve(keys):
    clk = Clock(); ls = store(); init_lease(ls, ttl_s=10, margin_s=2); sst = store(); unseal(sst, keys["operator"], 0)
    mk = lambda name, guard: LeaseClient(ls, LeaseConfig(ttl_s=10, margin_s=2), holder_id=name, mono=clk, authenticator=keys[name], acquire_guard=guard)
    aws = mk("aws", SealGuard(sst, keys["aws"], cache_s=0))
    aws.acquire(); clk.advance(12.1); assert aws.acquire().ok and aws.is_valid()              # sin sello: adquiere (observando ttl+margen)
    seal(sst, keys["oci"], aws._epoch + 1)                                                    # OCI promueve y sella
    r = aws.renew(); assert not r.ok and not aws.is_valid() and "sellado" in r.reason          # renovar también: se pierde
    clk.advance(100)
    for _ in range(3):
        r = aws.acquire(); clk.advance(15); assert not r.ok and "sellado" in r.reason          # ni tras caducar nadie: no adquiere
    unseal(sst, keys["operator"], 50)                                                         # failback MANUAL del operador (clave que no está en ningún nodo)
    aws.acquire(); clk.advance(15); r = aws.acquire(); assert r.ok and aws.is_valid(), r.reason


def test_un_guardia_que_lanza_excepcion_no_autoriza(keys):
    clk = Clock(); ls = store(); init_lease(ls, ttl_s=10, margin_s=2)
    def malo(epoch): raise RuntimeError("fallo")
    c = LeaseClient(ls, LeaseConfig(ttl_s=10, margin_s=2), holder_id="aws", mono=clk, authenticator=keys["aws"], acquire_guard=malo)
    assert not c.acquire().ok
