"""Consumidor que arranca SIN trinquete previo: una firma válida NO prueba que el registro esté completo ni actualizado. Defensas: cadena desde la génesis (huecos y sustituciones), ANCLA DE FRESCURA (cabeza del sello publicada
en el registro firmado del lease) e INICIALIZACIÓN HUMANA del trinquete. Control negativo: sin ancla ni inicialización, un truncamiento del final con todas las firmas válidas pasa inadvertido."""
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.failover.lease import Ed25519Auth, LeaseClient, LeaseConfig, init_lease
from app.failover.seal_log import InMemoryLog, LogGuard, MemRatchet, _name, append, init_ratchet
from app.failover.store import InMemoryStore, StoreError

raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def advance(self, s): self.t += s


@pytest.fixture
def auth():
    k = {n: Ed25519PrivateKey.generate() for n in ("aws", "oci", "operator")}; pubs = {n: [pub(v)] for n, v in k.items()}
    return {n: Ed25519Auth(n, raw(k[n]), pubs) for n in k}


def historia(auth, worm=False):
    log = InMemoryLog(worm=worm); append(log, auth["operator"], "operator", "unsealed", 0); append(log, auth["oci"], "oci", "sealed", 2); return log


def test_control_negativo_sin_ancla_ni_inicializacion_el_truncamiento_con_firmas_validas_pasa_inadvertido(auth):
    log = historia(auth); log.delete(_name(2))                                                            # el atacante borra el final (sin retención)
    ok, why = LogGuard(log, auth["aws"], MemRatchet())(None); assert ok, "(control) un consumidor nuevo sin ancla debía creer el registro truncado: si no, la prueba no discrimina"


def test_un_consumidor_nuevo_se_bloquea_hasta_que_una_persona_inicializa_el_trinquete_con_una_cabeza_verificada(auth):
    log = historia(auth); rat = MemRatchet(); g = LogGuard(log, auth["aws"], rat, require_init=True)
    ok, why = g(None); assert not ok and "SIN inicializar" in why
    with pytest.raises(StoreError): init_ratchet(g, 7)                                                    # la persona verificó otra cabeza: no se inicializa
    assert init_ratchet(g, 2) == 2
    ok, why = g(None); assert not ok and "SELLADO" in why                                                 # ahora sí evalúa (y está sellado)
    log.delete(_name(2)); ok, why = g(None); assert not ok and "RETROCESO" in why                         # y el truncamiento posterior lo detecta el trinquete


def test_la_cabeza_anclada_en_el_lease_detecta_truncamiento_y_historias_distintas_aunque_las_firmas_sean_validas(auth):
    log = historia(auth); head = LogGuard(log, auth["aws"], MemRatchet()).head(); assert head[0] == 2
    g = LogGuard(log, auth["aws"], MemRatchet())
    assert not g(None, head)[0] and "SELLADO" in g(None, head)[1]                                          # el registro coincide con la cabeza: sigue sellado
    log.delete(_name(2)); ok, why = LogGuard(log, auth["aws"], MemRatchet())(None, head); assert not ok and "TRUNCAMIENTO" in why       # consumidor SIN trinquete previo
    # historia DISTINTA: misma longitud pero otra entrada 2 firmada válidamente (p. ej. un «unsealed» del operador en lugar del sello)
    log2 = historia(auth); log2.delete(_name(2)); append(log2, auth["operator"], "operator", "unsealed", 2)
    ok, why = LogGuard(log2, auth["aws"], MemRatchet())(None, head); assert not ok and "no coincide con la cabeza" in why
    log3 = historia(auth); log3.objs[_name(2)] = b"x"
    assert not LogGuard(log3, auth["aws"], MemRatchet())(None, head)[0]


def test_require_head_sin_cabeza_en_el_lease_no_se_confia_en_un_registro_con_entradas(auth):
    log = historia(auth); ok, why = LogGuard(log, auth["aws"], MemRatchet(), require_head=True)(None, None); assert not ok and "sin ancla" in why
    only_genesis = InMemoryLog(); append(only_genesis, auth["operator"], "operator", "unsealed", 0)
    assert LogGuard(only_genesis, auth["aws"], MemRatchet(), require_head=True)(0, None)[0]               # génesis sola: aún no hubo promoción, nada que anclar


def test_huecos_y_sustituciones_en_la_cadena_se_rechazan_sin_trinquete_ni_cabeza(auth):
    log = InMemoryLog(); [append(log, auth["operator"], "operator", "unsealed", i) for i in range(3)]
    del log.objs[_name(2)]; assert not LogGuard(log, auth["aws"], MemRatchet())(None)[0]                  # hueco en medio
    log = historia(auth); viejo = log.read(_name(1)); log.objs[_name(2)] = viejo; assert not LogGuard(log, auth["aws"], MemRatchet())(None)[0]   # restaurar una versión antigua sobre la 2


def test_integracion_con_el_lease_oci_publica_la_cabeza_firmada_y_AWS_la_exige_y_alterarla_rompe_la_firma(auth):
    clk = Clock(); ls = InMemoryStore(); ls.verified = True; init_lease(ls, ttl_s=10, margin_s=2); log = historia(auth)
    oci = LeaseClient(ls, LeaseConfig(ttl_s=10, margin_s=2), holder_id="oci", mono=clk, authenticator=auth["oci"], head_provider=lambda: LogGuard(log, auth["oci"], MemRatchet()).head())
    oci.acquire(); clk.advance(12.1); assert oci.acquire().ok
    import json
    rec = json.loads(ls.read().data); assert rec["seal_head"][0] == 2 and rec["sig"]                      # la cabeza viaja DENTRO del registro firmado
    aws = LeaseClient(ls, LeaseConfig(ttl_s=10, margin_s=2), holder_id="aws", mono=clk, authenticator=auth["aws"], acquire_guard=LogGuard(log, auth["aws"], MemRatchet()))
    r = aws.acquire(); assert not r.ok and "sellado" in r.reason                                           # sellado
    log.delete(_name(2))                                                                                    # el atacante trunca; AWS (nuevo, sin trinquete) lee la cabeza del lease y lo detecta
    aws2 = LeaseClient(ls, LeaseConfig(ttl_s=10, margin_s=2), holder_id="aws", mono=clk, authenticator=auth["aws"], acquire_guard=LogGuard(log, auth["aws"], MemRatchet()))
    r = aws2.acquire(); assert not r.ok and "TRUNCAMIENTO" in r.reason
    # alterar la cabeza en el registro del lease invalida la firma (el registro deja de ser auténtico)
    from app.failover.lease import Record
    d = json.loads(ls.read().data); d["seal_head"] = [1, "0" * 64]; bad = Record.load(json.dumps(d).encode())
    assert not aws2._authentic(bad)


class _Obj:
    def __init__(self, n): self.name = n


class FakeClient:
    """Imita el ObjectStorageClient: paginación del listado, 404, 412 y 403 (permiso)."""
    class Err(Exception):
        def __init__(self, status): self.status = status
    def __init__(self, can_create=True): self.o, self.can_create, self.calls = {}, can_create, []
    def list_objects(self, ns, b, prefix=None, start=None, fields=None):
        self.calls.append("list"); names = sorted(k for k in self.o if k.startswith(prefix)); i = 0 if not start else names.index(start)
        page = names[i:i + 2]; nxt = names[i + 2] if len(names) > i + 2 else None
        class R: data = type("D", (), {"objects": [_Obj(n) for n in page], "next_start_with": nxt})
        return R
    def get_object(self, ns, b, name):
        self.calls.append("get")
        if name not in self.o: raise self.Err(404)
        return type("R", (), {"data": type("D", (), {"content": self.o[name]})})
    def put_object(self, ns, b, name, data, if_none_match=None):
        self.calls.append("put")
        if not self.can_create: raise self.Err(404)
        if name in self.o: raise self.Err(412)
        self.o[name] = data


def test_cliente_sdk_solo_usa_listar_leer_y_crear_con_if_none_match_y_pagina(auth):
    from app.failover.seal_log import OciSdkLogStore
    from app.failover.store import PreconditionFailed
    c = FakeClient(); log = OciSdkLogStore(c, "ns", "nexo-seal-lab-x")
    append(log, auth["operator"], "operator", "unsealed", 0); append(log, auth["oci"], "oci", "sealed", 1); append(log, auth["operator"], "operator", "unsealed", 1)
    assert len(log.names()) == 3 and set(c.calls) == {"list", "get", "put"}                              # NUNCA delete ni sobrescritura: solo esas tres operaciones
    with pytest.raises(PreconditionFailed): log.create(_name(1), b"x")
    with pytest.raises(StoreError): OciSdkLogStore(FakeClient(can_create=False), "ns", "b").create(_name(1), b"x")        # sin permiso de creación
    ok, why = LogGuard(log, auth["aws"], MemRatchet())(1); assert ok, why                                 # la cadena de 3 entradas (paginada) verifica


def test_limite_documentado_retroceso_COHERENTE_del_log_y_de_la_cabeza_no_lo_ve_un_consumidor_nuevo_sin_WORM_ni_inicializacion(auth):
    """Un atacante que puede revertir el log (borrar) Y el registro del lease (sobrescribir con una versión anterior legítima y firmada) deja una historia coherente más antigua: la cabeza anclada ya no lo delata.
    Lo que sí lo detiene: (a) la retención WORM del log (no se puede borrar), (b) el trinquete de un consumidor que YA vio el sello, (c) la inicialización humana del trinquete de un consumidor nuevo con una cabeza verificada
    FUERA de banda. El ancla de frescura del lease NO es un ancla externa: vive en el mismo dominio de confianza (identidades con permiso de sobrescribir el lease)."""
    log = historia(auth); cabeza_vieja = [1, LogGuard(InMemoryLog(), auth["aws"], MemRatchet()).head() or "x"]
    log.delete(_name(2))                                                                                    # el log vuelve a su estado previo a la promoción
    head1 = LogGuard(log, auth["aws"], MemRatchet()).head()                                                 # …y el lease se revierte a un registro firmado que anunciaba esa cabeza (seq 1)
    ok, why = LogGuard(log, auth["aws"], MemRatchet())(None, head1); assert ok, "(límite) un consumidor nuevo sin WORM ni inicialización cree la historia coherente más antigua"
    # (b) un consumidor que ya vio el sello (trinquete = 2) SÍ lo detecta
    r = MemRatchet(); r.observe(2); ok, why = LogGuard(log, auth["aws"], r)(None, head1); assert not ok and "RETROCESO" in why
    # (c) un consumidor nuevo con inicialización exigida NO cree nada hasta que una persona fije la cabeza verificada (=2)
    ok, why = LogGuard(log, auth["aws"], MemRatchet(), require_init=True)(None, head1); assert not ok and "SIN inicializar" in why
    with pytest.raises(StoreError): init_ratchet(LogGuard(log, auth["aws"], MemRatchet(), require_init=True), 2)     # la persona verificó 2 entradas y el registro tiene 1: no se inicializa
    # (a) con WORM el borrado inicial no habría ocurrido
    w = historia(auth, worm=True)
    with pytest.raises(Exception): w.delete(_name(2))


def test_regresion_el_titular_legitimo_con_la_genesis_unsealed_no_se_bloquea_al_renovar_con_epoca_creciente(auth):
    """DEFECTO que existía: la guardia comparaba la época del lease con la del «unsealed» de génesis (0), así que el primer lease legítimo (época 1) se bloqueaba en su primera renovación."""
    clk = Clock(); ls = InMemoryStore(); ls.verified = True; init_lease(ls, ttl_s=10, margin_s=2)
    log = InMemoryLog(); append(log, auth["operator"], "operator", "unsealed", 0)
    aws = LeaseClient(ls, LeaseConfig(ttl_s=10, margin_s=2), holder_id="aws", mono=clk, authenticator=auth["aws"], acquire_guard=LogGuard(log, auth["aws"], MemRatchet()))
    aws.acquire(); clk.advance(12.1); assert aws.acquire().ok and aws._epoch == 1
    for _ in range(5):
        clk.advance(3); r = aws.renew(); assert r.ok and aws.is_valid(), r.reason                           # renovaciones con época 1 > 0 de la génesis
