"""Regresión de T2 (22-nov): el Python del entorno no traía almacén de certificados y las llamadas HTTPS fallaban. El contexto verificado debe (1) caer a certifi SOLO si no hay CA cargada,
(2) respetar SSL_CERT_FILE, (3) NUNCA desactivar la verificación (un servidor con certificado no confiable sigue rechazándose), y (4) estar en TODOS los clientes HTTPS del failover."""
import datetime, ipaddress, os, ssl, sys, threading, unittest, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[2]
for p in (ROOT / "backend", HERE.parent / "failover", HERE.parent):
    sys.path.insert(0, str(p))
from app.failover import tlsctx  # noqa: E402
import adapters_probes as AP  # noqa: E402
import dns_switch as DS  # noqa: E402


class Stub:
    def __init__(self, certs): self._c = certs
    def get_ca_certs(self): return self._c


def selfsigned(tmp):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    k = ec.generate_private_key(ec.SECP256R1()); n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]); now = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
         .not_valid_after(now + datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
         .add_extension(x509.BasicConstraints(ca=True, path_length=None), True).sign(k, hashes.SHA256()))
    cf, kf = Path(tmp) / "c.pem", Path(tmp) / "k.pem"
    cf.write_bytes(c.public_bytes(serialization.Encoding.PEM)); kf.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())); return cf, kf


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self): self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"OK")


class Contexto(unittest.TestCase):
    def copies(self): return {"tlsctx": tlsctx.verified_ssl_context, "adapters_probes": AP._verified_ctx, "dns_switch": DS._verified_ctx}

    def test_sin_ca_cargada_usa_certifi_y_con_ca_cargada_no(self):
        import certifi
        for name, fn in self.copies().items():
            calls = []
            def fake(cafile=None, **k): calls.append(cafile); return Stub(["x"] if cafile else [])
            with mock.patch("ssl.create_default_context", fake): fn()
            self.assertEqual(calls, [None, certifi.where()], name)                  # sin CA: segundo intento con certifi
            calls.clear()
            with mock.patch("ssl.create_default_context", lambda cafile=None, **k: (calls.append(cafile), Stub(["ca"]))[1]): fn()
            self.assertEqual(calls, [None], name)                                   # con CA del sistema: no se toca

    def test_sin_certifi_se_sigue_verificando(self):
        import builtins
        real = builtins.__import__
        def no_certifi(n, *a, **k):
            if n == "certifi": raise ImportError
            return real(n, *a, **k)
        for name, fn in self.copies().items():
            with mock.patch("ssl.create_default_context", lambda cafile=None, **k: Stub([])), mock.patch("builtins.__import__", no_certifi): ctx = fn()
            self.assertIsInstance(ctx, Stub, name)                                  # devuelve el contexto por defecto (verificador); no un contexto sin verificar

    def test_verificacion_activa_certificado_no_confiable_se_rechaza_y_ssl_cert_file_se_respeta(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cf, kf = selfsigned(d); srv = ThreadingHTTPServer(("127.0.0.1", 0), H); sc = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); sc.load_cert_chain(cf, kf)
            srv.socket = sc.wrap_socket(srv.socket, server_side=True); threading.Thread(target=srv.serve_forever, daemon=True).start(); url = f"https://localhost:{srv.server_port}/"
            try:
                for name, fn in self.copies().items():
                    ctx = fn(); self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED, name); self.assertTrue(ctx.check_hostname, name)
                    with self.assertRaises(urllib.error.URLError, msg=name): urllib.request.urlopen(url, timeout=5, context=ctx)            # autofirmado NO confiable: se rechaza
                with mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(cf)}):
                    for name, fn in self.copies().items():
                        self.assertEqual(urllib.request.urlopen(url, timeout=5, context=fn()).read(), b"OK", name)                         # SSL_CERT_FILE confía en ese certificado
            finally: srv.shutdown()

    def test_dns_switch_usa_el_contexto_verificado_por_defecto(self):
        seen = {}
        def fake_urlopen(url, timeout=None, context=None):
            seen["ctx"] = context; raise urllib.error.URLError("simulado")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(DS.Refused): DS.duckdns_update("nexoeventos-test", "93.184.216.34", "tok-abcdef0123456789", DS.API_BASE)
        self.assertIsNotNone(seen["ctx"]); self.assertEqual(seen["ctx"].verify_mode, ssl.CERT_REQUIRED)

    def test_los_clientes_https_del_failover_construyen_su_opener_con_contexto_verificado(self):
        import tempfile, stat
        from app.failover.store import ParHttpStore
        with tempfile.TemporaryDirectory() as d:
            par = Path(d) / "p.url"; par.write_text("https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/X/n/ns/b/bk/o/lease.json"); os.chmod(par, 0o600)
            st = ParHttpStore(par); handlers = [h for h in st._opener.handlers if isinstance(h, urllib.request.HTTPSHandler)]
            self.assertTrue(handlers and handlers[0]._context.verify_mode == ssl.CERT_REQUIRED)
        self.assertTrue([h for h in AP._OPENER.handlers if isinstance(h, urllib.request.HTTPSHandler)][0]._context.verify_mode == ssl.CERT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
