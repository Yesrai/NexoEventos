"""La carrera de adquisición (lease_race.py) sobre un servidor HTTP local con If-Match efectivo (debe dar exclusividad) y SIN If-Match (control negativo: debe DETECTAR violaciones).
Sin nube. Demuestra que la prueba evalúa la propiedad y no solo describe un comportamiento simulado."""
import os, sys, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "hybrid"))
from test_lease_http import H, Srv, SECRET  # noqa: E402  (servidor falso que imita If-Match / If-None-Match de OCI)
import lease_race as LR  # noqa: E402
from app.failover.lease import LeaseConfig, init_lease  # noqa: E402
from app.failover.store import ParHttpStore  # noqa: E402

CFG = LeaseConfig(ttl_s=0.6, margin_s=0.2)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H); cls.S = cls.srv.s = Srv()
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.par = Path(cls.tmp.name) / "race.url"; cls.par.write_text(f"http://127.0.0.1:{cls.srv.server_port}/p/{SECRET}/n/ns/b/bk/o/lease.json"); os.chmod(cls.par, 0o600)

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.srv.server_close(); cls.tmp.cleanup()

    def factory(self):
        st = ParHttpStore(self.par, timeout=5, allow_http_localhost=True); st.verified = True; return st

    def setUp(self):
        self.S.reset(); init_lease(self.factory(), allow_non_atomic=False, ttl_s=CFG.ttl_s, margin_s=CFG.margin_s)


class Exclusividad(Base):
    def test_con_if_match_efectivo_10_rondas_de_8_siempre_un_solo_ganador(self):
        r = LR.run_race(self.factory, 10, 8, CFG)
        self.assertTrue(r["exclusividad_demostrada"], r)
        self.assertEqual((r["rondas_aprobadas"], r["rondas_con_mas_de_un_ganador"], r["rondas_con_validos_simultaneos"], r["inconclusos"]), (10, 0, 0, 0))
        self.assertEqual([d["epoca_final"] for d in r["detalle"]], list(range(2, 12)))      # época estrictamente creciente +1 (la 1 es del cliente «primer»)

    def test_control_negativo_sin_if_match_la_prueba_DETECTA_varios_ganadores(self):
        self.S.enforce = False                         # el servidor ignora If-Match: lo que pasaría con un almacén no atómico
        r = LR.run_race(self.factory, 6, 8, CFG)
        self.assertFalse(r["exclusividad_demostrada"], r)
        self.assertTrue(r["rondas_con_mas_de_un_ganador"] >= 1 or r["rondas_con_validos_simultaneos"] >= 1, r)

    def test_almacen_caido_en_la_carrera_es_inconcluso_no_exito(self):
        self.S.down = True
        r = LR.run_race(self.factory, 2, 4, CFG)
        self.assertFalse(r["exclusividad_demostrada"]); self.assertEqual(r["rondas_aprobadas"], 0)

    def test_plazo_global_detiene_la_prueba(self):
        r = LR.run_race(self.factory, 50, 4, CFG, deadline_s=0.5)
        self.assertIsNotNone(r["detenido"]); self.assertFalse(r["exclusividad_demostrada"]); self.assertLess(r["rondas_ejecutadas"], 50)


if __name__ == "__main__":
    unittest.main()
