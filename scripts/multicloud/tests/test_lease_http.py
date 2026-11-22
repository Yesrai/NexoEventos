"""B-10 ↔ B-11 · El lease REAL (lease.py) y la compuerta de escritura (gate.py) sobre un almacén HTTP condicional (ParHttpStore) contra un servidor FALSO en 127.0.0.1 que imita
If-Match / If-None-Match / ETag de OCI Object Storage. Sin OCI real, sin red externa. Comprueba exclusión mutua, caducidad, renovación, pérdida del lease, resultado incierto,
almacén caído, carrera de 8 clientes y ausencia de doble escritura. NO demuestra coordinación distribuida real: eso solo se comprueba contra OCI (autoprueba preparada, no ejecutada).
Uso: backend/.venv/bin/python -m unittest discover -s scripts/multicloud/tests -p 'test_lease_http.py' -v"""
import os, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.failover.gate import WriteGate  # noqa: E402
from app.failover.lease import LeaseClient, LeaseConfig, init_lease  # noqa: E402
from app.failover.store import ParHttpStore, PreconditionFailed, StoreError, StoreUnavailable, verify_store_semantics  # noqa: E402

SECRET = "PAR-LEASE-INVENTADO-SOLO-PRUEBAS-77"


class Srv:
    def __init__(self):
        self.lock = threading.Lock(); self.reset()

    def reset(self):
        self.objs = {}; self.n = 0; self.enforce = True; self.down = False; self.apply_then_503 = 0; self.no_etag = False; self.redirect = False; self.puts = 0   # objs: ruta -> (datos, etag)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body=b"", etag=None):
        self.send_response(code)
        if etag and not self.server.s.no_etag: self.send_header("ETag", etag)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        s = self.server.s
        if not self.path.startswith(f"/p/{SECRET}/"): return self._send(404)
        if s.down: return self._send(503)
        if s.redirect: self.send_response(302); self.send_header("Location", "http://127.0.0.1:1/"); self.send_header("Content-Length", "0"); self.end_headers(); return
        with s.lock:
            o = s.objs.get(self.path)
            if o is None: return self._send(404)
            self._send(200, o[0], o[1])

    def do_PUT(self):
        s = self.server.s; body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not self.path.startswith(f"/p/{SECRET}/"): return self._send(403)
        if s.down: return self._send(503)
        inm, im = self.headers.get("If-None-Match"), self.headers.get("If-Match")
        with s.lock:                                                    # la comprobación y la escritura son ATÓMICAS (como en el servicio real); un objeto por ruta
            cur = s.objs.get(self.path)
            if s.enforce:
                if inm == "*" and cur is not None: return self._send(412)
                if im is not None and (cur is None or im != cur[1]): return self._send(412)
            s.puts += 1; s.n += 1; s.objs[self.path] = (body, f"v{s.n}")
            if s.apply_then_503 > 0:
                s.apply_then_503 -= 1; return self._send(503)           # se aplicó pero el cliente no lo sabe: resultado incierto
            self._send(200, b"", f"v{s.n}")


class Clk:
    def __init__(self, off=0.0, rate=1.0): self.t = 0.0; self.off = off; self.rate = rate
    def __call__(self): return self.rate * self.t + self.off


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H); cls.S = cls.srv.s = Srv()
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.par = Path(cls.tmp.name) / "lease.url"
        cls.par.write_text(f"http://127.0.0.1:{cls.srv.server_port}/p/{SECRET}/n/ns/b/bk/o/lease.json"); os.chmod(cls.par, 0o600)

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.srv.server_close(); cls.tmp.cleanup()

    def setUp(self): self.S.reset()

    def store(self, verified=True):
        st = ParHttpStore(self.par, timeout=5, allow_http_localhost=True); st.verified = verified; return st

    def init(self):
        s = self.store(); init_lease(s, allow_non_atomic=False); return s


class TestSemantica(Base):
    def test_el_almacen_pasa_la_autoprueba_de_semantica(self):
        def make():
            self.S.reset(); return self.store(verified=False)
        rep = verify_store_semantics(make)
        self.assertTrue(all(rep.values()), rep)

    def test_un_servidor_que_ignora_if_match_no_pasa_y_el_lease_lo_rechaza(self):
        def make():
            self.S.reset(); self.S.enforce = False; return self.store(verified=False)
        rep = verify_store_semantics(make)
        self.assertFalse(all(rep.values()), rep)
        st = self.store(verified=False)
        r = LeaseClient(st, LeaseConfig(), "A", Clk()).acquire()
        self.assertFalse(r.ok); self.assertIn("NO verificado", r.reason)

    def test_errores_del_almacen(self):
        st = self.store()
        self.assertIsNone(st.read())
        st.create(b"x")
        with self.assertRaises(PreconditionFailed): st.create(b"y")
        with self.assertRaises(PreconditionFailed): st.replace("v999", b"z")
        self.S.down = True
        with self.assertRaises(StoreUnavailable): st.read()
        with self.assertRaises(StoreUnavailable): st.replace("v1", b"z")
        self.S.down = False; self.S.no_etag = True
        with self.assertRaises(StoreUnavailable): st.read()
        self.S.no_etag = False; self.S.redirect = True
        with self.assertRaises(StoreError): st.read()

    def test_url_invalida_y_secreto_oculto(self):
        d = Path(self.tmp.name)
        for text, mode in (("http://ejemplo.invalid/p/x/", 0o600), ("https://evil.example.com/p/x/", 0o600), ("https://u:p@x.oraclecloud.com/o/", 0o600), ("https://x.oraclecloud.com/o/?a=1", 0o600),
                           (self.par.read_text(), 0o644)):
            p = d / "u.url"; p.write_text(text); os.chmod(p, mode)
            with self.assertRaises(StoreError, msg=text) as cm: ParHttpStore(p, allow_http_localhost=text == self.par.read_text() and mode == 0o644)
            self.assertNotIn(SECRET, str(cm.exception))
        self.assertNotIn(SECRET, repr(self.store())); self.assertNotIn("127.0.0.1", repr(self.store()))

    def test_registro_corrupto_falla_cerrado(self):
        s = self.store(); s.create(b"esto no es un registro")
        r = LeaseClient(s, LeaseConfig(), "A", Clk()).acquire()
        self.assertFalse(r.ok); self.assertIn("ilegible", r.reason)


class TestLeaseSobreHttp(Base):
    def pair(self):
        ca, cb = Clk(1000.0, 1.03), Clk(-5000.0, 0.97)          # relojes con deriva ±3 % y desfases distintos
        a = LeaseClient(self.store(), LeaseConfig(), "A", ca); b = LeaseClient(self.store(), LeaseConfig(), "B", cb)
        return a, b, ca, cb

    def step(self, dt, *clks):
        for c in clks: c.t += dt

    def test_exclusion_mutua_mientras_el_titular_renueva(self):
        self.init(); a, b, ca, cb = self.pair()
        self.assertTrue(a.acquire().ok)
        for _ in range(40):                                         # 40 × 1 s: A renueva, B insiste
            self.step(1.0, ca, cb)
            if a.is_valid(): a.renew()
            rb = b.acquire(); self.assertFalse(rb.ok); self.assertFalse(b.is_valid())
        self.assertTrue(a.is_valid()); self.assertEqual(a.epoch, 1)

    def test_caducidad_toma_y_perdida_del_titular_anterior(self):
        self.init(); a, b, ca, cb = self.pair()
        self.assertTrue(a.acquire().ok)
        self.assertFalse(b.acquire().ok)                            # observa
        self.step(10.0, ca, cb); self.assertFalse(b.acquire().ok)   # aún no caducó
        self.step(15.0, ca, cb)                                     # A no renovó: caducó por su propio reloj
        self.assertFalse(a.is_valid())                              # A deja de escribir ANTES de que B pueda tomar
        rb = b.acquire(); self.assertTrue(rb.ok, rb.reason); self.assertEqual(b.epoch, 2)
        ra = a.renew(); self.assertFalse(ra.ok); self.assertFalse(a.is_valid())      # A intenta volver: pierde (ETag cambió)
        self.assertTrue(a.status()["lost"])

    def test_resultado_incierto_no_extiende_la_validez_y_se_adopta_despues(self):
        self.init(); a, b, ca, cb = self.pair(); self.assertTrue(a.acquire().ok)
        self.step(4.0, ca, cb); self.S.apply_then_503 = 1
        r = a.renew(); self.assertFalse(r.ok)                       # se aplicó en el servidor pero A no lo sabe
        self.step(12.0, ca, cb); self.assertFalse(a.is_valid())     # sin confirmación no hay validez: falla seguro
        r2 = a.acquire(); self.assertTrue(r2.ok, r2.reason)         # el titular adopta su propia escritura incierta

    def test_almacen_caido_invalida_al_titular_y_la_compuerta_bloquea(self):
        self.init(); a, b, ca, cb = self.pair(); self.assertTrue(a.acquire().ok)
        gate = WriteGate(a, "primary"); self.assertTrue(gate.allows_writes())
        self.S.down = True
        for _ in range(15):
            self.step(1.0, ca); gate.keeper_step()
        self.assertFalse(gate.allows_writes())                      # sin poder renovar, no se escribe
        self.S.down = False; self.step(1.0, ca); gate.keeper_step()
        self.assertTrue(gate.allows_writes() or a.status()["lost"] is False)   # se recupera solo si nadie más tomó el lease

    def test_carrera_de_8_clientes_un_solo_ganador(self):
        self.init(); clients = [LeaseClient(self.store(), LeaseConfig(), f"N{i}", Clk()) for i in range(8)]
        wins, lock = [], threading.Lock()
        def go(c):
            r = c.acquire()
            if r.ok:
                with lock: wins.append(c.holder_id)
        # el lease inicial está liberado (init_lease): los 8 intentan tomarlo a la vez por el mismo ETag
        ts = [threading.Thread(target=go, args=(c,)) for c in clients]; [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(wins), 1, wins)
        self.assertEqual(sum(1 for c in clients if c.is_valid()), 1)

    def test_no_hay_doble_escritura_con_pausa_y_toma(self):
        """Compuerta del primario y del standby sobre el MISMO almacén HTTP: aunque el primario se «congele» (no renueva) y el standby tome el lease, nunca escriben a la vez."""
        self.init(); a, b, ca, cb = self.pair()
        ga, gb = WriteGate(a, "primary"), WriteGate(b, "standby", promote_file=str(Path(self.tmp.name) / "promote"))
        self.assertTrue(a.acquire().ok)
        viol = 0; wrote_b = False; promote = Path(self.tmp.name) / "promote"; promote.unlink(missing_ok=True)
        for i in range(400):                                        # 100 s en pasos de 0,25 s
            self.step(0.25, ca, cb)
            if i % 4 == 0:
                if i < 40 or i > 300: ga.keeper_step()              # el primario renueva y se «congela» entre los pasos 40 y 300
                if i == 80: promote.write_text("1")                # el operador promueve al standby
                gb.keeper_step()
            wa, wb = ga.allows_writes(), gb.allows_writes()
            viol += int(wa and wb); wrote_b = wrote_b or wb
        promote.unlink(missing_ok=True)
        self.assertEqual(viol, 0); self.assertTrue(wrote_b)          # el standby sí llegó a escribir, pero nunca a la vez que el primario
        self.assertFalse(ga.allows_writes())                        # el primario, al volver, NO recupera el lease que tiene el standby


if __name__ == "__main__":
    unittest.main(verbosity=2)
