"""PERFIL AZURE del testigo: el servicio REAL (witness_service.build_from_env, mismas variables que usaría la VM) como PROCESO, con almacén en archivo y firma ECDSA local.
Demuestra persistencia (kill -9 y reinicio), exclusividad (dos procesos, un solo almacén), autenticación (token Bearer por alcance), TLS con certificado FIJADO y comportamiento ante fallos
(almacén alterado, cola truncada por escritura a medias, directorio sin permiso de escritura). Registra además, como prueba ejecutable, la LIMITACIÓN del archivo local: un prefijo restaurado
no se detecta localmente (por eso este perfil NO cumple `independent_infrastructure_validated`). Sin nube; solo 127.0.0.1."""
import base64, datetime, hashlib, json, os, signal, socket, ssl, subprocess, sys, threading, time
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_witness_service import Env, WS  # noqa: E402
from app.failover.store import StoreUnavailable  # noqa: E402
from app.failover.witness import EcdsaP256Verifier, HttpWitnessClient, LocalEcdsaFileSigner, WitnessGuard  # noqa: E402

ROOT = HERE.parents[2]
LAUNCH = ("import sys,time,os;sys.path.insert(0,r'%s/backend');sys.path.insert(0,r'%s/scripts/multicloud/witness');import witness_service as WS;"
          "w=WS.build_from_env();srv=WS.serve(w,host='127.0.0.1',port=int(os.environ['P']),invokers=WS.invokers_from_env());print('LISTO',flush=True);time.sleep(600)") % (ROOT, ROOT)
TOKENS = {"aws": "tok-aws-" + "a" * 30, "oci": "tok-oci-" + "o" * 30, "ops": "tok-ops-" + "p" * 30}


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Profile:
    def __init__(self, tmp):
        self.tmp = Path(tmp); self.e = Env(tmp)
        rep = {n: [base64.b64encode(k[0]).decode()] for n, k in self.e.pubs.items() if n != "witness"}
        (self.tmp / "reporters.json").write_text(json.dumps(rep)); os.chmod(self.tmp / "reporters.json", 0o600)
        tk = {"tokens": [{"id": "aws", "sha256": hashlib.sha256(TOKENS["aws"].encode()).hexdigest(), "scopes": ["attest", "report"]},
                         {"id": "oci", "sha256": hashlib.sha256(TOKENS["oci"].encode()).hexdigest(), "scopes": ["attest", "report"]},
                         {"id": "ops", "sha256": hashlib.sha256(TOKENS["ops"].encode()).hexdigest(), "scopes": ["entry"]}]}   # el centro solo LEE entradas, no atesta ni informa
        (self.tmp / "tokens.json").write_text(json.dumps(tk)); os.chmod(self.tmp / "tokens.json", 0o600)
        self.store = self.tmp / "witness-log.jsonl"; self.key = self.tmp / "witness-signer.pem"; self.procs = []

    def start(self, port=None):
        port = port or free_port()
        env = {**os.environ, "P": str(port), "WITNESS_STORE": f"file:{self.store}", "WITNESS_SIGNER": f"local-ecdsa:{self.key}", "WITNESS_ALLOW_LOCAL_SIGNER": "1",
               "WITNESS_REPORTERS_FILE": str(self.tmp / "reporters.json"), "WITNESS_INVOKER_TOKENS_FILE": str(self.tmp / "tokens.json")}
        p = subprocess.Popen([sys.executable, "-c", LAUNCH], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True); self.procs.append(p)
        t0 = time.time()
        while time.time() - t0 < 15:
            if p.poll() is not None: return None, p
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close(); return port, p
            except OSError: time.sleep(0.1)
        return None, p

    def client(self, port, who="aws", token=True):
        uf = self.tmp / f"url{port}"; uf.write_text(f"http://127.0.0.1:{port}/attest"); os.chmod(uf, 0o600)
        tf = None
        if token:
            tf = self.tmp / f"tok-{who}"; tf.write_text(TOKENS[who]); os.chmod(tf, 0o600)
        return HttpWitnessClient(str(uf), allow_http_localhost=True, token_file=str(tf) if tf else None)

    def guard(self, client):
        return WitnessGuard(client, EcdsaP256Verifier(LocalEcdsaFileSigner(str(self.key)).public_der()), now=time.time)

    def close(self):
        for p in self.procs:
            if p.poll() is None: p.kill()
            p.wait(5)


@pytest.fixture
def prof(tmp_path):
    p = Profile(tmp_path); yield p; p.close()


def genesis(prof, port):
    return prof.client(port, "oci").report(*prof.e.rep("operator", kind="genesis", lease_epoch=0, seal_seq=1, seal_digest="g"))


def test_persistencia_kill9_y_reinicio_conservan_marca_y_cadena(prof):
    port, p = prof.start(); assert port, p.stderr.read()
    assert genesis(prof, port)["ok"]; c = prof.client(port, "aws")
    for ep in (1, 2, 3): assert c.report(*prof.e.rep("aws", kind="lease_epoch", lease_epoch=ep))["ok"]
    assert prof.guard(c)(3, None)[0]
    p.send_signal(signal.SIGKILL); p.wait(5)                                                     # muerte abrupta, sin cierre ordenado
    port2, p2 = prof.start(); assert port2, p2.stderr.read()
    c2 = prof.client(port2, "aws"); assert prof.guard(c2)(3, None)[0] and not prof.guard(c2)(2, None)[0]      # misma marca de agua: 3 vale, 2 (anterior) se rechaza
    lines = prof.store.read_text().splitlines(); assert len(lines) == 4                          # génesis + 3 épocas, todas persistidas (fsync)


def test_exclusividad_dos_procesos_un_almacen_16_informes_concurrentes_sin_retrocesos(prof):
    pa, a = prof.start(); pb, b = prof.start(); assert pa and pb
    assert genesis(prof, pa)["ok"]; res = []; lock = threading.Lock()
    def go(i):
        port = pa if i % 2 else pb; c = prof.client(port, "aws" if i % 2 else "oci")
        r = c.report(*prof.e.rep("aws" if i % 2 else "oci", kind="lease_epoch", lease_epoch=1 + i))
        with lock: res.append(r["ok"])
    ts = [threading.Thread(target=go, args=(i,)) for i in range(16)]; [t.start() for t in ts]; [t.join() for t in ts]
    entries = [json.loads(l) for l in prof.store.read_text().splitlines()]
    assert [e["seq"] for e in entries] == list(range(1, len(entries) + 1))                       # secuencia sin huecos ni duplicados
    assert all(entries[i]["prev"] == entries[i - 1]["hash"] for i in range(1, len(entries)))     # cadena intacta
    eps = [e["payload"]["lease_epoch"] for e in entries if e["payload"]["kind"] == "lease_epoch"]
    wm = prof.client(pa).attest("ab" * 16)["watermark"]["lease_epoch"]; assert wm == max(eps)    # marca monótona = máximo informado


def test_autenticacion_por_token_y_alcance(prof):
    port, _ = prof.start(); assert port and genesis(prof, port)["ok"]
    with pytest.raises(StoreUnavailable): prof.client(port, token=False).attest("ab" * 16)       # anónimo → 401
    assert prof.client(port, "oci").attest("cd" * 16)["watermark"]                               # identidad válida con alcance
    ops = prof.client(port, "ops")
    with pytest.raises(StoreUnavailable): ops.attest("ef" * 16)                                  # el centro de operaciones NO puede atestar (403)
    assert ops.report(*prof.e.rep("aws", kind="lease_epoch", lease_epoch=9)).get("ok") is not True   # ni informar
    uf = prof.tmp / "badtok"; uf.write_text("mal"); os.chmod(uf, 0o600)
    bad = HttpWitnessClient(str(prof.tmp / f"url{port}"), allow_http_localhost=True, token_file=str(uf))
    with pytest.raises(StoreUnavailable): bad.attest("12" * 16)                                  # token desconocido


def test_informe_con_firma_ajena_o_de_otro_informante_se_rechaza_aunque_el_token_sea_valido(prof):
    port, _ = prof.start(); assert port and genesis(prof, port)["ok"]
    c = prof.client(port, "aws"); payload, sig = prof.e.rep("oci", kind="lease_epoch", lease_epoch=5)[1:]
    r = c.report("aws", payload, sig); assert r.get("ok") is not True                            # firmado por «oci» pero presentado como «aws»
    assert prof.client(port).attest("34" * 16)["watermark"]["lease_epoch"] == 0                  # la marca no se movió


def test_almacen_alterado_o_cola_a_medias_impiden_arrancar(prof):
    port, p = prof.start(); assert genesis(prof, port)["ok"]; assert prof.client(port, "aws").report(*prof.e.rep("aws", kind="lease_epoch", lease_epoch=1))["ok"]
    p.kill(); p.wait(5); raw = prof.store.read_text(); lines = raw.splitlines()
    prof.store.write_text("\n".join([lines[0], lines[1].replace('"lease_epoch": 1', '"lease_epoch": 0')]) + "\n")
    p1, pr1 = prof.start(); assert p1 is None and pr1.returncode not in (None, 0)                # alterado: no arranca
    prof.store.write_text(raw + '{"seq": 3, "prev": "x", "report')                               # escritura a medias (corte de energía): cola ilegible
    p2, pr2 = prof.start(); assert p2 is None and pr2.returncode not in (None, 0)                # falla CERRADO, no sirve un historial dudoso


def test_directorio_sin_permiso_de_escritura_no_acepta_informes_ni_avanza_la_marca(prof):
    port, _ = prof.start(); assert genesis(prof, port)["ok"]; os.chmod(prof.store, 0o400)        # disco lleno / permisos: el archivo deja de ser escribible
    try:
        r = prof.client(port, "aws").report(*prof.e.rep("aws", kind="lease_epoch", lease_epoch=4))
        assert r.get("ok") is not True
        assert prof.client(port).attest("56" * 16)["watermark"]["lease_epoch"] == 0
    finally: os.chmod(prof.store, 0o600)


def test_limitacion_ejecutable_un_prefijo_restaurado_no_se_detecta_localmente(prof):
    """DOCUMENTA el límite del archivo local: quien pueda restaurar un prefijo válido del archivo hace retroceder la marca de agua. No es un fallo del código: es la razón por la que este perfil
    solo vale para una conmutación CONTROLADA (automatic=false) y no cumple independent_infrastructure_validated (haría falta retención WORM o ≥ 2 testigos independientes)."""
    port, p = prof.start(); assert genesis(prof, port)["ok"]; c = prof.client(port, "aws")
    for ep in (1, 2): assert c.report(*prof.e.rep("aws", kind="lease_epoch", lease_epoch=ep))["ok"]
    p.kill(); p.wait(5); lines = prof.store.read_text().splitlines(); prof.store.write_text("\n".join(lines[:2]) + "\n")      # restaura el prefijo: génesis + época 1
    port2, p2 = prof.start(); assert port2, p2.stderr.read()
    assert prof.client(port2).attest("78" * 16)["watermark"]["lease_epoch"] == 1                 # retrocedió de 2 a 1 y el servicio arrancó: NO se detecta


def _selfsigned(tmp):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    k = ec.generate_private_key(ec.SECP256R1()); n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]); now = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
         .not_valid_after(now + datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]), False).sign(k, hashes.SHA256()))
    cf, kf = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
    cf.write_bytes(c.public_bytes(serialization.Encoding.PEM)); kf.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())); return cf, kf


def test_tls_con_certificado_fijado_acepta_solo_ese_certificado(tmp_path):
    import http.server
    e = Env(tmp_path); w = e.witness(); e.genesis(w); cf, kf = _selfsigned(tmp_path); other, _ = _selfsigned(tmp_path / "x") if (tmp_path / "x").mkdir() is None else (None, None)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), WS.make_handler(w, None)); ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(cf, kf)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        uf = tmp_path / "u"; uf.write_text(f"https://127.0.0.1:{srv.server_port}/attest"); os.chmod(uf, 0o600)
        assert HttpWitnessClient(str(uf), ca_file=str(cf)).attest("9a" * 16)["watermark"] is not None           # certificado fijado: acepta
        with pytest.raises(StoreUnavailable): HttpWitnessClient(str(uf)).attest("9b" * 16)                       # sin fijar: autofirmado no es de confianza
        with pytest.raises(StoreUnavailable): HttpWitnessClient(str(uf), ca_file=str(other)).attest("9c" * 16)   # otro certificado: rechaza
    finally: srv.shutdown()
