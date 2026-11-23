"""Pruebas de B-12 (dns_switch.py) con un «DuckDNS» y resolvedores SIMULADOS en 127.0.0.1. No toca ningún DNS público ni hace consultas a Internet."""
import io, json, os, stat, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dns_switch as ds  # noqa: E402

AWS_IP, OCI_IP = "8.8.8.8", "1.1.1.1"
TOKEN = "11111111-2222-3333-4444-555555555555"
RESOLVERS = ["r1", "r2", "r3"]


class Fake:
    """Zona simulada: el servidor DuckDNS la actualiza; los resolvedores la ven con retraso (en consultas)."""
    def __init__(self, ip=AWS_IP, lag=None, mode="ok", delay=0.0):
        self.zone, self.requests, self.mode, self.delay = {"nexoeventos-test": ip}, [], mode, delay
        self.lag = lag or {"r1": 0, "r2": 1, "r3": 2}                  # consultas que tarda cada resolvedor en ver el cambio
        self.pending = {r: None for r in RESOLVERS}; self.visible = {r: ip for r in RESOLVERS}; self.counts = {r: 0 for r in RESOLVERS}
        fake = self
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                q = parse_qs(urlparse(self.path).query); fake.requests.append(q)
                if fake.delay: time.sleep(fake.delay)
                if fake.mode == "ko": body = b"KO"
                elif fake.mode == "caido": self.send_response(500); self.end_headers(); return
                else:
                    fake.zone[q["domains"][0]] = q["ip"][0]
                    for r in RESOLVERS: fake.pending[r] = (q["ip"][0], fake.lag[r]); 
                    body = b"OK\n" + q["ip"][0].encode() + b"\nUPDATED"
                self.send_response(200); self.end_headers(); self.wfile.write(body)
            def log_message(self, *a): pass
        self.srv = HTTPServer(("127.0.0.1", 0), H); self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def resolver(self, name, server, timeout=3):
        self.counts[server] += 1
        p = self.pending[server]
        if p:
            ip, left = p
            if left <= 0: self.visible[server], self.pending[server] = ip, None
            else: self.pending[server] = (ip, left - 1)
        return [self.visible[server]], 60

    def close(self): self.srv.shutdown(); self.srv.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.fake = Fake()
        self.cfg = os.path.join(self.tmp, "cfg.json")
        with open(self.cfg, "w") as fh:
            json.dump({"allowed_domains": ["nexoeventos-test"], "allowed_targets": {"aws": AWS_IP, "oci": OCI_IP}, "assumed_ttl_s": 60, "min_interval_s": 300, "resolvers": RESOLVERS, "state_dir": os.path.join(self.tmp, "state")}, fh)
        self.env = {"NEXO_DNS_TEST": "1", "DUCKDNS_TOKEN": TOKEN}
        self.old = dict(os.environ); os.environ.update(self.env); os.environ.pop("NEXO_ALLOW_DNS_CHANGE", None)
        self.clock = {"t": 0.0}

    def tearDown(self):
        self.fake.close(); os.environ.clear(); os.environ.update(self.old)

    def run_cli(self, cmd, *extra, allow=False, domain="nexoeventos-test"):
        if allow: os.environ["NEXO_ALLOW_DNS_CHANGE"] = "YES"
        out, err = io.StringIO(), io.StringIO()
        import contextlib
        with contextlib.redirect_stderr(err):
            code = ds.main([cmd, "--config", self.cfg, "--domain", domain, "--api-base", f"http://127.0.0.1:{self.fake.port}", "--interval", "1", "--timeout", "30", *extra],
                           resolver=self.fake.resolver, sleep=lambda s: self.clock.__setitem__("t", self.clock["t"] + s), clock=lambda: self.clock["t"], out=out)
        return code, out.getvalue(), err.getvalue()

    def confirm(self, action, ip, domain="nexoeventos-test"): return ds.expected_phrase(action, domain, ip)


class Validacion(unittest.TestCase):
    def test_ips_validas_e_invalidas(self):
        for ok in ("8.8.8.8", "1.1.1.1", "129.151.20.33"): self.assertEqual(ds.validate_public_ipv4(ok), ok)
        for bad in ("10.0.0.1", "192.168.1.1", "172.16.0.5", "127.0.0.1", "169.254.1.1", "0.0.0.0", "255.255.255.255", "224.0.0.1", "203.0.113.5", "100.64.0.1", "::1", "abc", "1.2.3", "1.2.3.4.5", "999.1.1.1", " 8.8.8.8", "8.8.8.8 ", "08.8.8.8", "", None):
            with self.assertRaises(ds.Refused, msg=repr(bad)): ds.validate_public_ipv4(bad)

    def test_paquete_dns_ida_y_vuelta_con_compresion_de_nombres(self):
        q = ds.build_query("a.duckdns.org", 0xBEEF)
        resp = bytearray(q[:2] + b"\x81\x80" + q[4:6] + b"\x00\x02\x00\x00\x00\x00" + q[12:])
        rr = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04"
        resp += rr + bytes([8, 8, 8, 8]) + rr + bytes([1, 1, 1, 1])
        ips, ttl = ds.parse_response(bytes(resp), 0xBEEF)
        self.assertEqual((sorted(ips), ttl), (["1.1.1.1", "8.8.8.8"], 60))
        with self.assertRaises(ValueError): ds.parse_response(bytes(resp), 0x0001)           # id distinto
        with self.assertRaises(ValueError): ds.parse_response(bytes(resp[:20]), 0xBEEF)       # truncado
        err = bytearray(resp); err[3] = 0x83
        with self.assertRaises(ValueError): ds.parse_response(bytes(err), 0xBEEF)             # NXDOMAIN

    def test_configuracion_con_ip_invalida_en_lista_blanca_se_rechaza(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "c.json")
        for cfg in ({"allowed_domains": ["x"], "allowed_targets": {"aws": "10.0.0.1"}}, {"allowed_domains": ["No Valido!"], "allowed_targets": {"aws": "8.8.8.8"}}):
            with open(p, "w") as fh: json.dump(cfg, fh)
            with self.assertRaises(ds.Refused): ds.load_config(p)


class Cambios(Base):
    def test_plan_no_cambia_nada_y_no_llama_al_proveedor(self):
        code, out, _ = self.run_cli("plan", "--target", "oci")
        self.assertEqual(code, 0); self.assertIn("PLAN (no se cambió nada)", out); self.assertIn(OCI_IP, out); self.assertIn("TTL supuesto: 60", out)
        self.assertEqual(self.fake.requests, []); self.assertFalse(Path(self.tmp, "state", "nexoeventos-test.json").exists())

    def test_destino_o_dominio_fuera_de_lista_blanca(self):
        self.assertEqual(self.run_cli("plan", "--target", "otro")[0], 2)
        self.assertEqual(self.run_cli("plan", "--target", "oci", domain="otro-dominio")[0], 2)
        self.assertEqual(self.run_cli("apply", "--target", "1.2.3.4", "--confirm", self.confirm("apply", "1.2.3.4"), allow=True)[0], 2)   # IP a mano: rechazada
        self.assertEqual(self.fake.requests, [])

    def test_apply_exige_entorno_y_frase_exacta(self):
        self.assertEqual(self.run_cli("apply", "--target", "oci", "--confirm", self.confirm("apply", OCI_IP))[0], 2)                     # sin NEXO_ALLOW_DNS_CHANGE
        self.assertEqual(sum(self.fake.counts.values()), 0, "sin el permiso explícito no debe hacerse NI UNA consulta de red")
        self.assertEqual(self.run_cli("apply", "--target", "oci", allow=True)[0], 2)                                                      # sin --confirm
        self.assertEqual(self.run_cli("apply", "--target", "oci", "--confirm", self.confirm("apply", AWS_IP), allow=True)[0], 2)        # frase con otra IP
        self.assertEqual(self.run_cli("apply", "--target", "oci", "--confirm", "cambiar dns nexoeventos-test a 1.1.1.1", allow=True)[0], 2)  # minúsculas
        self.assertEqual(self.fake.requests, [])

    def test_apply_correcto_guarda_estado_audita_y_espera_propagacion_sin_filtrar_el_token(self):
        code, out, err = self.run_cli("apply", "--target", "oci", "--confirm", self.confirm("apply", OCI_IP), allow=True)
        self.assertEqual(code, 0, err + out); self.assertEqual(len(self.fake.requests), 1)
        q = self.fake.requests[0]; self.assertEqual((q["domains"], q["ip"], q["token"]), (["nexoeventos-test"], [OCI_IP], [TOKEN]))
        st = json.loads(Path(self.tmp, "state", "nexoeventos-test.json").read_text())
        self.assertEqual((st["previous_ip"], st["current_ip_set"]), (AWS_IP, OCI_IP))
        audit = Path(self.tmp, "state", "nexoeventos-test.audit.jsonl").read_text()
        for blob in (out, err, json.dumps(st), audit): self.assertNotIn(TOKEN, blob)
        self.assertIn("propagación", out); self.assertEqual(self.fake.visible["r3"], OCI_IP)
        self.assertEqual(stat.S_IMODE(Path(self.tmp, "state", "nexoeventos-test.json").stat().st_mode), 0o600)

    def test_intervalo_minimo_y_sin_cambios(self):
        self.assertEqual(self.run_cli("apply", "--target", "oci", "--confirm", self.confirm("apply", OCI_IP), allow=True)[0], 0)
        code, _, err = self.run_cli("apply", "--target", "aws", "--confirm", self.confirm("apply", AWS_IP), allow=True)
        self.assertEqual(code, 3); self.assertEqual(len(self.fake.requests), 1)                       # el 2.º cambio seguido se rechaza
        code, out, _ = self.run_cli("apply", "--target", "oci", "--confirm", self.confirm("apply", OCI_IP), allow=True)
        self.assertEqual(code, 0); self.assertIn("Sin cambios", out); self.assertEqual(len(self.fake.requests), 1)   # ya apunta ahí: no llama

    def test_rechazo_o_caida_del_proveedor_no_cambia_el_estado_ni_filtra_el_token(self):
        for mode in ("ko", "caido"):
            self.fake.mode = mode
            code, out, err = self.run_cli("apply", "--target", "oci", "--confirm", self.confirm("apply", OCI_IP), allow=True)
            self.assertEqual(code, 4, mode); self.assertNotIn(TOKEN, out + err)
            self.assertFalse(Path(self.tmp, "state", "nexoeventos-test.json").exists(), mode)

    def test_rollback_vuelve_a_la_ip_anterior_y_exige_su_propia_frase(self):
        self.assertEqual(self.run_cli("rollback", "--confirm", "x", allow=True)[0], 2)                  # sin estado previo
        self.run_cli("apply", "--target", "oci", "--confirm", self.confirm("apply", OCI_IP), allow=True)
        self.assertEqual(self.run_cli("rollback", "--confirm", self.confirm("apply", AWS_IP), allow=True)[0], 2)   # frase de apply no sirve
        n = len(self.fake.requests)
        code, out, _ = self.run_cli("rollback", "--confirm", self.confirm("rollback", AWS_IP), allow=True)
        self.assertEqual(code, 0); self.assertEqual(self.fake.requests[n]["ip"], [AWS_IP]); self.assertEqual(self.fake.zone["nexoeventos-test"], AWS_IP)

    def test_verify_espera_y_detecta_resolvedores_atrasados(self):
        self.run_cli("apply", "--target", "oci", "--confirm", self.confirm("apply", OCI_IP), allow=True)
        code, out, _ = self.run_cli("verify", "--expect-ip", OCI_IP); self.assertEqual(code, 0); self.assertIn("OK", out)
        self.fake.lag = {"r1": 0, "r2": 0, "r3": 10 ** 6}; self.fake.visible = {r: AWS_IP for r in RESOLVERS}
        code, out, _ = self.run_cli("verify", "--expect-ip", OCI_IP, "--timeout", "5")
        self.assertEqual(code, 1); self.assertIn("INCOMPLETO", out)

    def test_token_ausente_o_con_permisos_inseguros(self):
        os.environ.pop("DUCKDNS_TOKEN")
        self.assertEqual(self.run_cli("apply", "--target", "oci", "--confirm", self.confirm("apply", OCI_IP), allow=True)[0], 2)
        tf = Path(self.tmp, "tok"); tf.write_text(TOKEN); os.chmod(tf, 0o644)
        self.assertEqual(self.run_cli("apply", "--target", "oci", "--token-file", str(tf), "--confirm", self.confirm("apply", OCI_IP), allow=True)[0], 2)
        os.chmod(tf, 0o600)
        self.assertEqual(self.run_cli("apply", "--target", "oci", "--token-file", str(tf), "--confirm", self.confirm("apply", OCI_IP), allow=True)[0], 0)
        self.assertEqual(self.run_cli("plan", "--target", "oci")[0], 0)                                # plan no necesita token

    def test_api_base_solo_en_pruebas(self):
        del os.environ["NEXO_DNS_TEST"]
        self.assertEqual(self.run_cli("plan", "--target", "oci")[0], 2)

    def test_dos_cambios_simultaneos_solo_uno_pasa(self):
        self.fake.delay = 0.6
        res = []
        def go(): res.append(self.run_cli("apply", "--target", "oci", "--confirm", self.confirm("apply", OCI_IP), "--force-interval", allow=True)[0])
        ts = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(self.fake.requests), 1); self.assertIn(5, res)


if __name__ == "__main__":
    unittest.main()
