"""Servicio y cliente del TESTIGO de frescura (local): arranque, reinicio, recuperación, ataques (falsificación, reproducción, caducidad, restauración de historial, informantes comprometidos), quórum de testigos, firma ECDSA P-256
(equivalente a Cloud KMS con HSM), almacén de objetos con retención, caída del testigo (sin doble escritura) y pérdida total del testigo."""
import base64, json, os, sys, tempfile, threading, urllib.request, urllib.error
from pathlib import Path
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "scripts/multicloud/witness")); sys.path.insert(0, str(ROOT / "scripts/multicloud/failover"))
import witness_service as WS  # noqa: E402
from app.failover.lease import Ed25519Auth, LeaseClient, LeaseConfig, init_lease  # noqa: E402
from app.failover.seal_log import Entry, InMemoryLog, LogGuard, MemRatchet, _name, append, make_sealer  # noqa: E402
from app.failover.store import InMemoryStore, StoreError, StoreUnavailable  # noqa: E402
from app.failover.witness import (CompositeGuard, EcdsaP256Signer, EcdsaP256Verifier, HttpWitnessClient, ImmutableBucketSim, LocalWitnessClient, ObjectAppendStore, QuorumWitnessGuard,  # noqa: E402
                                  Witness, WitnessGuard, WitnessMemory, make_report)

raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


class Env:
    def __init__(self, tmp, ecdsa=False):
        self.tmp = Path(tmp); ks = {n: Ed25519PrivateKey.generate() for n in ("aws", "oci", "operator", "witness")}; self.pubs = {n: [pub(v)] for n, v in ks.items()}
        self.auth = {n: Ed25519Auth(n, raw(ks[n]), self.pubs) for n in ks}
        self.reporters = Ed25519Auth("witness", raw(ks["witness"]), self.pubs)
        self.signer = EcdsaP256Signer() if ecdsa else self.auth["witness"]
        self.verifier = EcdsaP256Verifier(self.signer.public_der()) if ecdsa else self.auth["aws"]
        self.wall = [9000.0]
    def witness(self, store=None, name="t.jsonl", **kw): return Witness(store or (self.tmp / name), self.signer, self.reporters, now=lambda: self.wall[0], **kw)
    def rep(self, who, **p): return make_report(self.auth[who], who, **p)
    def genesis(self, w, epoch=0, seq=1, dig="g"): assert w.report(*self.rep("operator", kind="genesis", lease_epoch=epoch, seal_seq=seq, seal_digest=dig))[0]
    def client_url(self, srv):
        f = self.tmp / f"u{srv.server_port}"; f.write_text(f"http://127.0.0.1:{srv.server_port}/attest"); os.chmod(f, 0o600); return HttpWitnessClient(str(f), allow_http_localhost=True)
    def guard(self, client, **kw): return WitnessGuard(client, self.verifier, now=lambda: self.wall[0], **kw)


def test_arranque_informe_atestacion_reinicio_y_recuperacion_por_HTTP(tmp_path):
    e = Env(tmp_path); w = e.witness(); srv = WS.serve(w)
    try:
        c = e.client_url(srv); assert not e.guard(c)(0, None)[0]                                              # sin inicializar: bloquea
        r = c.report(*e.rep("operator", kind="genesis", lease_epoch=0, seal_seq=1, seal_digest="g")); assert r["ok"] and r["seq"] == 1 and r["sig"]
        assert c.report(*e.rep("aws", kind="lease_epoch", lease_epoch=1))["ok"] and c.report(*e.rep("oci", kind="lease_epoch", lease_epoch=2))["ok"]
        assert e.guard(c)(2, None)[0] and not e.guard(c)(1, None)[0]                                           # época actual vale; una anterior se rechaza
    finally: srv.shutdown()
    # REINICIO: otro proceso con el mismo almacén conserva la marca de agua y la cadena
    w2 = e.witness(); assert w2.wm["lease_epoch"] == 2 and w2.entries == 3 and w2.last_hash == w.last_hash
    srv2 = WS.serve(w2)
    try: assert e.guard(e.client_url(srv2))(2, None)[0]
    finally: srv2.shutdown()
    # RECUPERACIÓN: un almacén ALTERADO impide arrancar (no se sirve un historial corrupto)
    lines = (tmp_path / "t.jsonl").read_text().splitlines(); (tmp_path / "t.jsonl").write_text("\n".join([lines[0], lines[1].replace('"lease_epoch": 1', '"lease_epoch": 0'), lines[2]]) + "\n")
    with pytest.raises(StoreError, match="ALTERADO"): e.witness()


def test_ataques_a_las_respuestas_y_a_la_entrada_del_servicio(tmp_path):
    e = Env(tmp_path); w = e.witness(); e.genesis(w); assert w.report(*e.rep("oci", kind="lease_epoch", lease_epoch=2))[0]; srv = WS.serve(w); c = e.client_url(srv)
    try:
        class Mitm:                                                                                           # intermediario que BAJA la marca de agua en la respuesta
            def attest(self, n): a = c.attest(n); a["watermark"] = {**a["watermark"], "lease_epoch": 0}; return a
        ok, why = e.guard(Mitm())(1, None); assert not ok and "NO verifica" in why
        viejo = c.attest("00" * 16)
        class Repro:
            def attest(self, n): return viejo
        ok, why = e.guard(Repro())(1, None); assert not ok and "OTRO reto" in why                             # reproducción de una respuesta válida de otro reto
        e.wall[0] += 3600
        class Rancio:
            def attest(self, n): return {**w.attest(n), "issued_at": e.wall[0] - 3600} | {}
        assert not e.guard(Rancio())(1, None)[0]                                                              # fecha antigua (y además la firma deja de coincidir)
        e.wall[0] -= 3600
        base = f"http://127.0.0.1:{srv.server_port}"
        def post(body, ctype="application/json"):
            req = urllib.request.Request(base + "/report", data=body, method="POST", headers={"Content-Type": ctype, "Content-Length": str(len(body))})
            try: r = urllib.request.urlopen(req); return r.status
            except urllib.error.HTTPError as ex: return ex.code
        assert post(b"no es json") == 400 and post(b"x" * 20000) == 413 and post(json.dumps({"reporter": "aws"}).encode()) == 400
        rep, payload, sig = e.rep("aws", kind="seal_head", seal_seq=9, seal_digest="x"); assert post(json.dumps({"reporter": rep, "payload": payload, "sig": sig}).encode()) == 409      # AWS no puede anclar el sello
        rep, payload, sig = e.rep("oci", kind="lease_epoch", lease_epoch=1); assert post(json.dumps({"reporter": rep, "payload": payload, "sig": sig}).encode()) == 409                  # regresión
        rep, payload, _ = e.rep("oci", kind="lease_epoch", lease_epoch=3); assert post(json.dumps({"reporter": rep, "payload": payload, "sig": "00" * 64}).encode()) == 409                 # firma inválida
        assert urllib.request.urlopen(base + "/healthz").status == 200
        with pytest.raises(urllib.error.HTTPError) as ex: urllib.request.urlopen(base + "/attest?nonce=zz"); assert ex.value.code == 400
        assert w.wm["lease_epoch"] == 2
    finally: srv.shutdown()


def test_informantes_comprometidos_no_pueden_envenenar_el_testigo(tmp_path):
    e = Env(tmp_path); log = InMemoryLog(); g = append(log, e.auth["operator"], "operator", "unsealed", 0)
    def seal_ok(seq, dig):
        try: en = Entry.load(log.read(_name(seq))); return en.digest() == dig and en.signer in ("oci", "operator") and e.auth["aws"].verify(en.signer, en.canonical(), en.sig)
        except Exception: return False
    w = e.witness(seal_verifier=seal_ok, max_epoch_jump=3); e.genesis(w, 0, 1, g.digest())
    assert not w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=10 ** 9))[0]                              # época absurda: DoS evitado
    assert w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=2))[0]
    assert not w.report(*e.rep("oci", kind="seal_head", seal_seq=2, seal_digest="inventada"))[0]                # cabeza que no existe en el registro: no se acepta
    s = make_sealer(log, e.auth["oci"], witness_report=lambda seq, dig, ep: w.report_with_receipt(*e.rep("oci", kind="seal_head", seal_seq=seq, seal_digest=dig)) or None)(2)
    assert w.wm["seal_seq"] == 2 and w.wm["seal_digest"] == s.digest()                                           # la cabeza REAL sí


def test_recibo_firmado_y_comprobacion_de_inclusion_detectan_la_perdida_o_sustitucion_del_historial(tmp_path):
    e = Env(tmp_path); w = e.witness(); e.genesis(w); r = w.report_with_receipt(*e.rep("oci", kind="lease_epoch", lease_epoch=1))
    body = {"seq": r["seq"], "hash": r["hash"], "reporter": "oci"}; assert e.auth["aws"].verify("witness", json.dumps({"receipt": body}, sort_keys=True, separators=(",", ":")).encode(), r["sig"])      # recibo del testigo
    assert w.entry(r["seq"])["hash"] == r["hash"]                                                                # el informante puede VOLVER a comprobar que su informe sigue en la cadena
    prefijo = e.witness(name="p.jsonl"); (tmp_path / "p.jsonl").write_text("\n".join((tmp_path / "t.jsonl").read_text().splitlines()[:1]) + "\n"); prefijo = e.witness(name="p.jsonl")
    assert prefijo.entry(r["seq"]) is None                                                                       # historial restaurado a un prefijo: el informe YA NO está → alarma de pérdida/rollback del testigo


def test_memoria_del_consumidor_detecta_un_testigo_restaurado_a_un_prefijo_y_el_consumidor_nuevo_no(tmp_path):
    e = Env(tmp_path); w = e.witness(); e.genesis(w); w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=1)); w.report(*e.rep("oci", kind="lease_epoch", lease_epoch=2))
    mem = WitnessMemory(tmp_path / "mem.json"); g = e.guard(LocalWitnessClient(w), memory=mem); assert g(2, None)[0]
    (tmp_path / "r.jsonl").write_text("\n".join((tmp_path / "t.jsonl").read_text().splitlines()[:2]) + "\n"); atras = e.witness(name="r.jsonl")          # el atacante restaura el almacén del testigo a un prefijo VÁLIDO
    ok, why = e.guard(LocalWitnessClient(atras), memory=mem)(1, None); assert not ok and "RETROCEDIÓ" in why                                          # consumidor con memoria: lo delata
    ok, why = e.guard(LocalWitnessClient(atras))(1, None); assert ok                                                                                    # (LÍMITE) consumidor NUEVO con un solo testigo: no puede


def test_quorum_de_testigos_con_k_2_resiste_el_retroceso_de_uno_la_caida_de_uno_y_el_conflicto(tmp_path):
    e = Env(tmp_path); a, b = e.witness(name="a.jsonl"), e.witness(name="b.jsonl")
    for w in (a, b): e.genesis(w); w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=1)); w.report(*e.rep("oci", kind="lease_epoch", lease_epoch=2))
    members = lambda ws: [(f"w{i}", LocalWitnessClient(w), e.verifier) for i, w in enumerate(ws)]
    mk = lambda ws, k: QuorumWitnessGuard(members(ws), k, now=lambda: e.wall[0])
    assert mk([a, b], 2)(2, None)[0]
    (tmp_path / "a2.jsonl").write_text("\n".join((tmp_path / "a.jsonl").read_text().splitlines()[:2]) + "\n"); a_atras = e.witness(name="a2.jsonl")        # UN testigo restaurado a un prefijo
    g = mk([a_atras, b], 2); assert not g(1, None)[0] and "RETROCESO" in g(1, None)[1] and g.behind == ["w0"]                                          # el máximo manda: se rechaza y se avisa de quién va por detrás
    b2 = e.witness(name="b2.jsonl"); (tmp_path / "b2.jsonl").write_text((tmp_path / "a2.jsonl").read_text()); b_atras = e.witness(name="b2.jsonl")
    assert mk([a_atras, b_atras], 2)(1, None)[0]                                                                                                         # (LÍMITE) si se retroceden TODOS a la vez, se acepta
    b.down = True; ok, why = mk([a, b], 2)(2, None); assert not ok and "quórum" in why                                                                  # un testigo caído con k=2: bloquea
    assert mk([a, b], 1)(2, None)[0]                                                                                                                     # con k=1 sigue con el otro
    c = e.witness(name="c.jsonl"); e.genesis(c, 0, 1, "OTRA"); c.report(*e.rep("oci", kind="seal_head", seal_seq=2, seal_digest="X")); a.report(*e.rep("oci", kind="seal_head", seal_seq=2, seal_digest="Y"))
    ok, why = mk([a, c], 2)(2, None); assert not ok and "CONFLICTO" in why


def test_firma_ecdsa_p256_equivalente_a_kms_hsm_solo_el_servicio_firma_y_una_clave_ajena_no_verifica(tmp_path):
    e = Env(tmp_path, ecdsa=True); w = e.witness(); e.genesis(w); w.report(*e.rep("oci", kind="lease_epoch", lease_epoch=2)); n0 = e.signer.calls
    srv = WS.serve(w)
    try:
        c = e.client_url(srv); assert e.guard(c)(2, None)[0] and not e.guard(c)(1, None)[0]
        otro = EcdsaP256Verifier(EcdsaP256Signer().public_der()); assert not WitnessGuard(c, otro, now=lambda: e.wall[0])(2, None)[0]                      # otra clave pública: no verifica
        assert not WitnessGuard(c, e.auth["aws"], now=lambda: e.wall[0])(2, None)[0]                                                                       # y una verificación Ed25519 tampoco
        assert e.signer.calls > n0                                                                                                                        # la firma se hizo en el firmante (KMS) y solo para atestar/recibos
    finally: srv.shutdown()


def test_almacen_de_objetos_con_retencion_impide_reescribir_y_sin_retencion_el_prefijo_restaurado_retrocede(tmp_path):
    e = Env(tmp_path); bucket = ImmutableBucketSim(worm=True); w = e.witness(store=ObjectAppendStore(bucket)); e.genesis(w); w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=1)); w.report(*e.rep("oci", kind="lease_epoch", lease_epoch=2))
    for atacar in (lambda: bucket.put_blind("log/000000000003", b"x"), lambda: bucket.delete("log/000000000003")):
        with pytest.raises(Exception): atacar()
    assert e.witness(store=ObjectAppendStore(bucket)).wm["lease_epoch"] == 2                                       # reinicio desde el bucket: intacto
    sin = ImmutableBucketSim(worm=False); w2 = e.witness(store=ObjectAppendStore(sin)); e.genesis(w2); w2.report(*e.rep("aws", kind="lease_epoch", lease_epoch=1)); w2.report(*e.rep("oci", kind="lease_epoch", lease_epoch=2))
    sin.delete("log/000000000003"); assert e.witness(store=ObjectAppendStore(sin)).wm["lease_epoch"] == 1                    # sin retención: restaurar un prefijo SÍ retrocede el testigo
    sin.o["log/000000000002"] = sin.o["log/000000000002"][:-3] + b"XX}"
    with pytest.raises(Exception): e.witness(store=ObjectAppendStore(sin))                                              # reemplazar una entrada intermedia rompe la cadena


def test_caida_del_testigo_google_cloud_bloquea_adquisiciones_y_promociones_sin_doble_escritura_y_el_titular_tiene_gracia_acotada(tmp_path):
    e = Env(tmp_path); w = e.witness(); e.genesis(w); w.report(*e.rep("oci", kind="lease_epoch", lease_epoch=2)); wc = LocalWitnessClient(w)
    clk = [100.0]; g = WitnessGuard(wc, e.verifier, now=lambda: e.wall[0], renew_grace_s=600)
    assert g(2, None)[0]                                                                                       # titular con atestación válida
    w.down = True
    assert g(2, None)[0] and "gracia" in g(2, None)[1]                                                          # renueva la MISMA época durante la gracia
    ok, why = g(3, None); assert not ok                                                                         # otra época: no
    nuevo = e.guard(wc, renew_grace_s=600); ok, why = nuevo(2, None); assert not ok and "INACCESIBLE" in why   # una instancia NUEVA no tiene gracia: no adquiere
    e.wall[0] += 601; assert not g(2, None)[0]                                                                  # pasada la gracia, el titular también se bloquea
    # promoción: sellar exige que el testigo registre la cabeza; con el testigo caído la promoción NO se completa
    log = InMemoryLog(); append(log, e.auth["operator"], "operator", "unsealed", 0)
    def informar(seq, dig, ep):
        r = w.report(*e.rep("oci", kind="seal_head", seal_seq=seq, seal_digest=dig)); return r
    with pytest.raises(StoreUnavailable): make_sealer(log, e.auth["oci"], witness_report=informar)(3)
    w.down = False; assert make_sealer(InMemoryLog(), e.auth["oci"], witness_report=lambda *a: None) is not None


def test_perdida_total_del_testigo_nodos_y_promociones_se_bloquean_y_la_recuperacion_exige_al_operador_y_no_puede_bajar_lo_visto(tmp_path):
    e = Env(tmp_path); w = e.witness(); e.genesis(w, 0, 1); w.report(*e.rep("oci", kind="lease_epoch", lease_epoch=5))
    mem = WitnessMemory(tmp_path / "m.json"); assert e.guard(LocalWitnessClient(w), memory=mem)(5, None)[0]
    nuevo = e.witness(name="vacio.jsonl")                                                                      # el almacén se perdió: servicio nuevo SIN inicializar
    ok, why = e.guard(LocalWitnessClient(nuevo), memory=mem)(5, None); assert not ok and "SIN INICIALIZAR" in why
    # recuperación: el operador reinicializa con una génesis; si pone una marca MENOR que la ya vista por los nodos con memoria, esos nodos lo rechazan
    e.genesis(nuevo, 0, 1); ok, why = e.guard(LocalWitnessClient(nuevo), memory=mem)(5, None); assert not ok
    nuevo2 = e.witness(name="v2.jsonl"); e.genesis(nuevo2, 5, 1); ok, why = e.guard(LocalWitnessClient(nuevo2), memory=WitnessMemory(tmp_path / "m2.json"))(5, None); assert ok     # génesis a la altura real (verificada fuera de banda)


def test_servicio_se_construye_solo_con_kms_y_almacen_declarados(tmp_path):
    rf = tmp_path / "rep.json"; rf.write_text(json.dumps({"aws": [base64.b64encode(b"\x01" * 32).decode()]}))
    with pytest.raises(SystemExit): WS.build_from_env({"WITNESS_STORE": "file:/tmp/x", "WITNESS_SIGNER": "local:/tmp/k", "WITNESS_REPORTERS_FILE": str(rf)})
    with pytest.raises(SystemExit): WS.build_from_env({"WITNESS_STORE": "ftp:/x", "WITNESS_SIGNER": "kms:projects/p", "WITNESS_REPORTERS_FILE": str(rf)})
    with pytest.raises(SystemExit): WS.build_from_env({"WITNESS_STORE": f"file:{tmp_path}/s", "WITNESS_SIGNER": f"local-ecdsa:{tmp_path}/k", "WITNESS_REPORTERS_FILE": str(rf)})        # firmante local sin permiso expreso
    w = WS.build_from_env({"WITNESS_STORE": f"file:{tmp_path}/s", "WITNESS_SIGNER": f"local-ecdsa:{tmp_path}/k", "WITNESS_REPORTERS_FILE": str(rf), "WITNESS_ALLOW_LOCAL_SIGNER": "1"}); assert w.wm is None
    assert oct((tmp_path / "k").stat().st_mode & 0o777) == "0o600"
