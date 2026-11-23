"""ATAQUE DE ROLLBACK SIMULTÁNEO: el atacante restaura el lease y el registro del sello a estados ANTIGUOS, con firmas válidas y coherentes entre sí, y arranca una instancia AWS nueva (sin trinquete ni historial).
Se reproduce contra la implementación VULNERABLE (guardia del registro + ancla del lease, sin testigo) y se comprueba que la versión CORREGIDA (testigo de frescura independiente) lo rechaza en todos los casos."""
import json
import shutil

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.failover.lease import Ed25519Auth, LeaseClient, LeaseConfig, init_lease
from app.failover.seal_log import InMemoryLog, LogGuard, MemRatchet, _name, append, make_sealer
from app.failover.store import InMemoryStore, StoreError, StoreUnavailable
from app.failover.witness import CompositeGuard, LocalWitnessClient, Witness, WitnessGuard, make_report

raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
TTL, MARGIN = 10, 2


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def advance(self, s): self.t += s


class W:
    """Mundo: lease + registro de sello + testigo (almacén APARTE), con la historia legítima ya ocurrida y las copias ANTIGUAS que el atacante restaurará."""
    def __init__(self, tmp_path):
        ks = {n: Ed25519PrivateKey.generate() for n in ("aws", "oci", "operator", "witness")}; self.pubs = {n: [pub(v)] for n, v in ks.items()}
        self.auth = {n: Ed25519Auth(n, raw(ks[n]), self.pubs) for n in ks}
        self.clk = Clock(); self.wall = [5000.0]
        self.ls = InMemoryStore(); self.ls.verified = True; init_lease(self.ls, ttl_s=TTL, margin_s=MARGIN); self.log = InMemoryLog(worm=False)
        self.wpath = tmp_path / "testigo.jsonl"; self.witness = Witness(self.wpath, self.auth["witness"], self.auth["witness"], now=lambda: self.wall[0]); self.wc = LocalWitnessClient(self.witness)
        g = append(self.log, self.auth["operator"], "operator", "unsealed", 0)
        self.rep(*make_report(self.auth["operator"], "operator", kind="genesis", lease_epoch=0, seal_seq=1, seal_digest=g.digest()))
        # historia legítima: AWS época 1 → (copias antiguas) → OCI época 2 y sello
        self.aws = self.node("aws", report=True); self.aws.acquire(); self.clk.advance(TTL + MARGIN + 0.1); assert self.aws.acquire().ok and self.aws._epoch == 1
        self.old_lease = self.ls.read().data; self.old_log = dict(self.log.objs)                              # <- lo que el atacante guardó
        self.clk.advance(TTL + MARGIN + 1)
        self.oci = self.node("oci", report=True); self.oci.acquire(); self.clk.advance(TTL + MARGIN + 0.1); assert self.oci.acquire().ok and self.oci._epoch == 2
        make_sealer(self.log, self.auth["oci"], witness_report=lambda seq, dig, ep: self.rep(*make_report(self.auth["oci"], "oci", kind="seal_head", seal_seq=seq, seal_digest=dig)))(2)
        assert self.witness.wm["lease_epoch"] == 2 and self.witness.wm["seal_seq"] == 2

    def rep(self, who, payload, sig): ok, why = self.witness.report(who, payload, sig); assert ok, why

    def node(self, name, report=False, guard=None, **kw):
        rep = (lambda ep, n=name: self.witness.report(*make_report(self.auth[n], n, kind="lease_epoch", lease_epoch=ep))) if report else None
        return LeaseClient(self.ls, LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id=kw.pop("holder", name), mono=self.clk, authenticator=self.auth[name if name in self.auth else "aws"], acquire_guard=guard, epoch_reporter=rep, **kw)

    def ataque(self):
        """Restaura lease Y registro a un estado ANTIGUO, coherente y con firmas válidas (nuevo ETag para el lease)."""
        with self.ls._lock: self.ls._gen += 1; self.ls._data = self.old_lease
        self.log.objs = dict(self.old_log)

    def guard_vulnerable(self): return LogGuard(self.log, self.auth["aws"], MemRatchet())                      # lo que había: registro + trinquete local vacío (consumidor NUEVO)
    def guard_corregida(self, max_age=30.0, client=None, ratchet=None):
        return CompositeGuard(WitnessGuard(client or self.wc, self.auth["aws"], self.log, max_age_s=max_age, now=lambda: self.wall[0]), LogGuard(self.log, self.auth["aws"], ratchet or MemRatchet()))

    def intenta_adquirir(self, guard, holder="aws-nuevo"):
        n = self.node("aws", guard=guard, holder=holder); r1 = n.acquire(); self.clk.advance(TTL + MARGIN + 0.1); r2 = n.acquire(); return n, r2


@pytest.fixture
def w(tmp_path): return W(tmp_path)


def test_sin_ataque_el_titular_legitimo_y_el_failback_funcionan_con_la_guardia_corregida(w):
    n, r = w.intenta_adquirir(w.guard_corregida()); assert not r.ok and "SELLADO" in r.reason                  # OCI promovió y selló: AWS no entra
    w.oci.release(); append(w.log, w.auth["operator"], "operator", "unsealed", 2)                           # failback manual…
    head = w.log.names()[-1]; from app.failover.seal_log import Entry
    w.rep(*make_report(w.auth["operator"], "operator", kind="seal_head", seal_seq=3, seal_digest=Entry.load(w.log.read(head)).digest()))      # …y el operador lo ancla en el testigo
    n, r = w.intenta_adquirir(w.guard_corregida(), holder="aws-failback"); assert r.ok and n.is_valid(), r.reason


def test_1_el_ataque_FUNCIONABA_contra_la_implementacion_vulnerable_instancia_nueva_adquiere_con_informacion_antigua(w):
    w.ataque()
    n, r = w.intenta_adquirir(w.guard_vulnerable())
    assert r.ok and n.is_valid(), "(control negativo) la versión vulnerable debía aceptar el lease y el sello antiguos coherentes: " + r.reason
    assert n._epoch <= 2, "AWS tomó la autoridad sobre una historia anterior a la promoción de OCI"


def test_2_la_version_corregida_rechaza_el_estado_antiguo_en_un_nodo_completamente_nuevo(w):
    w.ataque(); g = w.guard_corregida()
    n, r = w.intenta_adquirir(g); assert not r.ok and not n.is_valid() and ("RETROCESO" in r.reason or "TRUNCAMIENTO" in r.reason)
    assert any("TRUNCAMIENTO" in x or "RETROCESO" in x for x in g.guards[0].rejects)                              # lo delata el TESTIGO (marca de agua: época 2, sello 2), no la cadena ni la firma
    # el testigo detecta también el retroceso del lease aunque el registro del sello estuviera íntegro
    w2 = WitnessGuard(w.wc, w.auth["aws"], None, now=lambda: w.wall[0]); ok, why = w2(1, None); assert not ok and "RETROCESO del lease" in why


def test_3_base_restaurada_de_un_snapshot_antiguo_trinquete_y_epoca_de_la_base_viejos(w):
    w.ataque(); viejo = MemRatchet()                                                                           # el trinquete de la base restaurada vuelve a 0
    assert viejo.observe(0) == 0
    n, r = w.intenta_adquirir(w.guard_corregida(ratchet=viejo)); assert not r.ok and not n.is_valid()
    n2, r2 = w.intenta_adquirir(CompositeGuard(LogGuard(w.log, w.auth["aws"], viejo)), holder="aws-snap"); assert r2.ok                    # (control) sin testigo, la base vieja NO lo evita


def test_4_sin_referencia_verificable_se_bloquea_testigo_caido_inaccesible_sin_inicializar_firma_falsa_reproduccion_y_caducidad(w):
    w.ataque()
    w.witness.down = True; n, r = w.intenta_adquirir(w.guard_corregida()); assert not r.ok and not n.is_valid()                                      # testigo caído
    w.witness.down = False
    fresco = Witness(w.wpath.parent / "otro.jsonl", w.auth["witness"], w.auth["witness"], now=lambda: w.wall[0]); n, r = w.intenta_adquirir(w.guard_corregida(client=LocalWitnessClient(fresco))); assert not r.ok   # sin inicializar
    falso = Ed25519Auth("witness", raw(Ed25519PrivateKey.generate()), w.pubs); impostor = Witness(w.wpath.parent / "imp.jsonl", falso, w.auth["operator"], now=lambda: w.wall[0])
    impostor.report(*make_report(w.auth["operator"], "operator", kind="genesis", lease_epoch=0, seal_seq=1, seal_digest="x"))
    n, r = w.intenta_adquirir(w.guard_corregida(client=LocalWitnessClient(impostor))); assert not r.ok                                           # firma de un testigo que NO es el anclado
    viejo = w.witness.attest("nonce-ajeno")                                                                                                       # reproducción de una atestación válida de otro reto
    class Repro:
        def attest(self, nonce): return viejo
    n, r = w.intenta_adquirir(w.guard_corregida(client=Repro())); assert not r.ok
    w.wall[0] += 3600
    class Rancio:                                                                                                                                      # atestación con fecha antigua
        def attest(self, nonce): return {**w.witness.attest(nonce), "issued_at": w.wall[0] - 3600}
    n, r = w.intenta_adquirir(w.guard_corregida(client=Rancio())); assert not r.ok


def test_5_almacen_del_lease_o_del_sello_temporalmente_inaccesible_no_concede_autoridad(w):
    class Caido(InMemoryStore):
        def read(self): raise StoreUnavailable("caído")
    c = Caido(); c.verified = True
    n = LeaseClient(c, LeaseConfig(ttl_s=TTL, margin_s=MARGIN), holder_id="aws-n", mono=w.clk, authenticator=w.auth["aws"], acquire_guard=w.guard_corregida()); assert not n.acquire().ok and not n.is_valid()
    w.log.down = True
    n, r = w.intenta_adquirir(w.guard_corregida()); assert not r.ok and not n.is_valid()                                                              # registro del sello caído: falla cerrado
    w.log.down = False


def test_6_el_testigo_solo_avanza_informes_regresivos_o_de_informantes_no_autorizados_se_rechazan(w):
    def rep(who, **p): return w.witness.report(*make_report(w.auth[who], who, **p))
    assert not rep("aws", kind="lease_epoch", lease_epoch=1)[0]                                            # época que baja
    assert not rep("oci", kind="seal_head", seal_seq=1, seal_digest="x")[0]                                 # cabeza que baja
    assert not rep("oci", kind="seal_head", seal_seq=2, seal_digest="otra")[0]                              # misma secuencia, otra entrada: conflicto
    assert not rep("aws", kind="seal_head", seal_seq=9, seal_digest="x")[0]                                 # AWS no puede anclar el sello
    assert not rep("oci", kind="genesis", lease_epoch=0, seal_seq=0, seal_digest=None)[0]                   # ni reinicializar
    assert w.witness.wm["lease_epoch"] == 2 and w.witness.wm["seal_seq"] == 2


def test_7_la_alteracion_del_almacen_del_testigo_se_detecta_pero_restaurar_un_PREFIJO_valido_lo_retrocede_por_eso_exige_infraestructura_independiente_e_inmutable(w, tmp_path):
    lineas = w.wpath.read_text().splitlines(); assert len(lineas) >= 4
    corrupto = tmp_path / "corrupto.jsonl"; corrupto.write_text("\n".join([lineas[0], lineas[1].replace('"reporter": "aws"', '"reporter": "oci"'), *lineas[2:]]) + "\n")
    with pytest.raises(StoreError, match="ALTERADO"): Witness(corrupto, w.auth["witness"], w.auth["witness"])
    prefijo = tmp_path / "prefijo.jsonl"; prefijo.write_text("\n".join(lineas[:2]) + "\n")                       # restaurar solo el principio: cadena VÁLIDA
    w2 = Witness(prefijo, w.auth["witness"], w.auth["witness"], now=lambda: w.wall[0]); assert w2.wm["lease_epoch"] < 2
    # LÍMITE: si el atacante controla TAMBIÉN el almacén del testigo, la referencia retrocede con todo lo demás
    w.ataque(); n, r = w.intenta_adquirir(w.guard_corregida(client=LocalWitnessClient(w2))); assert r.ok, "(límite documentado) con el testigo restaurado la información antigua vuelve a aceptarse"


def test_cliente_https_del_testigo_valida_url_permisos_y_falla_cerrado(w, tmp_path):
    import http.server, os, threading
    from app.failover.witness import HttpWitnessClient
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            import urllib.parse
            n = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)["nonce"][0]; b = json.dumps(w.witness.attest(n)).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        f = tmp_path / "w.url"; f.write_text(f"http://127.0.0.1:{srv.server_port}/attest"); os.chmod(f, 0o600)
        cli = HttpWitnessClient(str(f), allow_http_localhost=True); g = WitnessGuard(cli, w.auth["aws"], w.log, now=lambda: w.wall[0]); assert g(2, None)[0]       # estado actual: autoriza
        w.ataque(); ok, why = g(1, None); assert not ok                                                                                         # estado antiguo: rechaza por HTTP también
        os.chmod(f, 0o644)
        with pytest.raises(StoreError): HttpWitnessClient(str(f), allow_http_localhost=True)
        os.chmod(f, 0o600); f.write_text("http://127.0.0.1:1/x")
        assert not WitnessGuard(HttpWitnessClient(str(f), allow_http_localhost=True), w.auth["aws"], w.log)(1, None)[0]                          # inaccesible: falla cerrado
        f.write_text("http://ejemplo.org/x")
        with pytest.raises(StoreError): HttpWitnessClient(str(f))                                                                               # solo https
    finally:
        srv.shutdown()
