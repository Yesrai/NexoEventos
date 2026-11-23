"""Endurecimiento del testigo: concurrencia (sin retrocesos ni actualizaciones perdidas), control de acceso, separación de claves, recuperación de un nodo AWS nuevo con dos testigos (historia antigua en uno, caída de uno)
y CONTENEDOR Docker real (construcción, arranque, HTTP, reinicio, recuperación, usuario no root)."""
import base64, hashlib, json, os, random, shutil, subprocess, sys, threading, time, urllib.error, urllib.request
from pathlib import Path
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "scripts/multicloud/witness")); sys.path.insert(0, str(Path(__file__).resolve().parent))
import witness_service as WS  # noqa: E402
from test_witness_service import Env, raw, pub  # noqa: E402
from app.failover.seal_log import InMemoryLog, append, make_sealer  # noqa: E402
from app.failover.store import PreconditionFailed, StoreError, StoreUnavailable  # noqa: E402
from app.failover.witness import (EcdsaP256Verifier, FileAppendStore, HttpWitnessClient, ImmutableBucketSim, LocalWitnessClient, ObjectAppendStore, QuorumReporter, QuorumWitnessGuard, Witness,  # noqa: E402
                                  WitnessGuard, make_report)


def chain_ok(store):
    prev = "0" * 64
    for line in store.lines():
        e = json.loads(line); assert e["prev"] == prev; prev = e["hash"]


# ───────────── 3. concurrencia ─────────────
@pytest.mark.parametrize("kind", ["objetos", "archivo"])
def test_informes_simultaneos_desde_varias_instancias_sin_retrocesos_ni_actualizaciones_perdidas(tmp_path, kind):
    e = Env(tmp_path); store = ObjectAppendStore(ImmutableBucketSim(worm=True)) if kind == "objetos" else FileAppendStore(tmp_path / "c.jsonl")
    inst = [e.witness(store=store, max_epoch_jump=1000) for _ in range(4)]; e.genesis(inst[0]); resultados, lock = [], threading.Lock()
    def worker(i, epochs):
        w = inst[i % 4]
        for ep in epochs:
            ok, why = w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=ep)); 
            with lock: resultados.append((ep, ok, why))
    epocas = list(range(1, 41)); random.Random(7).shuffle(epocas)
    ths = [threading.Thread(target=worker, args=(i, epocas[i::8])) for i in range(8)]; [t.start() for t in ths]; [t.join() for t in ths]
    aceptadas = [ep for ep, ok, _ in resultados if ok]
    final = e.witness(store=store, max_epoch_jump=1000); assert final.wm["lease_epoch"] == 40, "se perdió la actualización más alta"                                      # marca de agua = máximo
    assert final.entries == 1 + len(aceptadas), "hay informes aceptados que NO están en el almacén (actualizaciones perdidas) o entradas fantasma"
    chain_ok(store)                                                                                                                                  # cadena íntegra
    epocas_guardadas = [json.loads(l)["payload"]["lease_epoch"] for l in store.lines()[1:]]; assert epocas_guardadas == sorted(epocas_guardadas)      # NUNCA hay una entrada por debajo de la anterior
    assert all(not ok and "RETROCESO" in why for ep, ok, why in resultados if ep not in aceptadas)


def test_requisito_del_almacen_sin_creacion_condicional_atomica_SE_PIERDEN_actualizaciones(tmp_path):
    """CONTROL NEGATIVO del REQUISITO: el almacén real debe ofrecer «crear si no existe» ATÓMICO (Cloud Storage: ifGenerationMatch=0). Sin él, dos instancias escriben el mismo número y una actualización se pierde."""
    class NoAtomico(ImmutableBucketSim):
        def create(self, name, data): time.sleep(0.002); self.o[name] = data                           # sobrescribe: no es condicional
    e = Env(tmp_path)
    perdido = False
    for _ in range(40):
        bk = NoAtomico(worm=False); st = ObjectAppendStore(bk); x, y = e.witness(store=st), e.witness(store=st); e.genesis(x); r = []
        ts = [threading.Thread(target=lambda w=w, ep=ep: r.append(w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=ep))[0])) for w, ep in ((x, 5), (y, 6))]
        [t.start() for t in ts]; [t.join() for t in ts]
        if sum(r) == 2 and len(bk.o) == 2: perdido = True; break                                             # 2 informes aceptados, solo 1 entrada + génesis: UNO SE PERDIÓ
    assert perdido, "(control) sin creación condicional atómica debía poder perderse una actualización"


def test_concurrencia_por_HTTP_contra_un_servicio_marca_de_agua_monotona(tmp_path):
    e = Env(tmp_path); w = e.witness(max_epoch_jump=1000); e.genesis(w); srv = WS.serve(w); c = e.client_url(srv); res = []
    try:
        ths = [threading.Thread(target=lambda ep=ep: res.append((ep, c.report(*e.rep("oci", kind="lease_epoch", lease_epoch=ep))))) for ep in random.Random(3).sample(range(1, 30), 20)]
        [t.start() for t in ths]; [t.join() for t in ths]
        top = max(ep for ep, r in res if r["ok"]); assert w.wm["lease_epoch"] == top == max(ep for ep, _ in res)
        assert w.entries == 1 + sum(1 for _, r in res if r["ok"]); chain_ok(w.store)
    finally: srv.shutdown()


# ───────────── 6. control de acceso ─────────────
def tokens_file(tmp, spec):
    f = tmp / "tokens.json"; f.write_text(json.dumps({"tokens": [{"id": k, "sha256": hashlib.sha256(v[0].encode()).hexdigest(), "scopes": v[1]} for k, v in spec.items()]})); os.chmod(f, 0o600); return f


def http(url, method="GET", body=None, token=None):
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as ex: return ex.code, {}


def test_anonimos_e_identidades_no_autorizadas_no_pueden_atestar_informar_ni_inicializar(tmp_path):
    e = Env(tmp_path); w = e.witness(); tf = tokens_file(tmp_path, {"aws-consumidor": ("tok-aws-consumidor", ["attest", "entry"]), "oci-informante": ("tok-oci-informante", ["report"])})
    srv = WS.serve(w, invokers=WS.Invokers.from_file(tf)); base = f"http://127.0.0.1:{srv.server_port}"; nonce = "ab" * 16
    gen = json.dumps(dict(zip(("reporter", "payload", "sig"), e.rep("operator", kind="genesis", lease_epoch=0, seal_seq=1, seal_digest="g")))).encode()
    try:
        assert http(base + "/healthz")[0] == 200                                                                         # solo la salud es pública (sin datos)
        for ruta, m, b in ((f"/attest?nonce={nonce}", "GET", None), ("/entry?seq=1", "GET", None), ("/report", "POST", gen)):
            assert http(base + ruta, m, b)[0] == 401, ruta                                                              # anónimo
            assert http(base + ruta, m, b, token="inventado")[0] == 403, ruta                                           # identidad desconocida
        assert http(base + f"/attest?nonce={nonce}", token="tok-oci-informante")[0] == 403                              # identidad válida SIN ese alcance
        assert http(base + "/report", "POST", gen, token="tok-aws-consumidor")[0] == 403
        assert w.wm is None, "un anónimo o no autorizado inicializó el testigo"
        # con la identidad correcta pero una FIRMA que no es del operador: tampoco se inicializa (la autorización de fondo es la firma)
        falso = json.dumps(dict(zip(("reporter", "payload", "sig"), e.rep("aws", kind="genesis", lease_epoch=0, seal_seq=1, seal_digest="g")))).encode()
        assert http(base + "/report", "POST", falso, token="tok-oci-informante")[0] == 409 and w.wm is None
        assert http(base + "/report", "POST", gen, token="tok-oci-informante")[0] == 200 and w.wm is not None          # operador firmado + identidad con alcance: sí
        assert http(base + "/report", "POST", gen, token="tok-oci-informante")[0] == 409                                # no se reinicializa
        assert http(base + f"/attest?nonce={nonce}", token="tok-aws-consumidor")[0] == 200
        assert "tok-aws-consumidor" not in tf.read_text() and "tok-oci-informante" not in tf.read_text()               # el archivo guarda solo hashes
        os.chmod(tf, 0o644)
        with pytest.raises(SystemExit): WS.Invokers.from_file(tf)
    finally: srv.shutdown()


# ───────────── 7. separación de claves ─────────────
def test_la_clave_de_firma_del_testigo_no_puede_ser_la_de_un_informante(tmp_path):
    k = Ed25519PrivateKey.generate(); rep = {"oci": [pub(k)], "aws": [pub(Ed25519PrivateKey.generate())]}
    with pytest.raises(SystemExit, match="DISTINTAS"): WS.assert_key_separation(pub(k), rep)
    WS.assert_key_separation(EcdsaP256Verifier.__init__ and __import__("app.failover.witness", fromlist=["EcdsaP256Signer"]).EcdsaP256Signer().public_der(), rep)     # clave P-256 de KMS: distinta
    e = Env(tmp_path, ecdsa=True); assert e.signer.public_der() != pub(Ed25519PrivateKey.generate())
    # las claves de los informantes NO sirven para firmar atestaciones: el verificador del testigo las rechaza
    w = e.witness(); e.genesis(w); assert not WitnessGuard(type("C", (), {"attest": lambda s, n: {**w.attest(n), "sig": e.auth["oci"].sign("oci", b"x")}})(), e.verifier, now=lambda: e.wall[0])(0, None)[0]


# ───────────── 4/5. nodo AWS nuevo con DOS testigos ─────────────
def dos_testigos(tmp):
    e = Env(tmp); ws = [e.witness(name="a.jsonl"), e.witness(name="b.jsonl")]
    for w in ws: e.genesis(w); w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=1)); w.report(*e.rep("oci", kind="lease_epoch", lease_epoch=2))
    return e, ws


def test_nodo_aws_nuevo_con_dos_testigos_uno_con_historia_antigua_ambos_disponibles_y_uno_caido(tmp_path):
    e, (a, b) = dos_testigos(tmp_path); srvs = [WS.serve(x) for x in (a, b)]
    try:
        miembros = lambda cl: [(f"t{i}", c, e.verifier) for i, c in enumerate(cl)]
        clientes = [e.client_url(s) for s in srvs]
        g = QuorumWitnessGuard(miembros(clientes), 2, now=lambda: e.wall[0]); assert g(2, None)[0]                      # ambos disponibles y al día: acepta el estado vigente (época 2)
        assert not g(1, None)[0]                                                                                    # …y rechaza el antiguo
        (tmp_path / "vieja.jsonl").write_text("\n".join((tmp_path / "a.jsonl").read_text().splitlines()[:2]) + "\n"); vieja = e.witness(name="vieja.jsonl"); sv = WS.serve(vieja)    # UNO devuelve una historia antigua
        try:
            g2 = QuorumWitnessGuard(miembros([e.client_url(sv), clientes[1]]), 2, now=lambda: e.wall[0]); ok, why = g2(1, None)
            assert not ok and "RETROCESO" in why and g2.behind == ["t0"]                                              # el otro testigo manda: se rechaza y se señala al atrasado
            assert g2(2, None)[0]                                                                                    # y el estado legítimo SIGUE siendo aceptable (no hay bloqueo innecesario)
        finally: sv.shutdown()
        srvs[1].shutdown(); g3 = QuorumWitnessGuard(miembros(clientes), 2, now=lambda: e.wall[0]); ok, why = g3(2, None); assert not ok and "quórum" in why        # UNO caído con 2/2: bloquea
        assert QuorumWitnessGuard(miembros(clientes), 1, now=lambda: e.wall[0])(2, None)[0]                          # (con k=1 seguiría: por eso el automático exige k=2)
    finally:
        for s in srvs: s.shutdown()


def test_con_un_testigo_caido_el_quorum_2_de_2_bloquea_las_nuevas_promociones_y_no_se_escribe_el_sello_como_completado(tmp_path):
    e, (a, b) = dos_testigos(tmp_path); log = InMemoryLog(); append(log, e.auth["operator"], "operator", "unsealed", 0)
    informar = QuorumReporter([LocalWitnessClient(a), LocalWitnessClient(b)], 2)
    b.down = True
    def witness_report(seq, dig, ep): return informar(*e.rep("oci", kind="seal_head", seal_seq=seq, seal_digest=dig))
    with pytest.raises(StoreUnavailable, match="quórum"): make_sealer(log, e.auth["oci"], witness_report=witness_report)(3)          # la promoción NO se completa
    b.down = False
    # tras volver el testigo, el informe pendiente se puede completar (el sello ya escrito solo pudo BLOQUEAR a AWS)
    assert len(informar(*e.rep("oci", kind="lease_epoch", lease_epoch=3))) == 2


# ───────────── 1/2. contenedor Docker real ─────────────
def docker_ok():
    try: return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except Exception: return False


@pytest.fixture(scope="module")
def imagen(tmp_path_factory):
    if not docker_ok(): pytest.skip("Docker no disponible")
    ctx = tmp_path_factory.mktemp("ctx"); (ctx / "backend/app").mkdir(parents=True); shutil.copy(ROOT / "backend/app/__init__.py", ctx / "backend/app/__init__.py"); shutil.copytree(ROOT / "backend/app/failover", ctx / "backend/app/failover", ignore=shutil.ignore_patterns("__pycache__"))
    (ctx / "scripts/multicloud/witness").mkdir(parents=True); shutil.copy(ROOT / "scripts/multicloud/witness/witness_service.py", ctx / "scripts/multicloud/witness/witness_service.py"); shutil.copy(ROOT / "scripts/multicloud/witness/Dockerfile", ctx / "Dockerfile")
    tag = f"nexo-witness-test:{os.getpid()}"; r = subprocess.run(["docker", "build", "-q", "-t", tag, str(ctx)], capture_output=True, text=True, timeout=600); assert r.returncode == 0, r.stderr[-500:]
    yield tag
    subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)


def lanzar(tag, tmp_path, e, nombre):
    data = tmp_path / "data"; cfg = tmp_path / "cfg"; data.mkdir(exist_ok=True); cfg.mkdir(exist_ok=True)
    (cfg / "reporters.json").write_text(json.dumps({k: [base64.b64encode(v[0]).decode()] for k, v in e.pubs.items() if k != "witness"}))
    tokens_file(cfg, {"consumidor": ("t-cons", ["attest", "entry"]), "informante": ("t-inf", ["report"])}); (cfg / "tokens.json").exists() or None
    for p in (cfg / "reporters.json",): os.chmod(p, 0o600)
    uid = f"{os.getuid()}:{os.getgid()}"
    r = subprocess.run(["docker", "run", "-d", "--name", nombre, "--user", uid, "-p", "127.0.0.1::8080", "-v", f"{data}:/data", "-v", f"{cfg}:/cfg:ro", "-e", "WITNESS_STORE=file:/data/log.jsonl", "-e", "WITNESS_SIGNER=local-ecdsa:/data/key.pem",
                        "-e", "WITNESS_ALLOW_LOCAL_SIGNER=1", "-e", "WITNESS_REPORTERS_FILE=/cfg/reporters.json", "-e", "WITNESS_INVOKER_TOKENS_FILE=/cfg/tokens.json", tag], capture_output=True, text=True); assert r.returncode == 0, r.stderr
    return data


def puerto(nombre):
    for _ in range(40):
        r = subprocess.run(["docker", "port", nombre, "8080"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip(): return int(r.stdout.split(":")[-1])
        time.sleep(0.25)
    raise AssertionError("sin puerto")


def esperar(base):
    for _ in range(60):
        try:
            if urllib.request.urlopen(base + "/healthz", timeout=2).status == 200: return
        except Exception: time.sleep(0.5)
    raise AssertionError("el contenedor no respondió a /healthz")


def test_contenedor_real_arranque_http_firmas_reinicio_recuperacion_y_acceso(imagen, tmp_path):
    e = Env(tmp_path); nombre = f"nexo-witness-{os.getpid()}"
    try:
        data = lanzar(imagen, tmp_path, e, nombre); base = f"http://127.0.0.1:{puerto(nombre)}"; esperar(base)
        assert subprocess.run(["docker", "exec", nombre, "id", "-u"], capture_output=True, text=True).stdout.strip() != "0"            # no root
        assert http(base + "/attest?nonce=" + "cd" * 16)[0] == 401                                                  # anónimo fuera
        rep = lambda who, **p: json.dumps(dict(zip(("reporter", "payload", "sig"), e.rep(who, **p)))).encode()
        assert http(base + "/report", "POST", rep("operator", kind="genesis", lease_epoch=0, seal_seq=1, seal_digest="g"), token="t-inf")[0] == 200
        assert http(base + "/report", "POST", rep("aws", kind="lease_epoch", lease_epoch=1), token="t-inf")[0] == 200
        assert http(base + "/report", "POST", rep("oci", kind="lease_epoch", lease_epoch=2), token="t-inf")[0] == 200
        assert http(base + "/report", "POST", rep("oci", kind="lease_epoch", lease_epoch=1), token="t-inf")[0] == 409                      # regresión rechazada
        # desafío y firma: se verifica con la clave PÚBLICA del testigo (derivada del archivo de clave del volumen)
        from cryptography.hazmat.primitives import serialization as S
        k = S.load_pem_private_key((data / "key.pem").read_bytes(), password=None); der = k.public_key().public_bytes(S.Encoding.DER, S.PublicFormat.SubjectPublicKeyInfo)
        c_url = tmp_path / "u"; c_url.write_text(base + "/attest"); os.chmod(c_url, 0o600)
        class Cli(HttpWitnessClient):
            def attest(self, nonce):
                s, b = http(base + "/attest?nonce=" + nonce, token="t-cons"); assert s == 200; return b
        g = WitnessGuard(Cli(str(c_url), allow_http_localhost=True), EcdsaP256Verifier(der), now=time.time)
        assert g(2, None)[0] and not g(1, None)[0]                                                                  # firma ECDSA verificada; el estado antiguo se rechaza
        # reinicio del contenedor: el estado vuelve del volumen
        subprocess.run(["docker", "restart", nombre], capture_output=True, timeout=60); base2 = f"http://127.0.0.1:{puerto(nombre)}"; esperar(base2); base = base2
        s, att = http(base + "/attest?nonce=" + "ef" * 16, token="t-cons"); assert s == 200 and att["watermark"]["lease_epoch"] == 2 and att["entries"] == 3
        # recuperación: un almacén ALTERADO impide arrancar
        subprocess.run(["docker", "stop", nombre], capture_output=True, timeout=60)
        lines = (data / "log.jsonl").read_text().splitlines(); (data / "log.jsonl").write_text("\n".join([lines[0], lines[1].replace('"lease_epoch": 1', '"lease_epoch": 0'), lines[2]]) + "\n")
        subprocess.run(["docker", "start", nombre], capture_output=True, timeout=60); time.sleep(3)
        st = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", nombre], capture_output=True, text=True).stdout.split()
        assert st[0] == "false" and st[1] != "0", "el contenedor arrancó con un almacén alterado"
        assert "ALTERADO" in subprocess.run(["docker", "logs", nombre], capture_output=True, text=True).stderr
    finally:
        subprocess.run(["docker", "rm", "-f", nombre], capture_output=True)
