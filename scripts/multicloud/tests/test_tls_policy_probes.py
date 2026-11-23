"""G9 — TLS de los extremos del failover cuyo certificado no coincide con el nombre de la URL: certificado FIJADO y validación contra otro nombre (`verify_as`), con servidores HTTPS reales en 127.0.0.1.
La verificación NUNCA se desactiva: cada caso negativo debe fallar de forma concluyente. Sin red externa, sin nube."""
import copy, http.server, json, ssl, subprocess, sys, tempfile, threading, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "failover")); sys.path.insert(0, str(HERE.parents[2] / "backend")); sys.path.insert(0, str(HERE))
import adapters_probes as ap  # noqa: E402
import failover_config as FC  # noqa: E402
import real_factory as RF  # noqa: E402
from test_real_factory import cfg_ok  # noqa: E402


def make_cert(d, name, cn="localhost"):
    crt, key = Path(d) / f"{name}.crt", Path(d) / f"{name}.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt), "-days", "2", "-subj", f"/CN={cn}", "-addext", f"subjectAltName=DNS:{cn}"], check=True, capture_output=True)
    return crt, key


class Srv:
    def __init__(self, crt, key, mode="enforce"):
        outer = self
        self.hosts = []
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hosts.append(self.headers.get("Host"))
                body = json.dumps({"mode": mode, "status": "ok", "holds_lease": False}).encode()          # compuerta en enforce SIN el lease ⇒ «vallado»
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *a): pass
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(crt, key)
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); self.srv.socket = ctx.wrap_socket(self.srv.socket, server_side=True)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.port = self.srv.server_address[1]

    def url(self, path="/livez"): return f"https://127.0.0.1:{self.port}{path}"
    def stop(self): self.srv.shutdown()


class TlsPolicyTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.crt, self.key = make_cert(self.d, "a"); self.crt2, _ = make_cert(self.d, "b"); self.s = Srv(self.crt, self.key); self.addCleanup(self.s.stop)

    def probe(self, tls=None, **kw): return ap.HttpProbe(self.s.url(), attempts=1, spacing_s=0, tls=tls, **kw).run()

    def test_con_certificado_fijado_y_verify_as_la_sonda_es_sana_y_envia_la_cabecera_host_correcta(self):
        self.assertIs(self.probe(ap.TlsPolicy("localhost", self.crt)), True); self.assertEqual(self.s.hosts[-1], "localhost")

    def test_sin_politica_el_autofirmado_se_rechaza_nunca_se_acepta(self):
        self.assertIs(self.probe(None), False)

    def test_nombre_equivocado_o_certificado_fijado_distinto_fallan(self):
        self.assertIs(self.probe(ap.TlsPolicy("otro.example", self.crt)), False)
        self.assertIs(self.probe(ap.TlsPolicy("localhost", self.crt2)), False)        # otro certificado fijado: este servidor no es de confianza

    def test_solo_verify_as_con_ca_publicas_rechaza_un_autofirmado(self):
        self.assertIs(self.probe(ap.TlsPolicy("localhost")), False)

    def test_gate_status_usa_la_politica(self):
        self.assertEqual(ap.gate_status(self.s.url("/write-gate"), tls=ap.TlsPolicy("localhost", self.crt)), "vallado")
        self.assertIsNone(ap.gate_status(self.s.url("/write-gate")))                    # sin política: inalcanzable (TLS) ⇒ desconocido, no «escribe»
        self.assertIsNone(ap.gate_status(self.s.url("/write-gate"), tls=ap.TlsPolicy("otro.example", self.crt)))

    def test_json_ok_y_http_plano_siguen_funcionando_con_politica(self):
        self.assertIs(self.probe(ap.TlsPolicy("localhost", self.crt), json_ok=lambda d: d.get("status") == "ok"), True)
        self.assertIsNone(ap.HttpProbe("http://example.com/livez", tls=ap.TlsPolicy("localhost", self.crt)).run())      # http remoto: inválida

    def test_politica_invalida(self):
        for args in (dict(), dict(verify_as="a b"), dict(verify_as="x;y"), dict(cafile="relativa.pem"), dict(cafile="/no/existe.pem")):
            with self.assertRaises(ValueError): ap.TlsPolicy(**args)
        with self.assertRaises(ValueError): ap.TlsPolicy.from_config({"verify": False})
        with self.assertRaises(ValueError): ap.TlsPolicy.from_config({"verify_as": "x.example", "insecure": True})
        self.assertIsNone(ap.TlsPolicy.from_config(None))

    def test_el_codigo_no_desactiva_la_verificacion(self):
        src = (HERE.parent / "failover/adapters_probes.py").read_text()
        for malo in ("CERT_NONE", "_create_unverified_context", "check_hostname = False", "verify=False"): self.assertNotIn(malo, src)


class ConfigAndFactory(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.crt, _ = make_cert(self.d, "p"); self.crt2, _ = make_cert(self.d, "s")

    def cfg(self):
        c = cfg_ok(); c["primary"]["tls"] = {"verify_as": "nexoeventos-demo.duckdns.org"}; c["standby"]["tls"] = {"verify_as": "localhost", "cafile": str(self.crt2)}; return c

    def test_la_fabrica_propaga_la_politica_a_sondas_y_compuertas(self):
        kw = RF.derive_kwargs(self.cfg(), check_files=True)
        self.assertEqual(kw["primary_tls"].verify_as, "nexoeventos-demo.duckdns.org"); self.assertIsNone(kw["primary_tls"].cafile)
        self.assertEqual(kw["standby_tls"].cafile, self.crt2)
        self.assertTrue(all(p.tls is kw["primary_tls"] for p in kw["probes"].probes)); self.assertIsNone(kw["probes"].control.tls)       # el control usa CA públicas
        self.assertTrue(all(p.tls is kw["standby_tls"] for p in kw["standby_readiness_probes"].values())); self.assertIs(kw["standby_health"].tls, kw["standby_tls"])

    def test_sin_tls_en_la_configuracion_todo_queda_como_antes(self):
        kw = RF.derive_kwargs(cfg_ok(), check_files=False); self.assertIsNone(kw["primary_tls"]); self.assertIsNone(kw["standby_tls"]); self.assertTrue(all(p.tls is None for p in kw["probes"].probes))

    def test_los_adaptadores_construidos_reciben_la_politica_para_las_compuertas(self):
        from test_real_factory import providers
        a = RF.build_adapters(self.cfg(), providers(), check_files=False)         # los archivos de la configuración de ejemplo no existen; el certificado fijado de TLS sí
        self.assertEqual(a.primary_tls.verify_as, "nexoeventos-demo.duckdns.org"); self.assertEqual(a.standby_tls.cafile, self.crt2)

    def test_la_validacion_rechaza_tls_inseguro_o_incompleto(self):
        base = FC.validate(self.cfg(), check_files=False); malos = []
        for side in ("primary", "standby"):
            for t in ({"verify": False}, {"verify_as": "x.example", "insecure": True}, {}, {"verify_as": "a b"}, {"cafile": "relativo.pem"}, {"cafile": "/no/existe.pem"}):
                c = self.cfg(); c[side]["tls"] = t; r = FC.validate(c, check_files=True); malos.append((side, t, [e for e in r["errors"] if "tls" in str(e)]))
        for side, t, errs in malos: self.assertTrue(errs, (side, t))
        ok = FC.validate(self.cfg(), check_files=True); self.assertFalse([e for e in ok["errors"] if "tls" in str(e)])


if __name__ == "__main__":
    unittest.main()
