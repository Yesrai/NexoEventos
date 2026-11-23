"""Antirretroceso del sello: un atacante con permiso de SOBRESCRITURA o de borrado no puede devolver un «unsealed» antiguo. Control negativo: SIN retención y SIN trinquete, el retroceso sí funciona."""
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.failover.lease import Ed25519Auth
from app.failover.seal_log import Entry, InMemoryLog, LogGuard, MemRatchet, _name, append
from app.failover.store import PreconditionFailed

raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


@pytest.fixture
def auth():
    k = {n: Ed25519PrivateKey.generate() for n in ("aws", "oci", "operator")}; pubs = {n: [pub(v)] for n, v in k.items()}
    return {n: Ed25519Auth(n, raw(k[n]), pubs) for n in k}


def historia(auth, worm=True):
    log = InMemoryLog(worm=worm)
    append(log, auth["operator"], "operator", "unsealed", 0)      # 1: despliegue
    append(log, auth["oci"], "oci", "sealed", 3)                  # 2: promoción de OCI (época 3)
    return log


def test_flujo_normal_sellado_y_failback_manual(auth):
    log = historia(auth); g = LogGuard(log, auth["aws"], MemRatchet())
    ok, why = g(None); assert not ok and "SELLADO" in why
    append(log, auth["operator"], "operator", "unsealed", 3)
    assert g(3)[0] and g(4)[0]                                      # tras el failback el lease sigue creciendo: el titular legítimo NO queda bloqueado (la cadena ya impide reutilizar un «unsealed» viejo)
    append(log, auth["oci"], "oci", "sealed", 9)
    assert not g(9)[0]                                              # una promoción posterior vuelve a sellar


def test_un_PAR_de_sobrescritura_no_puede_reutilizar_ni_reemplazar_entradas_con_retencion(auth):
    log = historia(auth); viejo = log.read(_name(1))
    with pytest.raises(PreconditionFailed): log.put_blind(_name(2), viejo)        # reemplazar la entrada «sealed» por el «unsealed» antiguo
    with pytest.raises(PreconditionFailed): log.delete(_name(2))                    # borrar el sello
    assert not LogGuard(log, auth["aws"], MemRatchet())(None)[0]                   # sigue sellado


def test_el_atacante_puede_anadir_nombres_nuevos_pero_sin_firma_ni_cadena_validas_se_rechaza(auth):
    log = historia(auth); g = LogGuard(log, auth["aws"], MemRatchet())
    viejo = Entry.load(log.read(_name(1)))
    log.put_blind(_name(3), viejo.dump())                                           # añade el «unsealed» antiguo como entrada 3 (nombre nuevo permitido)
    ok, why = g(None); assert not ok and "inválida" in why                           # seq/prev_hash no encajan: la cadena lo delata
    assert g.tamper_events >= 1
    log2 = historia(auth)
    falsa = Entry(3, "unsealed", 99, Entry.load(log2.read(_name(2))).digest(), 1.0, "operator"); falsa.sig = auth["aws"].sign("operator", falsa.canonical())   # firma de AWS haciéndose pasar por el operador
    log2.put_blind(_name(3), falsa.dump()); assert not LogGuard(log2, auth["aws"], MemRatchet())(None)[0]


def test_borrar_el_final_sin_retencion_lo_detecta_el_trinquete_de_la_base(auth):
    log = historia(auth, worm=False); rat = MemRatchet(); g = LogGuard(log, auth["aws"], rat)
    assert not g(None)[0] and rat.v == 2                                            # AWS vio el sello (entrada 2) y lo anotó en SU base
    log.delete(_name(2))                                                            # el atacante con permiso de borrado revierte al «unsealed» anterior
    ok, why = g(None); assert not ok and "RETROCESO" in why
    # con un consumidor nuevo (sin trinquete) y sin retención el retroceso NO se detecta: por eso el automático exige WORM en OCI real
    assert LogGuard(log, auth["aws"], MemRatchet())(None)[0] is True


def test_control_negativo_sin_retencion_y_sin_trinquete_el_unsealed_antiguo_devuelve_la_autoridad(auth):
    log = historia(auth, worm=False); viejo = log.read(_name(1))
    log.objs[_name(2)] = viejo                                                      # sobrescritura del objeto 2 con el «unsealed» antiguo (firma válida)
    ok, why = LogGuard(log, auth["aws"], MemRatchet())(None)
    assert not ok                                                                    # la CADENA lo rechaza (seq 1 en la posición 2)…
    log.objs.pop(_name(2))                                                           # …pero quitándolo del todo, un consumidor sin trinquete ve «unsealed» y autoriza
    assert LogGuard(log, auth["aws"], MemRatchet())(None)[0], "(control) sin WORM ni trinquete el retroceso por borrado SÍ funciona"


def test_cadena_rota_hueco_o_fallo_de_almacen_o_trinquete_bloquean(auth):
    log = historia(auth); del log.objs[_name(1)]
    assert not LogGuard(log, auth["aws"], MemRatchet())(None)[0]                    # falta la entrada 1
    log = historia(auth); log.down = True; assert not LogGuard(log, auth["aws"], MemRatchet())(None)[0]
    log = historia(auth); r = MemRatchet(); r.down = True; assert not LogGuard(log, auth["aws"], r)(None)[0]
    assert not LogGuard(InMemoryLog(), auth["aws"], MemRatchet())(None)[0]          # vacío
