import http.server, os, sys, tempfile, threading, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/multicloud/hybrid")); import hybrid_par as P  # noqa: E402

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
B_OK = {"public-access-type": "NoPublicAccess", "versioning": "Enabled"}
def par(obj="hybrid-test/writer-lease.json", acc="ObjectReadWrite", h=3, **kw):
    return {"name": "t", "object-name": obj, "access-type": acc, "time-expires": (NOW + timedelta(hours=h)).isoformat(), "bucket-listing-action": "Deny", **kw}


class Audit(unittest.TestCase):
    def test_conjunto_correcto(self):
        r = P.audit([par(), par("hybrid-test/fence-attestation.json")], B_OK, NOW); self.assertTrue(r["ok"], r)
        self.assertTrue(P.audit([], B_OK, NOW)["ok"])                                         # 0 PAR (tras revocar) es válido
    def test_detecta_cada_exceso(self):
        casos = {"prefijo completo": par(None, "AnyObjectReadWrite"), "backups": par("backups/database/x.cms"), "secrets": par("secrets/k"), "caduca tarde": par(h=24),
                 "caducado": par(h=-1), "lista": par(**{"bucket-listing-action": "ListObjects"}), "objeto ajeno": par("hybrid-test/otro.json")}
        for k, p in casos.items(): self.assertFalse(P.audit([p], B_OK, NOW)["ok"], k)
        self.assertFalse(P.audit([par(), par(), par()], B_OK, NOW)["ok"])
        self.assertFalse(P.audit([par()], {"public-access-type": "ObjectRead", "versioning": "Enabled"}, NOW)["ok"])
        self.assertFalse(P.audit([par()], {"public-access-type": "NoPublicAccess", "versioning": "Disabled"}, NOW)["ok"])
    def test_plan_solo_objetos_de_la_prueba_sin_url_ni_tipos_Any(self):
        t = "\n".join(P.plan_commands()); self.assertNotIn("Any", t); self.assertNotIn("backups", t); self.assertNotIn("secrets", t)
        self.assertEqual(t.count("--access-type ObjectReadWrite"), 2); self.assertIn("hybrid-test/writer-lease.json", t)


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path == "/p/PAR/n/ns/b/bk/o/hybrid-test/writer-lease.json"
        self.send_response(200 if ok else 404); self.end_headers()
    def log_message(self, *a): pass


class Probe(unittest.TestCase):
    def test_probe_rechaza_alcance_extra_y_exige_permisos_0600(self):
        srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        d = tempfile.mkdtemp(); f = os.path.join(d, "u"); url = f"http://127.0.0.1:{srv.server_port}/p/PAR/n/ns/b/bk/o/hybrid-test/writer-lease.json"
        Path(f).write_text(url); os.chmod(f, 0o600)
        r = P.probe(P.read_url(f)); self.assertTrue(r["ok"], r); self.assertNotIn("127.0.0.1", str(r))                         # nunca devuelve la URL
        os.chmod(f, 0o644)
        with self.assertRaises(PermissionError): P.read_url(f)
        self.assertFalse(P.probe(url, status=lambda u: 200)["ok"])                                                          # si el servidor deja leer backups/, se detecta
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
