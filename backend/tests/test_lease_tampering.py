"""Lease MANIPULADO: un tercero (o un controlador defectuoso) con la URL de lectura/escritura del almacén sobrescribe el objeto SIN If-Match. Qué se exige:
la manipulación solo puede hacer que un controlador PIERDA el lease (falla seguro), nunca que dos controladores crean tenerlo a la vez. Reloj simulado (determinista)."""
import json

import pytest

from app.failover.lease import LeaseClient, LeaseConfig, Record, init_lease
from app.failover.store import InMemoryStore

TTL, MARGIN = 10.0, 2.0


class Clock:
    def __init__(self, t=1000.0): self.t = t
    def __call__(self): return self.t
    def advance(self, s): self.t += s


def world(keys=None):
    store = InMemoryStore(); store.verified = True; init_lease(store, ttl_s=TTL, margin_s=MARGIN)
    clk = Clock()
    mk = lambda name: LeaseClient(store, LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id=name, mono=clk, **({"auth_keys": keys} if keys else {}))
    return store, clk, mk("aws"), mk("oci")


def blind_write(store, **fields):
    """Sobrescritura ciega SIN If-Match (lo que permite un PAR de lectura/escritura): cambia el objeto y el servidor le asigna un ETag NUEVO."""
    base = dict(v=1, holder=None, epoch=0, seq=0, ttl_s=TTL, margin_s=MARGIN, released=False); base.update(fields)
    rv = store.read()
    with store._lock:
        store._gen += 1; store._data = json.dumps(base).encode()
    return store.read().etag


def acquire_after_observing(c, clk, secs=None):
    r = c.acquire()
    clk.advance(secs if secs is not None else TTL + MARGIN + 0.1)
    return c.acquire()


def never_both(a, b):
    assert not (a.is_valid() and b.is_valid()), "DOS controladores con lease válido a la vez"


def test_registro_falsificado_con_el_titular_igual_al_atacado_no_concede_el_lease_al_instante():
    store, clk, aws, oci = world()
    assert acquire_after_observing(aws, clk).ok and aws.is_valid()
    blind_write(store, holder="oci", epoch=aws._epoch, seq=999)                          # «yo soy el titular», sin haberlo tomado
    r = oci.acquire()
    assert not r.ok and not oci.is_valid(), r                                           # debe OBSERVAR ttl+margen, no adoptarlo
    never_both(aws, oci)


def test_liberacion_falsificada_no_permite_la_toma_inmediata():
    store, clk, aws, oci = world()
    assert acquire_after_observing(aws, clk).ok
    blind_write(store, holder=None, epoch=aws._epoch, seq=999, released=True)         # «el titular se fue»
    r = oci.acquire()
    assert not r.ok and not oci.is_valid(), r
    never_both(aws, oci)


def test_ttl_y_margen_falsificados_a_la_baja_no_acortan_la_espera():
    store, clk, aws, oci = world()
    assert acquire_after_observing(aws, clk).ok
    blind_write(store, holder="aws", epoch=aws._epoch, seq=999, ttl_s=0.01, margin_s=0.0)
    oci.acquire(); clk.advance(3.0)                                                       # 1 s ≪ ttl+margen locales
    assert not oci.acquire().ok and not oci.is_valid()


def test_reutilizar_un_registro_antiguo_no_devuelve_el_lease_al_escritor_anterior():
    store, clk, aws, oci = world()
    assert acquire_after_observing(aws, clk).ok
    viejo = store.read().data
    clk.advance(TTL + MARGIN + 1); assert not aws.is_valid()                              # el anterior dejó de renovar (partición)
    assert acquire_after_observing(oci, clk).ok and oci.is_valid()
    with store._lock:                                                                     # el atacante restaura el registro viejo de AWS (ETag nuevo)
        store._gen += 1; store._data = viejo
    for _ in range(3):
        aws.renew()
    assert not aws.is_valid(), "el escritor anterior recuperó el lease con un registro reutilizado"
    never_both(aws, oci)


def test_epoca_falsificada_hacia_atras_no_hace_retroceder_a_quien_toma():
    store, clk, aws, oci = world()
    assert acquire_after_observing(aws, clk).ok and acquire_after_observing(oci, clk, TTL + MARGIN + 0.1) is not None
    mayor = max(aws._epoch or 0, oci._epoch or 0, 5)
    oci._hwm = max(oci._hwm, mayor)
    blind_write(store, holder="x", epoch=1, seq=1)
    clk.advance(0.1); oci.acquire(); clk.advance(TTL + MARGIN + 0.5)
    r = oci.acquire()
    assert (not r.ok) or oci._epoch > mayor, "se concedió una época menor que la ya vista"


def test_etag_no_se_puede_falsificar_el_contenido_identico_recibe_otro_etag_y_el_cas_de_quien_renueva_falla():
    store, clk, aws, oci = world()
    assert acquire_after_observing(aws, clk).ok
    e_antes = store.read().etag; contenido = store.read().data
    with store._lock:
        store._gen += 1; store._data = contenido                                         # mismo contenido, escrito a ciegas
    assert store.read().etag != e_antes
    assert aws._etag != store.read().etag                                                # el CAS de quien renueva va contra SU ETag: ya no coincide
    aws.renew(); assert not aws.is_valid()                                               # y pierde el lease (falla seguro)


def test_controlador_defectuoso_con_cas_incorrectos_no_altera_el_lease_ni_crea_dos_titulares():
    store, clk, aws, oci = world()
    assert acquire_after_observing(aws, clk).ok
    for basura in ("etag-inventado", "", "*", aws._etag + "x"):
        with pytest.raises(Exception):
            store.replace(basura, b"{}")
    assert aws.renew().ok and aws.is_valid()
    never_both(aws, oci)


def test_con_firmas_una_liberacion_autentica_si_se_honra_y_la_falsificada_no():
    keys = {"aws": b"k-aws" * 4, "oci": b"k-oci" * 4}
    store, clk, aws, oci = world(keys)
    assert acquire_after_observing(aws, clk).ok
    blind_write(store, holder=None, epoch=aws._epoch, seq=999, released=True)         # sin firma: se ignora el atajo
    assert not oci.acquire().ok
    store2, clk2, aws2, oci2 = world(keys)
    assert acquire_after_observing(aws2, clk2).ok
    assert not oci2.acquire().ok                                                         # OCI vigila al titular
    assert aws2.release().ok
    r = oci2.acquire()
    assert r.ok and oci2.is_valid(), r                                                   # liberación AUTÉNTICA (firmada por quien tenía el lease): toma inmediata


def test_reinicio_del_titular_adopta_su_lease_solo_si_el_etag_es_el_de_su_ultima_escritura(tmp_path):
    sp = str(tmp_path / "aws.state")
    store, clk, _, oci = world()
    mk = lambda: LeaseClient(store, LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id="aws", mono=clk, state_path=sp)
    a = mk(); a.acquire(); clk.advance(TTL + MARGIN + 0.1); assert a.acquire().ok
    assert oct(__import__("os").stat(sp).st_mode & 0o777) == "0o600"
    reiniciado = mk()                                                                       # proceso nuevo, misma identidad, sin memoria
    assert reiniciado.acquire().ok and reiniciado._epoch == a._epoch                        # nadie escribió desde entonces: adopta (ETag idéntico)
    # ahora OCI toma y el atacante restaura el último registro de AWS (contenido idéntico, ETag NUEVO)
    ultimo = store.read().data; clk.advance(TTL + MARGIN + 1); assert acquire_after_observing(oci, clk).ok
    with store._lock:
        store._gen += 1; store._data = ultimo
    otro_reinicio = mk(); r = otro_reinicio.acquire()
    assert not r.ok and not otro_reinicio.is_valid(), "un reinicio adoptó un registro reutilizado"
    never_both(otro_reinicio, oci)


def test_liberacion_autentica_pero_antigua_reutilizada_no_da_atajo_a_quien_no_la_vio_venir():
    keys = {"aws": b"k-aws" * 4, "oci": b"k-oci" * 4}
    store, clk, aws, oci = world(keys)
    assert acquire_after_observing(aws, clk).ok
    oci.acquire(); assert aws.release().ok                                              # liberación auténtica, vista por OCI
    antigua = store.read().data
    assert oci.acquire().ok and oci.is_valid()                                          # OCI toma (época+1)
    with store._lock:
        store._gen += 1; store._data = antigua                                           # el atacante reutiliza la liberación firmada de AWS
    reiniciado = LeaseClient(store, LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id="aws", mono=clk, auth_keys=keys)   # AWS sin memoria
    assert not reiniciado.acquire().ok and not reiniciado.is_valid(), "atajo de liberación con un registro antiguo"
    never_both(reiniciado, oci)


@pytest.mark.parametrize("contenido", [None, "", "no es json", "[]", '{"etag": 5, "holder": "aws"}', '{"etag": "x", "holder": "otro"}', '{"etag": ""}', b"\xff\xfe"])
def test_estado_local_ausente_o_corrupto_nunca_adopta_ni_rompe(tmp_path, contenido):
    sp = tmp_path / "aws.state"
    store, clk, _, _ = world()
    mk = lambda: LeaseClient(store, LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id="aws", mono=clk, state_path=str(sp))
    a = mk(); a.acquire(); clk.advance(TTL + MARGIN + 0.1); assert a.acquire().ok
    if contenido is None: sp.unlink()
    else: sp.write_bytes(contenido if isinstance(contenido, bytes) else contenido.encode())
    r = mk().acquire()
    assert not r.ok, "adoptó sin un ETag propio verificable"                              # debe observar ttl+margen
    assert not mk().is_valid()


def test_ed25519_cada_nodo_guarda_solo_su_privada_y_un_nodo_no_puede_firmar_como_otro():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from app.failover.lease import Ed25519Auth
    raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ka, ko = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    store = InMemoryStore(); store.verified = True; init_lease(store, ttl_s=TTL, margin_s=MARGIN); clk = Clock()
    A = Ed25519Auth("aws", raw(ka), {"oci": [pub(ko)]}); O = Ed25519Auth("oci", raw(ko), {"aws": [pub(ka)]})
    aws = LeaseClient(store, LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id="aws", mono=clk, authenticator=A)
    oci = LeaseClient(store, LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id="oci", mono=clk, authenticator=O)
    assert acquire_after_observing(aws, clk).ok
    assert not oci.acquire().ok; assert aws.release().ok and oci.acquire().ok              # liberación firmada con la privada de AWS, verificada con su pública
    assert not A.can_sign("oci") and not O.can_sign("aws")                               # ningún nodo puede firmar como el otro (no tiene su privada)
    blind_write(store, holder=None, epoch=oci._epoch, seq=10**6, released=True)
    assert not LeaseClient(store, LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id="aws", mono=clk, authenticator=A).acquire().ok     # liberación sin firma: sin atajo
