#!/usr/bin/env python3
"""Prueba LOCAL (sin nubes) de backup_cycle.py (B-14) y backup_freshness.py (B-20): servidor HTTP falso en 127.0.0.1 que imita un PAR de escritura
(PUT con If-None-Match), claves desechables en un directorio temporal y un volcado simulado. No usa AWS, OCI ni red externa.
Uso: backend/.venv/bin/python scripts/multicloud/test_backup_cycle.py"""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_cycle as bc  # noqa: E402
import backup_freshness as bf  # noqa: E402

PAR_SECRET = "p/SECRETO-DEL-PAR-NO-DEBE-APARECER/n/ns/b/bucket/o"
PLAIN = b"PGDMP" + bytes(range(256)) * 40  # volcado simulado


class FakeBucket(BaseHTTPRequestHandler):
    store: dict = {}
    requests: list = []
    fail_next: list = []  # códigos HTTP a devolver antes de aceptar

    def do_PUT(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        type(self).requests.append({"path": self.path, "inm": self.headers.get("If-None-Match"), "n": len(body)})
        if type(self).fail_next:
            self.send_response(type(self).fail_next.pop(0)); self.end_headers(); return
        if self.path in type(self).store and self.headers.get("If-None-Match") == "*":
            self.send_response(412); self.end_headers(); return
        type(self).store[self.path] = body
        self.send_response(200); self.end_headers()

    def log_message(self, *a):
        pass


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.key, cls.crt = t / "k.pem", t / "c.crt"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(cls.key), "-out", str(cls.crt), "-days", "2",
                        "-subj", "/CN=prueba-local"], check=True, capture_output=True)
        cls.dump_file = t / "dump.bin"
        cls.dump_file.write_bytes(PLAIN)
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeBucket)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/{PAR_SECRET}/"
        cls.par = t / "par.url"
        cls.par.write_text(cls.url)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.tmp.cleanup()

    def setUp(self):
        FakeBucket.store.clear(); FakeBucket.requests.clear(); FakeBucket.fail_next.clear()
        self.state = Path(tempfile.mkdtemp(dir=self.tmp.name))

    def run_cycle(self, *extra, dump=None, par=None, cert=None):
        pin = [] if ("--cert-sha256" in extra or "--allow-unpinned-cert" in extra) else ["--cert-sha256", bc.cert_fingerprint(str(cert or self.crt))]
        argv = [*pin, "--cert", str(cert or self.crt), "--par-url-file", str(par or self.par), "--state-dir", str(self.state),
                "--dump-cmd", dump or f"cat {self.dump_file}", "--backoff", "0", "--allow-http-localhost", "--env", "test-env", *extra]
        err = io.StringIO()
        with redirect_stderr(err):
            rc = bc.main(argv)
        return rc, err.getvalue()

    def records(self):
        p = self.state / "cycles.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


class TestPrefixScope(Base):
    """C-04: con un PAR cuyo objeto es un PREFIJO (`.../o/backups/c04-20261119/`), todo lo que sube el ciclo cae dentro de ese prefijo: exactamente 3 objetos (cifrado,
    manifiesto, firma), con nombre simple, sin `..`, sin `//` y sin salir del alcance autorizado."""
    PREFIX = "n/espacio/b/bucket/o/backups/c04-20261119/"

    def test_todas_las_escrituras_quedan_dentro_del_prefijo_del_par(self):
        sign = Path(self.tmp.name) / "firma.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(sign)], check=True, capture_output=True)
        par = Path(self.tmp.name) / "par-prefijo.url"
        par.write_text(self.url + self.PREFIX)
        rc, err = self.run_cycle("--sign-key", str(sign), par=par)
        self.assertEqual(rc, 0, err)
        base = "/" + PAR_SECRET + "/" + self.PREFIX
        paths = [r["path"] for r in FakeBucket.requests]
        self.assertEqual(len(paths), 3, paths)
        for path in paths:
            self.assertTrue(path.startswith(base), path)
            name = path[len(base):]
            self.assertRegex(name, r"^nexoeventos-rds-\d{8}T\d{6}Z\.(cms|manifest\.json|manifest\.json\.sig)$")
            self.assertNotIn("..", name); self.assertNotIn("/", name)
        self.assertTrue(all(r["inm"] == "*" for r in FakeBucket.requests))
        self.assertTrue(any(p.endswith(".manifest.json.sig") for p in paths))  # la firma se sube (procedencia)
        self.assertNotIn(PAR_SECRET, err)


class TestPrefixEnforcedByServer(Base):
    """C-04 (19-nov): el access-uri real termina en `/o/`. El prefijo debe ir en el NOMBRE (`--object-prefix backups/c04-20261119/`); con el prefijo por defecto los PUT
    quedarían fuera del alcance del PAR, y con `--object-prefix` el resultado es idéntico a una URL que ya lo trajera."""
    BASE = "n/espacio/b/bucket/o/"
    PFX = "backups/c04-20261119/"

    def _run(self, prefix):
        sign = Path(self.tmp.name) / "firma.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(sign)], check=True, capture_output=True)
        par = Path(self.tmp.name) / "par-o.url"
        par.write_text(self.url + self.BASE)
        rc, err = self.run_cycle("--sign-key", str(sign), *prefix, par=par)
        return rc, err, [r["path"] for r in FakeBucket.requests]

    def test_url_terminada_en_o_con_prefijo_en_el_nombre_equivale_a_url_con_prefijo(self):
        rc, err, paths = self._run(["--object-prefix", self.PFX])
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(paths), 3, paths)
        base = "/" + PAR_SECRET + "/" + self.BASE + self.PFX
        for p in paths:
            self.assertTrue(p.startswith(base), p)
            self.assertRegex(p[len(base):], r"^nexoeventos-rds-\d{8}T\d{6}Z\.(cms|manifest\.json|manifest\.json\.sig)$")
            self.assertNotIn("..", p); self.assertNotIn("//", p.replace("/" + PAR_SECRET + "/", ""))

    def test_object_prefix_invalido_se_rechaza(self):
        for malo in ("../x/", "a//b/", "sin-barra-final", "/abs/", "a b/"):
            rc, err, paths = self._run(["--object-prefix", malo])
            self.assertEqual(rc, 2, malo); self.assertEqual(paths, [])

    def test_con_el_prefijo_por_defecto_los_objetos_quedan_fuera_del_prefijo_autorizado(self):
        rc, err, paths = self._run([])
        self.assertTrue(paths and not any(("/" + self.BASE + self.PFX) in p for p in paths))  # el riesgo que el control previo de c04-par-check.sh debe detectar


class TestCertificateIdentity(Base):
    """Identidad explícita del certificado destinatario: se fija por su huella SHA-256 (no por el nombre del archivo) y cualquier otro se rechaza ANTES de volcar nada.
    Caso real del 19-nov: se usó `CN=NexoEventos backup recovery` creyendo que era el certificado de OCI."""

    def _other_cert(self):
        key, crt = Path(self.tmp.name) / "otra.key", Path(self.tmp.name) / "otra.crt"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt), "-subj", "/CN=NexoEventos OCI recovery", "-days", "2"], check=True, capture_output=True)
        return crt

    def test_huella_correcta_se_acepta_en_cualquier_formato_y_queda_en_el_manifiesto(self):
        fp = bc.cert_fingerprint(str(self.crt))
        colons = ":".join(fp[i:i + 2] for i in range(0, 64, 2)).upper()
        rc, err = self.run_cycle("--cert-sha256", colons)
        self.assertEqual(rc, 0, err)
        man = [json.loads(v) for k, v in FakeBucket.store.items() if k.endswith(".manifest.json")]
        self.assertEqual(man[0]["recipient_cert_sha256"], fp)

    def test_certificado_distinto_se_rechaza_antes_de_volcar_o_subir(self):
        rc, err = self.run_cycle("--cert-sha256", bc.cert_fingerprint(str(self._other_cert())), dump="echo NO-DEBE-EJECUTARSE >&2; false")
        self.assertEqual(rc, 2, err)
        self.assertIn("NO tiene la huella esperada", err); self.assertNotIn("NO-DEBE-EJECUTARSE", err)
        self.assertEqual(FakeBucket.requests, [])

    def test_sin_huella_fijada_se_rechaza_salvo_compatibilidad_explicita(self):
        rc, err = self.run_cycle("--allow-unpinned-cert", "--cert-sha256", "")  # vacío + flag de compatibilidad = comportamiento anterior
        self.assertEqual(rc, 0, err)
        argv = ["--cert", str(self.crt), "--par-url-file", str(self.par), "--state-dir", str(self.state), "--dump-cmd", f"cat {self.dump_file}", "--allow-http-localhost", "--env", "test-env"]
        e = io.StringIO()
        with redirect_stderr(e):
            self.assertEqual(bc.main(argv), 2)
        self.assertIn("falta cert_sha256", e.getvalue())

    def test_huella_con_formato_invalido_se_rechaza(self):
        for malo in ("abc", "z" * 64, "12:34"):
            rc, err = self.run_cycle("--cert-sha256", malo)
            self.assertEqual(rc, 2, malo)


class TestBackupCycle(Base):
    def test_exito_cifrado_sin_claro_y_sin_secretos(self):
        rc, err = self.run_cycle()
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(FakeBucket.store), 2)  # cifrado + manifiesto
        (path, blob), = [(k, v) for k, v in FakeBucket.store.items() if k.endswith(".cms")]
        self.assertTrue(all(r["inm"] == "*" for r in FakeBucket.requests))  # sin sobrescritura en ningún objeto
        self.assertNotIn(PLAIN[:32], blob)  # el objeto remoto no contiene el volcado en claro
        out = subprocess.run(["openssl", "cms", "-decrypt", "-inform", "DER", "-inkey", str(self.key), "-recip", str(self.crt)], input=blob,
                             capture_output=True, check=True).stdout
        self.assertEqual(out, PLAIN)  # descifra con la clave privada
        # nada en disco más que el registro: ni el .cms ni el volcado
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["cycle.lock", "cycles.jsonl"])
        self.assertNotIn("SECRETO", err)
        self.assertNotIn("SECRETO", (self.state / "cycles.jsonl").read_text())
        rec = self.records()[-1]
        self.assertTrue(rec["ok"]); self.assertEqual(len(rec["cms_sha256"]), 64)
        self.assertEqual((self.state / "cycles.jsonl").stat().st_mode & 0o777, 0o600)

    def test_objeto_existente_no_se_sobrescribe_ni_se_reintenta(self):
        rc1, _ = self.run_cycle()
        self.assertEqual(rc1, 0)
        existing = dict(FakeBucket.store)
        self.assertEqual(len(existing), 2)
        n = len(FakeBucket.requests)
        # mismo segundo => mismo nombre: forzamos la colisión con un reloj fijo
        orig = bc.run_cycle
        name = next(k for k in existing if k.endswith(".cms")).rsplit("/", 1)[1]
        ts = name.rsplit("-", 1)[1][:-4]
        when = datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        ns = bc.argparse.Namespace(cert=str(self.crt), par_url_file=str(self.par), state_dir=str(self.state), dump_cmd=f"cat {self.dump_file}",
                                   prefix="nexoeventos-rds", retries=3, backoff=0, timeout=10, allow_http_localhost=True, env="test-env", allow_non_pgdmp=False, fingerprint_cmd=None)
        with self.assertRaises(bc.CycleError) as cm:
            orig(ns, now=lambda: when)
        self.assertIn("412", str(cm.exception))
        self.assertEqual(len(FakeBucket.requests), n + 1)  # un solo intento: error permanente
        self.assertEqual(FakeBucket.store, existing)  # intacto

    def test_reintenta_ante_503_transitorio(self):
        FakeBucket.fail_next[:] = [503, 503]
        rc, err = self.run_cycle()
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(FakeBucket.requests), 4)  # 2 fallos + cifrado + manifiesto
        self.assertEqual(len(FakeBucket.store), 2)
        self.assertEqual(self.records()[-1]["attempts"], 3)

    def test_agota_reintentos_y_registra_fallo(self):
        FakeBucket.fail_next[:] = [503] * 10
        rc, err = self.run_cycle("--retries", "2")
        self.assertEqual(rc, 1)
        self.assertEqual(len(FakeBucket.requests), 3)
        self.assertFalse(FakeBucket.store)
        self.assertFalse(self.records()[-1]["ok"])
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["cycle.lock", "cycles.jsonl"])  # sin .part

    def test_volcado_fallido_no_sube_nada(self):
        rc, err = self.run_cycle(dump="echo PGDMP-parcial; exit 3")
        self.assertEqual(rc, 1)
        self.assertFalse(FakeBucket.requests)
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["cycle.lock", "cycles.jsonl"])

    def test_exige_https_salvo_localhost_de_prueba(self):
        bad = Path(self.tmp.name) / "bad.url"
        bad.write_text("http://ejemplo.invalid/p/x/n/y/b/z/o/")
        rc, err = self.run_cycle(par=bad)
        self.assertEqual(rc, 1)
        self.assertIn("HTTPS", err)
        self.assertFalse(FakeBucket.requests)

    def test_rechaza_certificado_con_clave_privada(self):
        both = Path(self.tmp.name) / "both.pem"
        both.write_text(self.crt.read_text() + self.key.read_text())
        rc, err = self.run_cycle(cert=both)
        self.assertEqual(rc, 1)
        self.assertFalse(FakeBucket.requests)


class TestCycleHardening(Base):
    def test_manifiesto_verificable_con_verify_transfer(self):
        rc, err = self.run_cycle()
        self.assertEqual(rc, 0, err)
        (mpath, mblob), = [(k, v) for k, v in FakeBucket.store.items() if k.endswith(".manifest.json")]
        (cpath, cblob), = [(k, v) for k, v in FakeBucket.store.items() if k.endswith(".cms")]
        m = json.loads(mblob)
        self.assertEqual(m["env"], "test-env")
        self.assertEqual(m["plaintext_dump_sha256"], hashlib.sha256(PLAIN).hexdigest())
        self.assertEqual(m["oci_cms_sha256"], hashlib.sha256(cblob).hexdigest())
        self.assertEqual(m["oci_cms_bytes"], len(cblob))
        d = Path(self.tmp.name) / "dl"; d.mkdir(exist_ok=True)
        (d / "o.cms").write_bytes(cblob); (d / "o.manifest.json").write_bytes(mblob)
        r = subprocess.run([str(ROOT / "scripts/multicloud/verify-transfer.sh"), str(d / "o.manifest.json"), str(d / "o.cms")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)  # el mismo verificador que usa la restauración
        self.assertNotIn("SECRETO", mblob.decode())

    def test_huella_antes_y_despues_va_al_manifiesto(self):
        rc, err = self.run_cycle("--fingerprint-cmd", "echo alembic=0008; echo reservations=7")
        self.assertEqual(rc, 0, err)
        (_, mblob), = [(k, v) for k, v in FakeBucket.store.items() if k.endswith(".manifest.json")]
        m = json.loads(mblob)
        self.assertEqual(m["fingerprint_before"], {"alembic": "0008", "reservations": "7"}); self.assertEqual(m["fingerprint_after"], m["fingerprint_before"])

    def test_huella_que_falla_o_sale_vacia_aborta_sin_subir(self):
        for cmd in ("exit 4", "echo sin-clave-valor"):
            FakeBucket.requests.clear()
            rc, err = self.run_cycle("--fingerprint-cmd", cmd)
            self.assertEqual(rc, 1); self.assertIn("huella", err); self.assertFalse(FakeBucket.requests)

    def test_manifiesto_firmado_para_procedencia(self):
        k = Path(self.tmp.name) / "sign.pem"; pub = Path(self.tmp.name) / "sign.pub"
        subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(k)], check=True, capture_output=True)
        subprocess.run(["openssl", "ec", "-in", str(k), "-pubout", "-out", str(pub)], check=True, capture_output=True); os.chmod(k, 0o600)
        rc, err = self.run_cycle("--sign-key", str(k)); self.assertEqual(rc, 0, err)
        (mp, mblob), = [(x, v) for x, v in FakeBucket.store.items() if x.endswith(".manifest.json")]
        (_, sig), = [(x, v) for x, v in FakeBucket.store.items() if x.endswith(".manifest.json.sig")]
        # openssl lee la firma de un archivo
        sf = Path(self.tmp.name) / "m.sig"; sf.write_bytes(sig)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(sf)], input=mblob, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(sf)], input=mblob + b" ", capture_output=True)
        self.assertNotEqual(r.returncode, 0)                           # manifiesto alterado: la firma no vale
        self.assertTrue(FakeBucket.requests[-1]["path"].endswith(".sig"))   # la firma se sube la ÚLTIMA

    def test_clave_de_firma_invalida_aborta_antes_de_publicar_la_firma(self):
        k = Path(self.tmp.name) / "mala.pem"; k.write_text("no es una clave"); os.chmod(k, 0o600)
        rc, err = self.run_cycle("--sign-key", str(k)); self.assertEqual(rc, 1)
        self.assertFalse(any(x.endswith(".sig") for x in FakeBucket.store)); self.assertFalse(self.records()[-1]["ok"])
        k2 = Path(self.tmp.name) / "abierta.pem"; k2.write_text("-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n"); os.chmod(k2, 0o644)
        FakeBucket.store.clear(); rc, err = self.run_cycle("--sign-key", str(k2)); self.assertEqual(rc, 1); self.assertIn("0600", err)

    def test_volcado_sin_cabecera_pgdmp_no_se_sube(self):
        for cmd in ("printf ''", "printf 'esto no es un volcado de postgres, tiene mas de sesenta y cuatro bytes de largo para pasar el minimo'"):
            FakeBucket.requests.clear()
            rc, err = self.run_cycle(dump=cmd)
            self.assertEqual(rc, 1); self.assertIn("PGDMP", err); self.assertFalse(FakeBucket.requests)

    def test_ciclo_solapado_no_hace_nada(self):
        import fcntl, os
        fd = os.open(self.state / "cycle.lock", os.O_WRONLY | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            rc, err = self.run_cycle()
        finally:
            os.close(fd)
        self.assertEqual(rc, 3); self.assertIn("en curso", err); self.assertFalse(FakeBucket.requests)
        rc2, _ = self.run_cycle()  # liberado el bloqueo, vuelve a funcionar
        self.assertEqual(rc2, 0)

    def test_manifiesto_rechazado_marca_fallo_y_no_cuenta_como_fresco(self):
        FakeBucket.fail_next[:] = []
        orig = FakeBucket.do_PUT
        def falla_manifiesto(h):
            if h.path.endswith(".manifest.json"):
                n = int(h.headers.get("Content-Length", 0)); h.rfile.read(n); FakeBucket.requests.append({"path": h.path, "inm": "*", "n": n})
                h.send_response(403); h.end_headers(); return
            orig(h)
        FakeBucket.do_PUT = falla_manifiesto
        try:
            rc, err = self.run_cycle()
        finally:
            FakeBucket.do_PUT = orig
        self.assertEqual(rc, 1); self.assertIn("manifiesto", err)
        self.assertFalse(self.records()[-1]["ok"])
        self.assertEqual(bf.evaluate(self.state, 90, datetime.now(timezone.utc), "test-env")[0], 1)

    def test_configuracion_por_entorno_y_prioridad_de_la_linea_de_ordenes(self):
        cfg = Path(self.tmp.name) / "aws-academy.json"
        cfg.write_text(json.dumps({"env": "aws-academy", "cert": str(self.crt), "cert_sha256": bc.cert_fingerprint(str(self.crt)), "par_url_file": str(self.par), "state_dir": str(self.state),
                                   "dump_cmd": f"cat {self.dump_file}", "retries": 1, "backoff": 0}))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = bc.main(["--config", str(cfg), "--allow-http-localhost"])
        self.assertEqual(rc, 0, err.getvalue())
        self.assertEqual(self.records()[-1]["env"], "aws-academy")
        self.assertEqual(bc.parse_args(["--config", str(cfg)]).env, "aws-academy")
        a = bc.parse_args(["--config", str(cfg), "--env", "oci-recuperacion", "--retries", "0"])  # la línea de órdenes tiene prioridad
        self.assertEqual((a.env, a.retries, a.prefix), ("oci-recuperacion", 0, "nexoeventos-rds"))

    def test_configuracion_invalida(self):
        t = Path(self.tmp.name)
        casos = {"par_url en línea": {"env": "x", "par_url": "https://x/p/SECRETO/"}, "clave desconocida": {"env": "x", "otra": 1}}
        for nombre, cfg in casos.items():
            (t / "c.json").write_text(json.dumps(cfg))
            err = io.StringIO()
            with redirect_stderr(err):
                rc = bc.main(["--config", str(t / "c.json")])
            self.assertEqual(rc, 2, nombre); self.assertNotIn("SECRETO", err.getvalue())
        for argv in (["--env", "AWS_Mayus", "--cert", "x", "--par-url-file", "x", "--state-dir", str(self.state)],
                     ["--env", "ok", "--cert", "x", "--par-url-file", "x", "--state-dir", str(self.state), "--retries", "99"],
                     ["--env", "ok"]):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(bc.main(argv), 2, argv)

    def test_integracion_respaldo_a_restauracion_con_clave_protegida(self):
        """Cierra el círculo B-14 + S-01: el objeto y el manifiesto que sube el ciclo se restauran con restore-drill.sh y una clave protegida."""
        t = Path(self.tmp.name) / "integ"; t.mkdir(exist_ok=True)
        env = {**os.environ, "KP": "frase-de-prueba-no-real"}
        for cmd in (["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-aes-256-cbc", "-pass", "env:KP", "-out", str(t / "k.pem")],
                    ["openssl", "req", "-x509", "-new", "-key", str(t / "k.pem"), "-passin", "env:KP", "-days", "2", "-subj", "/CN=i", "-out", str(t / "c.crt")]):
            r = subprocess.run(cmd, capture_output=True, env=env, stdin=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 0, f"{cmd[1]}: {r.stderr.decode(errors='replace')[:300]} | KP en env={'KP' in env} | openssl={subprocess.run(['which','openssl'],capture_output=True,text=True).stdout.strip()}")
        rc, err = self.run_cycle(cert=t / "c.crt")
        self.assertEqual(rc, 0, err)
        for k, v in FakeBucket.store.items():
            (t / ("o.cms" if k.endswith(".cms") else "o.manifest.json")).write_bytes(v)
        shim = t / "shim"; shim.mkdir(exist_ok=True)
        (shim / "psql").write_text('#!/usr/bin/env bash\nif [[ "$*" == *"-d drill"* && "$*" == *"-At"* ]]; then echo "reservations=3"; fi\nexit 0\n')
        (shim / "pg_restore").write_text('#!/usr/bin/env bash\nif [[ "$1" == "--list" ]]; then echo "; toc"; echo "1; 0 0 TABLE x"; fi\ncat >/dev/null\nexit 0\n')
        for f in shim.iterdir():
            f.chmod(0o755)
        (t / "base.json").write_text(json.dumps({"baselines": {"k": {"fingerprint": {"reservations": "3"}}}}))
        def drill(passin):
            e = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}", "NEXO_T_PASS": "frase-de-prueba-no-real"}
            return subprocess.run([str(ROOT / "scripts/multicloud/restore-drill.sh"), "--manifest", str(t / "o.manifest.json"), "--cms", str(t / "o.cms"), "--key", str(t / "k.pem"),
                                   "--baseline", str(t / "base.json"), "--baseline-key", "k", "--mode", "local", *passin], capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL, timeout=60)
        ok = drill(["--passin", "env:NEXO_T_PASS"])
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("SHA-256 del cifrado coincide", ok.stdout); self.assertIn("hash del volcado en claro coincide", ok.stdout)
        self.assertNotEqual(drill([]).returncode, 0)  # sin contraseña: falla, no se cuelga


class TestFreshness(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)

    def write(self, *recs):
        (self.d / "cycles.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")

    def rec(self, minutes_ago, ok=True):
        return {"ok": ok, "finished_at": (self.now - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def test_fresco(self):
        self.write(self.rec(120), self.rec(20))
        self.assertEqual(bf.evaluate(self.d, 90, self.now)[0], 0)

    def test_caduco(self):
        self.write(self.rec(200))
        code, msg = bf.evaluate(self.d, 90, self.now)
        self.assertEqual(code, 1); self.assertIn("CADUCO", msg)

    def test_fallo_reciente_no_oculta_respaldo_viejo(self):
        self.write(self.rec(200), self.rec(5, ok=False))
        self.assertEqual(bf.evaluate(self.d, 90, self.now)[0], 1)

    def test_filtro_por_entorno_no_deja_que_otro_entorno_oculte_la_caducidad(self):
        a = dict(self.rec(10), env="aws-academy"); b = dict(self.rec(500), env="oci-recuperacion")
        self.write(a, b)
        self.assertEqual(bf.evaluate(self.d, 90, self.now, "aws-academy")[0], 0)
        self.assertEqual(bf.evaluate(self.d, 90, self.now, "oci-recuperacion")[0], 1)
        self.assertEqual(bf.evaluate(self.d, 90, self.now, "otro-entorno")[0], 1)  # sin ciclos propios = caduco, no fresco

    def test_informe_de_rpo(self):
        def r(start_min_ago, dur_s):
            s = self.now - timedelta(minutes=start_min_ago); f = s + timedelta(seconds=dur_s)
            return {"ok": True, "env": "e", "started_at": s.strftime("%Y-%m-%dT%H:%M:%SZ"), "finished_at": f.strftime("%Y-%m-%dT%H:%M:%SZ"), "duration_s": dur_s}
        self.write(r(100, 30), r(70, 40), r(40, 20))  # huecos de 30 min; el peor caso = hueco + duración del siguiente
        rep = bf.rpo_report(bf.read_records(self.d, "e"), self.now)
        self.assertEqual(rep["cycles_ok"], 3); self.assertEqual(rep["gap_min_max"], 30.0)
        self.assertAlmostEqual(rep["rpo_worst_case_min"], 30 + 40 / 60, places=1)
        self.assertEqual(rep["since_last_data_snapshot_min"], 40.0)

    def test_config_y_report_por_cli(self):
        cfgf = self.d / "cfg.json"; cfgf.write_text(json.dumps({"state_dir": str(self.d), "env": "aws-academy", "max_age_min": 90}))
        self.write(dict(self.rec(10), env="aws-academy"))
        self.assertEqual(bf.main(["--config", str(cfgf), "--now", self.now.strftime("%Y-%m-%dT%H:%M:%SZ")]), 0)
        self.assertEqual(bf.main(["--config", str(cfgf), "--report", "--now", self.now.strftime("%Y-%m-%dT%H:%M:%SZ")]), 0)
        self.assertEqual(bf.main(["--state-dir", str(self.d)]), 2)

    def test_fallo_reciente_con_respaldo_fresco_sigue_fresco(self):
        self.write(self.rec(30), self.rec(5, ok=False))
        code, msg = bf.evaluate(self.d, 90, self.now)
        self.assertEqual(code, 0); self.assertIn("falló", msg)

    def test_sin_registro_es_desconocido(self):
        self.assertEqual(bf.evaluate(self.d, 90, self.now)[0], 2)

    def test_registro_ilegible_y_reloj_futuro(self):
        (self.d / "cycles.jsonl").write_text("no es json\n")
        self.assertEqual(bf.evaluate(self.d, 90, self.now)[0], 2)
        self.write(self.rec(-10))
        self.assertEqual(bf.evaluate(self.d, 90, self.now)[0], 2)

    def test_solo_fallos(self):
        self.write(self.rec(5, ok=False))
        self.assertEqual(bf.evaluate(self.d, 90, self.now)[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
