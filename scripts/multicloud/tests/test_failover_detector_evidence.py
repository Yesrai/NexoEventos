import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "failover"))
import detector as D  # noqa: E402
import evidence as E  # noqa: E402


class Clasificacion(unittest.TestCase):
    base = dict(control=True, livez=True, ready=True, write_gate="escribe", ec2="running", rds="available")

    def k(self, **kw):
        return D.classify({**self.base, **kw}, gate_attested=kw.pop("att", None))

    def test_primario_sano_no_es_promovible(self):
        r = D.classify(self.base); self.assertEqual((r["kind"], r["promotable"]), ("HEALTHY", False))

    def test_una_sola_familia_no_declara_la_caida(self):
        # /livez falla pero AWS no confirma: no es una caída (falso positivo típico: ruta de red del sondeador)
        for ec2 in ("running", None):
            r = D.classify({**self.base, "livez": False, "ready": False, "ec2": ec2})
            self.assertFalse(r["promotable"] and r["kind"] == "INSTANCE_DOWN")
        r = D.classify({**self.base, "livez": False, "ready": False, "ec2": None}); self.assertEqual(r["kind"], "TRANSIENT")

    def test_caida_de_instancia_exige_http_y_aws(self):
        for st in ("stopped", "terminated"):
            r = D.classify({**self.base, "livez": False, "ready": False, "ec2": st, "write_gate": None}); self.assertEqual((r["kind"], r["promotable"]), ("INSTANCE_DOWN", True))
        r = D.classify({**self.base, "livez": True, "ready": True, "ec2": "stopped"}); self.assertEqual(r["kind"], "HEALTHY")     # AWS dice parada pero responde: no se actúa

    def test_caida_de_rds_es_candidata_pero_distinta_de_la_instancia(self):
        r = D.classify({**self.base, "ready": False, "rds": "stopped"}); self.assertEqual((r["kind"], r["promotable"]), ("DB_DOWN", True))
        self.assertIn("vallado", " ".join(r["reasons"]))
        r = D.classify({**self.base, "ready": False, "rds": "available"}); self.assertEqual((r["kind"], r["promotable"]), ("TRANSIENT", False))     # /ready falla con RDS disponible: contradictorio

    def test_aislamiento_de_red_solo_es_candidato_con_compuerta_atestiguada(self):
        sig = {**self.base, "livez": False, "ready": False, "write_gate": None}
        self.assertEqual((D.classify(sig)["kind"], D.classify(sig)["promotable"]), ("NETWORK_ISOLATION", False))
        self.assertTrue(D.classify(sig, gate_attested=True)["promotable"])
        self.assertFalse(D.classify(sig, gate_attested=None)["promotable"])

    def test_sondeador_aislado_no_concluye_nada(self):
        for c in (False, None):
            r = D.classify({**self.base, "control": c, "livez": False, "ec2": "stopped"}); self.assertEqual((r["kind"], r["promotable"]), ("SONDEADOR_AISLADO", False))

    def test_una_senal_que_lanza_es_desconocida_no_sana(self):
        def boom(): raise OSError("x")
        d = D.IncidentDetector(livez=boom, ready=boom, control=lambda: True, aws=boom)
        r = d.observe(); self.assertFalse(r["promotable"]); self.assertIsNone(r["signals"]["livez"])

    def test_detector_integra_las_senales(self):
        d = D.IncidentDetector(livez=lambda: False, ready=lambda: False, control=lambda: True, aws=lambda: {"ec2": "stopped", "rds": "stopped"})
        self.assertEqual(d.observe()["kind"], "INSTANCE_DOWN")


class Vallado(unittest.TestCase):
    def test_primario_que_escribe_bloquea(self):
        r = E.assess_fencing(gate="escribe", aws={"ec2": "stopped"}); self.assertEqual(r["verdict"], "CAN_WRITE")      # la compuerta manda sobre cualquier otra evidencia

    def test_vallado_de_la_base_prevalece_sobre_una_compuerta_http_que_escribe(self):
        r = E.assess_fencing(gate="escribe", db_fence=True); self.assertEqual((r["verdict"], r["evidence"][0]["kind"]), ("FENCED", "db_fence"))
        self.assertEqual(E.assess_fencing(gate="escribe", db_fence=False)["verdict"], "CAN_WRITE")

    def test_evidencias_verificadas(self):
        self.assertEqual(E.assess_fencing(gate="vallado")["verdict"], "FENCED")
        r = E.assess_fencing(gate=None, aws={"ec2": "stopped", "rds": "stopped"}); self.assertEqual((r["verdict"], r["evidence"][0]["kind"], r["evidence"][0]["strength"]), ("FENCED", "aws_instance", "verified"))
        self.assertEqual(E.assess_fencing(gate=None, db_fence=True)["verdict"], "FENCED")

    def test_sin_evidencia_es_desconocido_y_la_rds_sola_no_es_vallado(self):
        self.assertEqual(E.assess_fencing(gate=None)["verdict"], "UNKNOWN")
        self.assertEqual(E.assess_fencing(gate=None, aws={"ec2": "running", "rds": "stopped"})["verdict"], "UNKNOWN")     # RDS caída ≠ primario vallado
        self.assertEqual(E.assess_fencing(gate=None, aws={"ec2": "stopping"})["verdict"], "UNKNOWN")                       # estado transitorio

    def test_evidencia_inferida_exige_compuerta_atestacion_de_la_base_y_lease_tomado(self):
        self.assertEqual(E.assess_fencing(gate=None, gate_attested=True, lease_held=False, db_attested=True)["verdict"], "UNKNOWN")
        self.assertEqual(E.assess_fencing(gate=None, gate_attested=None, lease_held=True, db_attested=True)["verdict"], "UNKNOWN")
        for da in (None, False):      # la compuerta de la aplicación SOLA no es garantía: falta la atestación del vallado en la base
            self.assertEqual(E.assess_fencing(gate=None, gate_attested=True, lease_held=True, db_attested=da)["verdict"], "UNKNOWN")
        r = E.assess_fencing(gate=None, gate_attested=True, lease_held=True, db_attested=True); self.assertEqual((r["verdict"], r["evidence"][0]["strength"]), ("FENCED", "inferred"))


class LectorAws(unittest.TestCase):
    def runner(self, ec2, rds):
        def run(cmd):
            if "ec2" in cmd:
                if isinstance(ec2, Exception): raise ec2
                return ec2
            if isinstance(rds, Exception): raise rds
            return rds
        return run

    def test_lee_estados(self):
        self.assertEqual(E.AwsState(run=self.runner('["stopped"]', '["stopped"]')).read(), {"ec2": "stopped", "rds": "stopped"})

    def test_errores_o_estados_mezclados_son_desconocidos_nunca_parados(self):
        self.assertEqual(E.AwsState(run=self.runner(OSError("x"), OSError("x"))).read(), {"ec2": None, "rds": None})
        self.assertEqual(E.AwsState(run=self.runner('["stopped","running"]', "no-json")).read(), {"ec2": None, "rds": None})
        self.assertEqual(E.AwsState(run=self.runner("[]", "[]")).read(), {"ec2": None, "rds": None})

    def test_solo_comandos_de_lectura(self):
        seen = []
        E.AwsState(run=lambda c: (seen.append(c), "[]")[1]).read()
        self.assertTrue(all(any(v in c for v in ("describe-instances", "describe-db-instances")) for c in seen) and not any(w in " ".join(sum(seen, [])) for w in ("start", "stop", "terminate", "modify", "delete")))


if __name__ == "__main__":
    unittest.main()
