"""Adaptador de lectura de OCI (oci_source.py) contra un servidor HTTP FALSO en 127.0.0.1: sin OCI real, sin red externa, sin Docker, con claves desechables y
psql/pg_restore falsos. Prueba el lector, la selección segura, la procedencia por firma y la integración con el orquestador (el failover se bloquea ante cualquier
comprobación fallida). La URL del PAR de prueba es un valor inventado que solo existe en un archivo temporal 0600.
Uso: backend/.venv/bin/python -m unittest discover -s scripts/multicloud/tests -p 'test_oci_source.py' -v"""
import json, os, stat, subprocess, sys, tempfile, threading, unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[3]
for sub in ("scripts/multicloud/failover", "scripts/multicloud", "backend"):
    sys.path.insert(0, str(ROOT / sub))
import backup_cycle as bc  # noqa: E402
import oci_source as oc  # noqa: E402
import sim  # noqa: E402
from orchestrator import NotAuthorized, Orchestrator, State  # noqa: E402

PASS = "frase-de-prueba-no-real-5512"
PAR_SECRET = "PAR-INVENTADO-SOLO-PRUEBAS-0xDEADBEEF"
FP_BEFORE = {"alembic": "0008", "reservations": "10", "inventory_md5": "aaa"}
FP_AFTER = {"alembic": "0008", "reservations": "12", "inventory_md5": "bbb"}


class State_:
    def __init__(self):
        self.store: dict[str, bytes] = {}; self.rules: dict[str, list] = {}; self.log: list[str] = []
        self.secret = PAR_SECRET; self.extra_listing: list[str] = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        S: State_ = self.server.state
        u = urlparse(self.path); base = f"/p/{S.secret}/n/ns/b/bucket/o/"
        if not u.path.startswith(base):
            S.log.append("BAD-SECRET"); self.send_response(404); self.end_headers(); return
        name = unquote(u.path[len(base):]); S.log.append(name or "LIST")
        rules = S.rules.get(name) or S.rules.get("*")
        if rules:
            act = rules.pop(0)
            if act[0] == "status":
                self.send_response(act[1]);
                if act[1] == 429: self.send_header("Retry-After", "0")
                self.send_header("Content-Length", "0"); self.end_headers(); return
            if act[0] == "redirect":
                self.send_response(302); self.send_header("Location", "http://127.0.0.1:1/x"); self.send_header("Content-Length", "0"); self.end_headers(); return
            if act[0] == "huge":
                self.send_response(200); self.send_header("Content-Length", str(10 << 30)); self.end_headers(); return
            if act[0] == "stream_forever":   # sin Content-Length: el cliente debe cortar por tamaño
                self.send_response(200); self.send_header("Connection", "close"); self.end_headers()
                try:
                    for _ in range(64): self.wfile.write(b"x" * 65536)
                except OSError: pass
                return
            if act[0] == "truncate":
                data = S.store[name]; self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
                self.wfile.write(data[: len(data) // 2]); self.wfile.flush(); self.close_connection = True; return
        if name == "":
            names = sorted(S.store) + S.extra_listing
            pre = parse_qs(u.query).get("prefix", [""])[0]
            body = json.dumps({"objects": [{"name": n, "size": 1} for n in names if n.startswith(pre)]}).encode()
        elif name in S.store:
            body = S.store[name]
        else:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); t = cls.t = Path(cls.tmp.name)
        env = {**os.environ, "KP": PASS}
        def run(cmd, **kw):
            r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, **kw); assert r.returncode == 0, r.stderr.decode()[:200]; return r
        run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-aes-256-cbc", "-pass", "env:KP", "-out", str(t / "k.pem")], env=env)
        run(["openssl", "req", "-x509", "-new", "-key", str(t / "k.pem"), "-passin", "env:KP", "-days", "2", "-subj", "/CN=t", "-out", str(t / "c.crt")], env=env)
        for n in ("sign", "forger"):
            run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(t / f"{n}.pem")]); os.chmod(t / f"{n}.pem", 0o600)
            run(["openssl", "ec", "-in", str(t / f"{n}.pem"), "-pubout", "-out", str(t / f"{n}.pub")])
        shim = cls.shim = t / "shim"; shim.mkdir()
        (shim / "psql").write_text('#!/usr/bin/env bash\nif [[ "$*" == *"-d drill"* && "$*" == *"-At"* ]]; then echo "alembic=0008"; echo "reservations=${SHIM_RES:-11}"; echo "inventory_md5=${SHIM_MD5:-aaa}"; fi\nexit 0\n')
        (shim / "pg_restore").write_text('#!/usr/bin/env bash\nif [[ "$1" == "--list" ]]; then echo "; toc"; echo "1; 0 0 TABLE x"; fi\ncat >/dev/null\nexit 0\n')
        for f in shim.iterdir(): f.chmod(0o755)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H); cls.srv.state = State_()
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/p/{PAR_SECRET}/n/ns/b/bucket/o/"
        cls.par = t / "par.url"; cls.par.write_text(cls.url); os.chmod(cls.par, 0o600)

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.srv.server_close(); cls.tmp.cleanup()

    def setUp(self):
        self.S = self.srv.state; self.S.store.clear(); self.S.rules.clear(); self.S.log.clear(); self.S.extra_listing.clear(); self.S.secret = PAR_SECRET
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.work = Path(tempfile.mkdtemp(dir=self.tmp.name))

    def reader(self, **kw):
        kw.setdefault("backoff", 0); kw.setdefault("sleep", lambda s: None); kw.setdefault("allow_http_localhost", True)
        return oc.ParHttpReader(self.par, **kw)

    def make_backup(self, minutes_ago, tag="a", sign="good", env="aws-academy", fp=True, recipient=None):
        t0 = self.now - timedelta(minutes=minutes_ago); name = f"nexoeventos-rds-{t0:%Y%m%dT%H%M%SZ}.cms"; stem = name[:-4]
        src = self.work / f".src-{tag}-{minutes_ago}"; src.write_bytes(b"PGDMP" + tag.encode() + bytes(range(256)) * 8)
        out = self.work / f".{name}"
        info = bc.dump_and_encrypt(f"cat {src}", self.t / "c.crt", out); blob = out.read_bytes(); out.unlink(); src.unlink()
        m = bc.build_manifest(env, name, t0, info, FP_BEFORE if fp else None, FP_AFTER if fp else None, recipient)
        mb = (json.dumps(m, indent=1, sort_keys=True) + "\n").encode()
        self.S.store[name] = blob; self.S.store[stem + ".manifest.json"] = mb
        if sign:
            self.S.store[stem + ".manifest.json.sig"] = bc.sign_manifest(str(self.t / ("sign.pem" if sign == "good" else "forger.pem")), mb)
        return stem

    def fetch(self, **kw):
        kw.setdefault("signer_pub", self.t / "sign.pub")
        self.w = Path(tempfile.mkdtemp(dir=self.work))          # directorio nuevo en cada descarga (no se reutiliza lo verificado antes)
        return oc.fetch_latest(self.reader(), self.w, now=self.now, **kw)

    def restore(self, reader=None, extra_env=None, password=PASS, passin="env:NEXO_T_PASS", **kw):
        e = {**os.environ, "PATH": f"{self.shim}:{os.environ['PATH']}", "NEXO_T_PASS": password, **(extra_env or {})}
        kw.setdefault("signer_pub", self.t / "sign.pub"); kw.setdefault("max_age_s", 3600)
        return oc.restore_latest_from_oci(reader or self.reader(), self.t / "k.pem", passin, now=self.now, restore_env=e, **kw)


class TestSeleccionYDescarga(Base):
    def test_descarga_y_selecciona_el_reciente_con_permisos_restrictivos(self):
        self.make_backup(90, "viejo"); n = self.make_backup(30, "medio"); new = self.make_backup(5, "nuevo")
        rep = self.fetch()
        self.assertEqual(rep["selected"]["stem"], new); self.assertEqual(rep["provenance"], "signed")
        v = self.w / "verified"
        self.assertEqual(sorted(p.name for p in v.iterdir()), sorted([new + ".cms", new + ".manifest.json"]))
        for p in v.iterdir(): self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.w / "verified").stat().st_mode), 0o700)
        self.assertEqual(list((self.w / "incoming").iterdir()), [])  # la cuarentena queda vacía
        self.assertNotIn(self.S.store[new + ".cms"], [None])  # sanity
        # solo se descargó el objeto ganador (no los viejos)
        self.assertEqual([x for x in self.S.log if x.endswith(".cms")], [new + ".cms"])

    def test_objeto_inexistente_cae_al_anterior(self):
        ok = self.make_backup(60, "bueno"); bad = self.make_backup(5, "malo"); del self.S.store[bad + ".cms"]
        rep = self.fetch(); self.assertEqual(rep["selected"]["stem"], ok); self.assertTrue(any("objeto no disponible" in s["reason"] for s in rep["skipped"]))

    def test_manifiesto_inexistente_o_corrupto(self):
        ok = self.make_backup(60, "bueno"); a = self.make_backup(20, "a"); b = self.make_backup(5, "b")
        self.S.rules[a + ".manifest.json"] = [("status", 404)]        # aparece en el listado pero su descarga da 404
        self.S.store[b + ".manifest.json"] = b"{no es json"
        rep = self.fetch(); self.assertEqual(rep["selected"]["stem"], ok); self.assertEqual(len(rep["skipped"]), 2)

    def test_hash_y_tamano_incorrectos(self):
        ok = self.make_backup(60, "bueno"); h = self.make_backup(30, "hash"); s = self.make_backup(5, "tam")
        blob = bytearray(self.S.store[h + ".cms"]); blob[len(blob) // 2] ^= 1; self.S.store[h + ".cms"] = bytes(blob)       # mismo tamaño, otro hash
        self.S.store[s + ".cms"] = self.S.store[s + ".cms"][:-10]                                                           # tamaño distinto
        rep = self.fetch(); self.assertEqual(rep["selected"]["stem"], ok)
        reasons = " | ".join(x["reason"] for x in rep["skipped"]); self.assertIn("SHA-256", reasons); self.assertIn("tamaño", reasons)
        self.assertEqual(list((self.w / "incoming").iterdir()), [])  # no quedan parciales

    def test_respaldo_vencido_por_rpo(self):
        self.make_backup(180, "viejo")
        rep = self.fetch(max_age_s=3600)
        self.assertIsNone(rep["selected"]); self.assertIn("vencido", rep["skipped"][0]["reason"])
        self.assertFalse([x for x in self.S.log if x.endswith(".cms")])   # ni siquiera se descarga el objeto

    def test_filtro_de_entorno(self):
        self.make_backup(5, env="oci-recuperacion")
        self.assertIsNone(self.fetch(env="aws-academy")["selected"]); self.assertIsNotNone(self.fetch(env="oci-recuperacion")["selected"])


class TestHttp(Base):
    def test_403_404_son_permanentes_y_no_se_reintentan(self):
        self.make_backup(5)
        for code in (403, 404):
            self.S.log.clear(); self.S.rules["*"] = [("status", code)] * 10
            with self.assertRaises(oc.FetchError) as cm: self.reader(retries=3).list_stems()
            self.assertFalse(cm.exception.transient); self.assertEqual(len(self.S.log), 1, code)
            self.assertNotIn(PAR_SECRET, str(cm.exception))

    def test_429_y_503_se_reintentan_con_limite(self):
        stem = self.make_backup(5)
        self.S.rules["*"] = [("status", 429), ("status", 503)]
        self.assertEqual(self.reader(retries=3).list_stems(), [stem]); self.assertEqual(len(self.S.log), 3)   # 2 fallos + 1 éxito
        self.S.log.clear(); self.S.rules["*"] = [("status", 503)] * 20
        with self.assertRaises(oc.FetchError) as cm: self.reader(retries=2).list_stems()
        self.assertTrue(cm.exception.transient); self.assertEqual(len(self.S.log), 3)                        # 1 + 2 reintentos, ni uno más

    def test_url_o_credencial_incorrecta(self):
        self.make_backup(5); self.S.secret = "OTRO-SECRETO"
        with self.assertRaises(oc.FetchError) as cm: self.reader().list_stems()
        self.assertNotIn(PAR_SECRET, str(cm.exception))
        rep = self.fetch(); self.assertIsNone(rep["selected"]); self.assertNotIn(PAR_SECRET, json.dumps(rep))

    def test_redireccion_rechazada(self):
        self.S.rules["*"] = [("redirect",)]
        with self.assertRaises(oc.FetchError) as cm: self.reader().list_stems()
        self.assertIn("redirección", str(cm.exception)); self.assertEqual(len(self.S.log), 1)

    def test_respuesta_excesivamente_grande(self):
        stem = self.make_backup(5)
        self.S.rules[stem + ".cms"] = [("huge",)]
        rep = self.fetch(); self.assertIsNone(rep["selected"]); self.assertIn("excede", rep["skipped"][0]["reason"])
        self.assertEqual(list((self.w / "incoming").iterdir()), [])
        self.S.rules[stem + ".cms"] = [("stream_forever",)]            # sin Content-Length: se corta por tamaño y se borra el parcial
        rep = self.fetch(); self.assertIsNone(rep["selected"]); self.assertEqual(list((self.w / "incoming").iterdir()), [])

    def test_manifiesto_enorme_se_rechaza(self):
        stem = self.make_backup(5); self.S.store[stem + ".manifest.json"] = b" " * 200000
        self.assertIsNone(self.fetch()["selected"])

    def test_fallo_de_red_durante_la_descarga_se_reintenta_sin_duplicar(self):
        stem = self.make_backup(5)
        self.S.rules[stem + ".cms"] = [("truncate",)]
        rep = self.fetch(); self.assertEqual(rep["selected"]["stem"], stem)
        self.assertEqual(len([x for x in self.S.log if x == stem + ".cms"]), 2)            # 1 truncada + 1 correcta
        self.assertEqual(sorted(p.name for p in (self.w / "verified").iterdir()), sorted([stem + ".cms", stem + ".manifest.json"]))
        self.S.rules[stem + ".cms"] = [("truncate",)] * 20
        rep = self.fetch(); self.assertIsNone(rep["selected"])                              # siempre truncada: falla tras los reintentos
        self.assertEqual(list((self.w / "incoming").iterdir()), []); self.assertEqual(list((self.w / "verified").iterdir()), [])


def shutil_rm(p):
    import shutil; shutil.rmtree(p)


class TestSeguridadDeNombresYDestino(Base):
    def test_nombres_maliciosos_en_el_listado_se_ignoran(self):
        ok = self.make_backup(5)
        self.S.extra_listing = ["../evil.manifest.json", "a/b.manifest.json", ".oculto.manifest.json", "con espacio.manifest.json", "x" * 300 + ".manifest.json",
                                "..%2f..%2fetc%2fpasswd.manifest.json", "ok\x00.manifest.json"]
        self.assertEqual(self.reader().list_stems(), [ok])

    def test_nombre_malicioso_en_get_directo(self):
        for n in ("../x", "a/b", "..", ".x", "", "x/../y", "a b"):
            with self.assertRaises(oc.FetchError): self.reader().get(n, 100)
        self.assertEqual(self.S.log, [])

    def test_manifiesto_con_object_name_malicioso_o_de_otro_respaldo(self):
        a = self.make_backup(60, "a"); b = self.make_backup(5, "b")
        for bad in ("../../etc/passwd", "/etc/passwd", a + ".cms", b + ".cms.exe"):
            m = json.loads(self.S.store[b + ".manifest.json"]); m["object_name"] = bad
            mb = json.dumps(m).encode(); self.S.store[b + ".manifest.json"] = mb
            self.S.store[b + ".manifest.json.sig"] = bc.sign_manifest(str(self.t / "sign.pem"), mb)   # incluso FIRMADO: se rechaza por contenido
            rep = self.fetch(); self.assertEqual(rep["selected"]["stem"], a, bad)
        m = json.loads(self.S.store[b + ".manifest.json"]); m["object_name"] = b + ".cms"; m["name"] = a      # nombre del manifiesto ≠ nombre del objeto
        mb = json.dumps(m).encode(); self.S.store[b + ".manifest.json"] = mb; self.S.store[b + ".manifest.json.sig"] = bc.sign_manifest(str(self.t / "sign.pem"), mb)
        self.assertEqual(self.fetch()["selected"]["stem"], a)

    def test_manifiesto_con_campos_invalidos(self):
        ok = self.make_backup(60, "ok"); b = self.make_backup(5, "b")
        for patch in ({"oci_cms_bytes": -5}, {"oci_cms_bytes": 10 ** 15}, {"oci_cms_bytes": True}, {"oci_cms_sha256": "zz"}, {"created_utc": "ayer"}):
            m = json.loads(self.S.store[b + ".manifest.json"]); m.update(patch); mb = json.dumps(m).encode()
            self.S.store[b + ".manifest.json"] = mb; self.S.store[b + ".manifest.json.sig"] = bc.sign_manifest(str(self.t / "sign.pem"), mb)
            self.assertEqual(self.fetch()["selected"]["stem"], ok, patch)

    def test_no_sobrescribe_ni_sigue_enlaces(self):
        r = self.reader(); stem = self.make_backup(5)
        d = self.work / "dest"; d.mkdir()
        (d / "existe").write_bytes(b"original")
        with self.assertRaises(oc.FetchError): r.get(stem + ".cms", 1 << 20, sink=d / "existe")
        self.assertEqual((d / "existe").read_bytes(), b"original")
        victim = d / "victima"; victim.write_bytes(b"no tocar"); (d / "enlace").symlink_to(victim)
        with self.assertRaises(oc.FetchError): r.get(stem + ".cms", 1 << 20, sink=d / "enlace")
        self.assertEqual(victim.read_bytes(), b"no tocar")


class TestUrlYArchivo(Base):
    def mk(self, text, mode=0o600):
        p = self.work / "u.url"; p.write_text(text); os.chmod(p, mode); return p

    def test_validaciones_de_la_url(self):
        good = "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/X/n/ns/b/bk/o/"
        oc.ParHttpReader(self.mk(good))                                                   # válida
        for text, kw in ((good.replace("https", "http"), {}), ("https://evil.example.com/p/X/n/ns/b/bk/o/", {}), (good + "?x=1", {}), ("https://u:p@objectstorage.x.oraclecloud.com/o/", {}),
                         ("https://oraclecloud.com.evil.io/p/X/", {}), ("ftp://127.0.0.1/", {}), ("", {})):
            with self.assertRaises(oc.FetchError, msg=text): oc.ParHttpReader(self.mk(text), **kw)
        with self.assertRaises(oc.FetchError): oc.ParHttpReader(self.mk(good, 0o644))     # permisos de grupo/otros
        with self.assertRaises(oc.FetchError): oc.ParHttpReader(self.work / "no-existe")

    def test_repr_y_errores_no_contienen_la_url(self):
        r = self.reader(); self.assertNotIn(PAR_SECRET, repr(r)); self.assertNotIn("127.0.0.1", repr(r))


class TestProcedencia(Base):
    def test_firma_valida(self):
        self.make_backup(5); self.assertEqual(self.fetch()["provenance"], "signed")

    def test_sin_firmante_configurado_falla_cerrado_sin_descargar_nada(self):
        self.make_backup(5)
        rep = oc.fetch_latest(self.reader(), self.work / "w", now=self.now)
        self.assertIsNone(rep["selected"]); self.assertIn("procedencia", rep["error"]); self.assertEqual(self.S.log, [])
        out = self.restore(signer_pub=None); self.assertFalse(out["fingerprint_ok"]); self.assertIn("procedencia", out["reason"])

    def test_atacante_con_escritura_reemplaza_manifiesto_y_objeto_pero_no_firma(self):
        good = self.make_backup(60, "legitimo")
        evil = self.make_backup(5, "malicioso", sign="forger")                       # firmado con otra clave
        rep = self.fetch(); self.assertEqual(rep["selected"]["stem"], good)
        self.assertTrue(any("firma" in s["reason"] for s in rep["skipped"]))
        stem2 = self.make_backup(2, "sinfirma", sign=None)                           # sin .sig
        self.assertEqual(self.fetch()["selected"]["stem"], good)

    def test_manifiesto_alterado_tras_firmar(self):
        ok = self.make_backup(60, "ok"); b = self.make_backup(5, "b")
        m = json.loads(self.S.store[b + ".manifest.json"]); m["fingerprint_after"] = FP_BEFORE
        self.S.store[b + ".manifest.json"] = (json.dumps(m) + "\n").encode()           # firma antigua, contenido nuevo
        self.assertEqual(self.fetch()["selected"]["stem"], ok)

    def test_reenvio_de_un_respaldo_firmado_pero_viejo_se_rechaza_por_antiguedad(self):
        self.make_backup(500, "viejo-firmado")
        rep = self.fetch(max_age_s=3600); self.assertIsNone(rep["selected"]); self.assertIn("vencido", rep["skipped"][0]["reason"])

    def test_modo_de_laboratorio_sin_firma_queda_marcado(self):
        self.make_backup(5, sign=None)
        rep = oc.fetch_latest(self.reader(), self.work / "w", now=self.now, allow_unsigned=True)
        self.assertEqual((rep["provenance"], rep["provenance_mode"]), ("unsigned", "UNSIGNED-LAB-ONLY"))

    def test_clave_de_firmante_privada_se_rechaza(self):
        self.make_backup(5)
        rep = oc.fetch_latest(self.reader(), self.work / "w", now=self.now, signer_pub=self.t / "sign.pem")
        self.assertIsNone(rep["selected"])


class FakeOciCli(Base):
    def test_lector_por_cli_con_shim(self):
        stem = self.make_backup(5)
        cli = self.work / "oci"; store = self.work / "bucket"; store.mkdir()
        for k, v in self.S.store.items(): (store / k).write_bytes(v)
        cli.write_text(f'''#!/usr/bin/env python3
import sys, json, shutil, os
a = sys.argv[1:]; B = {str(store)!r}
if "list" in a: print(json.dumps({{"data": [{{"name": n}} for n in sorted(os.listdir(B))]}})); sys.exit(0)
name = a[a.index("--name") + 1]; dest = a[a.index("--file") + 1]
if os.path.exists(dest): sys.exit(9)
p = os.path.join(B, name)
if not os.path.isfile(p): sys.exit(3)
shutil.copy(p, dest)
''')
        cli.chmod(0o755)
        r = oc.OciCliReader("ns", "bucket", "PERFIL", oci_bin=str(cli), backoff=0, sleep=lambda s: None)
        rep = oc.fetch_latest(r, self.work / "w", now=self.now, signer_pub=self.t / "sign.pub")
        self.assertEqual(rep["selected"]["stem"], stem)
        with self.assertRaises(oc.FetchError): r.get("../x", 10)
        with self.assertRaises(oc.FetchError): oc.OciCliReader("ns;rm", "b", "p")
        with self.assertRaises(oc.FetchError): r.get(stem + ".cms", 10)             # tope de tamaño (se comprueba al terminar)


class RealOciAdapters(sim.SimAdapters):
    """Mundo simulado (sondas, lease, DNS) + restore_latest REAL de OCI."""
    def __init__(self, w, test, **kw): super().__init__(w); self.test, self.kw = test, kw
    def restore_latest(self):
        self.w.restore_calls += 1
        return self.test.restore(**self.kw)


class TestIntegracionConElOrquestador(Base):
    def run_orch(self, **kw):
        w, _, cfg = sim.make("primary_dead", 1, None, "r")
        res = Orchestrator(RealOciAdapters(w, self, **kw), cfg, State(Path(tempfile.mkdtemp(dir=self.tmp.name)) / "e.json", "r"), dry_run=False).run()
        w.advance(5)
        return res, w

    def assert_blocked(self, res, w, contains=None):
        self.assertEqual(res["outcome"], "ABORTED", res)
        self.assertEqual((w.dns_applied, w.standby_wrote, w.enable_calls, w.acquire_ok_calls, w.violations), (0, False, 0, 0, 0))
        if contains: self.assertIn(contains, res["abort_reason"])

    def test_camino_feliz_localiza_descarga_verifica_descifra_compara_y_continua(self):
        self.make_backup(90, "viejo"); new = self.make_backup(5, "nuevo")
        res, w = self.run_orch()
        self.assertEqual(res["outcome"], "DONE", res); self.assertEqual((w.violations, w.dns_applied, w.dns_violation, w.restore_calls), (0, 1, False, 1))
        self.assertEqual([x for x in self.S.log if x.endswith(".cms")], [new + ".cms"])
        self.assertTrue(w.standby_wrote)

    def test_si_el_mas_reciente_es_invalido_continua_con_el_anterior_admisible(self):
        ok = self.make_backup(30, "bueno"); bad = self.make_backup(5, "malo", sign="forger")
        res, w = self.run_orch(); self.assertEqual(res["outcome"], "DONE"); self.assertEqual(w.dns_applied, 1)

    def test_cualquier_comprobacion_fallida_bloquea_el_failover(self):
        casos = {}
        def solo(setup): return setup
        def c_sin_respaldos(): pass
        def c_objeto_alterado():
            s = self.make_backup(5); b = bytearray(self.S.store[s + ".cms"]); b[10] ^= 1; self.S.store[s + ".cms"] = bytes(b)
        def c_manifiesto_corrupto():
            s = self.make_backup(5); self.S.store[s + ".manifest.json"] = b"basura"
        def c_firma_falsa(): self.make_backup(5, sign="forger")
        def c_sin_firma(): self.make_backup(5, sign=None)
        def c_vencido(): self.make_backup(500)
        def c_sin_huella(): self.make_backup(5, fp=False)
        def c_http_403(): self.make_backup(5); self.S.rules["*"] = [("status", 403)] * 50
        def c_http_503(): self.make_backup(5); self.S.rules["*"] = [("status", 503)] * 50
        def c_par_caducado(): self.make_backup(5); self.S.secret = "revocado"
        def c_objeto_enorme(): s = self.make_backup(5); self.S.rules[s + ".cms"] = [("huge",)]
        def c_red_cae(): s = self.make_backup(5); self.S.rules[s + ".cms"] = [("truncate",)] * 50
        for nombre, f in {"sin respaldos": c_sin_respaldos, "objeto alterado": c_objeto_alterado, "manifiesto corrupto": c_manifiesto_corrupto, "firma falsa": c_firma_falsa,
                          "sin firma": c_sin_firma, "vencido": c_vencido, "sin huella": c_sin_huella, "HTTP 403": c_http_403, "HTTP 503": c_http_503,
                          "PAR caducado": c_par_caducado, "objeto enorme": c_objeto_enorme, "la red cae": c_red_cae}.items():
            with self.subTest(nombre):
                self.setUp(); f()
                res, w = self.run_orch(); self.assert_blocked(res, w)

    def test_fallos_de_la_restauracion_misma_bloquean(self):
        self.make_backup(5)
        for nombre, kw in {"huella distinta": {"extra_env": {"SHIM_RES": "99"}}, "contraseña incorrecta": {"password": "equivocada-no-real"}, "sin contraseña": {"passin": ""}}.items():
            with self.subTest(nombre):
                res, w = self.run_orch(**kw); self.assert_blocked(res, w, "huella")
                self.assertNotIn(PASS, json.dumps(res)); self.assertNotIn("equivocada-no-real", json.dumps(res))
                self.assertNotIn(PAR_SECRET, json.dumps(res))

    def test_la_huella_y_la_antiguedad_siguen_mandando_aunque_la_procedencia_sea_valida(self):
        self.make_backup(400)                                # firmado, íntegro, pero fuera de RPO (el adaptador lo rechaza y el orquestador también)
        res, w = self.run_orch(); self.assert_blocked(res, w)

    def test_reintentos_no_duplican_efectos(self):
        stem = self.make_backup(5); self.S.rules["*"] = [("status", 503), ("status", 429)]
        res, w = self.run_orch()
        self.assertEqual(res["outcome"], "DONE"); self.assertEqual((w.restore_calls, w.dns_applied, w.enable_calls), (1, 1, 1))
        self.assertEqual([x for x in self.S.log if x.endswith(".cms")], [stem + ".cms"])      # el objeto se descargó una sola vez

    def test_el_adaptador_oci_no_habilita_nada_mas(self):
        a = oc.OciRecoveryAdapters(self.reader(), self.t / "k.pem", "env:NEXO_T_PASS", signer_pub=self.t / "sign.pub")
        for call in (a.precheck, a.probe_all, a.dns_apply, lambda: a.enable_standby(1), a.lease_acquire):
            with self.assertRaises(NotAuthorized): call()
        self.make_backup(5)
        r = a.restore_latest(); self.assertIn("fingerprint_ok", r)

    def test_no_lanza_ante_errores_inesperados(self):
        class Roto:
            def list_stems(self): raise RuntimeError("boom con detalle sensible " + PAR_SECRET)
        out = oc.restore_latest_from_oci(Roto(), self.t / "k.pem", "", signer_pub=self.t / "sign.pub")
        self.assertFalse(out["fingerprint_ok"]); self.assertNotIn(PAR_SECRET, json.dumps(out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
