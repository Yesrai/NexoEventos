import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/multicloud/failover")); sys.path.insert(0, str(ROOT / "backend"))
import evidence as EV  # noqa: E402
from promotion_gate import StrongFence  # noqa: E402
from adapters_standby import FullRecoveryAdapters  # noqa: E402

OKP = {"latched": True, "authority_revoked": True, "app_sessions_left": 0, "prepared_xacts": 0}


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s


class Strong(unittest.TestCase):
    def sf(self, **kw):
        c = Clock(); kw.setdefault("now", c); kw.setdefault("sleep", c.sleep); return StrongFence(**kw), c

    def test_la_base_vallada_con_prueba_completa_es_evidencia_fuerte(self):
        s, _ = self.sf(hard_fence=lambda: OKP, aws_read=lambda: {"ec2": "running", "rds": "available"})
        r = s.establish(); self.assertTrue(r["strong"]); self.assertEqual(r["evidence"][0]["kind"], "db_hard_fenced")

    def test_prueba_incompleta_no_vale_sesiones_restantes_preparadas_sin_cerrojo_o_sin_revocacion(self):
        for p in ({**OKP, "app_sessions_left": 1}, {**OKP, "prepared_xacts": 1}, {**OKP, "latched": False}, {**OKP, "authority_revoked": False}, None, {}):
            s, _ = self.sf(hard_fence=lambda p=p: p, aws_read=lambda: {"rds": "available"})
            self.assertFalse(s.establish()["strong"], p)

    def test_RDS_stopped_confirmada_vale_pero_stopping_available_o_desconocida_no(self):
        for rds, esperado in (("stopped", True), ("stopping", False), ("available", False), ("starting", False), (None, False)):
            s, _ = self.sf(hard_fence=lambda: (_ for _ in ()).throw(ConnectionError("x")), aws_read=lambda rds=rds: {"rds": rds})
            self.assertEqual(s.establish()["strong"], esperado, rds)

    def test_EC2_detenida_atestacion_lease_y_timeout_no_son_evidencia(self):
        s, _ = self.sf(hard_fence=lambda: (_ for _ in ()).throw(ConnectionError("x")), aws_read=lambda: {"ec2": "stopped", "rds": "available"})
        r = s.establish(); self.assertFalse(r["strong"]); self.assertTrue(any("EC2 detenida" in x for x in r["insufficient"])); self.assertIn("atestacion_del_vallado", r["not_evidence"])
        for k in ("caducidad_del_lease", "timeout_o_silencio", "barrera_http_de_reconocimiento", "ec2_detenida"): self.assertIn(k, r["not_evidence"])
        v = EV.assess_fencing(gate=None, aws={"ec2": "stopped", "rds": "available"}, gate_attested=True, lease_held=True, db_attested=True, strong=r, require_strong=True)
        self.assertEqual(v["verdict"], "UNKNOWN"); self.assertEqual(v["classification"], "RUNNING_OR_UNKNOWN")
        # el mismo caso en modo laxo (antiguo) SÍ promovía: es justo lo que ya no basta
        self.assertEqual(EV.assess_fencing(gate=None, aws={"ec2": "stopped", "rds": "available"}, gate_attested=True, lease_held=True, db_attested=True)["verdict"], "FENCED")

    def test_un_dato_caducado_no_vale_y_la_clasificacion_distingue_detenida_de_incomunicada(self):
        s = StrongFence(hard_fence=lambda: (_ for _ in ()).throw(ConnectionError("x")), aws_read=lambda: {"rds": "stopped"}, now=lambda: 1000.0, max_age_s=60)
        ok = s.establish(); self.assertTrue(ok["strong"]); self.assertEqual(ok["classification"], "CONFIRMED_FENCED")
        times = iter([1000.0, 1200.0]); s2 = StrongFence(hard_fence=None, aws_read=lambda: {"rds": "stopped"}, now=lambda: next(times, 1200.0), max_age_s=60)   # leída a las 1000, evaluada a las 1200
        r2 = s2.establish(); self.assertFalse(r2["strong"]); self.assertTrue(any("caducado" in x for x in r2["insufficient"]))
        inc = StrongFence(hard_fence=lambda: (_ for _ in ()).throw(ConnectionError("x")), aws_read=lambda: (_ for _ in ()).throw(OSError("x"))).establish()
        self.assertEqual(inc["classification"], "UNREACHABLE"); self.assertFalse(inc["strong"])

    def test_ordenar_la_parada_de_la_RDS_solo_si_se_permite_y_espera_a_stopped(self):
        estados = iter(["available", "stopping", "stopping", "stopped"]); llamadas = []
        c = Clock()
        s = StrongFence(hard_fence=None, aws_read=lambda: {"rds": next(estados)}, stop_rds=lambda: llamadas.append(1), allow_stop_rds=True, now=c, sleep=c.sleep, poll_s=5, stop_wait_s=100)
        r = s.establish(); self.assertTrue(r["strong"]); self.assertEqual(len(llamadas), 1); self.assertIn("stop-db-instance ordenado", r["actions"])
        n = []; s2 = StrongFence(hard_fence=None, aws_read=lambda: {"rds": "available"}, stop_rds=lambda: n.append(1), allow_stop_rds=False)
        self.assertFalse(s2.establish()["strong"]); self.assertEqual(n, [])                      # sin permiso expreso NO se ordena nada sobre la RDS
        c2 = Clock(); s3 = StrongFence(hard_fence=None, aws_read=lambda: {"rds": "stopping"}, stop_rds=lambda: None, allow_stop_rds=True, now=c2, sleep=c2.sleep, poll_s=10, stop_wait_s=30)
        self.assertFalse(s3.establish()["strong"])                                              # nunca llegó a stopped en el plazo

    def test_el_adaptador_con_vallado_fuerte_exigido_bloquea_la_promocion_sin_evidencia_aunque_la_atestacion_sea_perfecta(self):
        class L:
            def is_valid(self): return True
        a = FullRecoveryAdapters.__new__(FullRecoveryAdapters)
        a.primary_gate_url = None; a.allow_http_localhost = False; a.aws_state = lambda: {"ec2": "stopped", "rds": "available"}; a.fence_result = None; a.primary_db_fence = None
        a.db_attestation = {"ok": True}; a._gate_attested = True; a.lease = L(); a.require_strong_fence = True; a.strong_result = None
        a.strong_fence = StrongFence(hard_fence=lambda: (_ for _ in ()).throw(ConnectionError("partición")), aws_read=lambda: {"ec2": "stopped", "rds": "available"})
        r = a.fencing_assessment(); self.assertEqual(r["verdict"], "UNKNOWN"); self.assertEqual(r["classification"], "RUNNING_OR_UNKNOWN")
        a.strong_fence = StrongFence(hard_fence=lambda: OKP, aws_read=lambda: {"rds": "available"})
        r = a.fencing_assessment(); self.assertEqual(r["verdict"], "FENCED"); self.assertEqual(r["evidence"][0]["kind"], "db_hard_fenced")
        a.strong_fence = None; self.assertEqual(a.fencing_assessment()["verdict"], "UNKNOWN")      # sin puerta configurada: falla cerrado


if __name__ == "__main__":
    unittest.main()


import orchestrator as OR  # noqa: E402
import sim  # noqa: E402
import tempfile  # noqa: E402


class SelloEnElOrquestador(unittest.TestCase):
    def correr(self, seal_ok):
        w, ad, cfg = sim.make("primary_dead", 1, None, "r")
        orden = []
        class A(sim.SimAdapters):
            requires_seal = True
            def seal_primary(self, epoch):
                orden.append(("sello", w.standby_enabled)); 
                if seal_ok == "excepcion": raise OSError("almacén del sello inaccesible")
                return {"sellado": bool(seal_ok)}
        a = A(w); st = OR.State(Path(tempfile.mkdtemp()) / "e.json", "r")
        res = OR.Orchestrator(a, cfg, st, cancel_check=lambda: False).run(); w.advance(5)
        return res, w, orden

    def test_con_sello_exigido_se_sella_ANTES_de_habilitar_escrituras(self):
        res, w, orden = self.correr(True)
        self.assertEqual(res["outcome"], "DONE"); self.assertEqual(orden, [("sello", False)])     # al sellar, el standby aún NO escribía
        self.assertEqual(res["sello"]["sellado"], True); self.assertEqual(w.violations, 0)

    def test_si_no_se_puede_sellar_no_se_promueve_el_lease_se_libera_y_se_alerta(self):
        for fallo in (False, "excepcion"):
            res, w, _ = self.correr(fallo)
            self.assertEqual(res["outcome"], "ABORTED"); self.assertFalse(w.standby_wrote); self.assertEqual(w.dns_applied, 0)
            self.assertIn("sello", res["abort_reason"]); self.assertTrue(any("SELLAR" in a["message"] for a in res["alerts"]))


class AutomaticoBloqueado(unittest.TestCase):
    def correr(self, **kw):
        w, ad, cfg = sim.make("primary_dead", 1, None, "r"); cfg = OR.Config(automatic=True, **kw)
        class A(sim.SimAdapters):
            require_strong_fence = kw.pop("_strong", True) if False else True
            requires_seal = True
            def seal_primary(self, epoch): return {"sellado": True}
        a = A(w); res = OR.Orchestrator(a, cfg, OR.State(Path(tempfile.mkdtemp()) / "e.json", "r"), cancel_check=lambda: False).run(); w.advance(5); return res, w

    def test_automatico_sin_validaciones_reales_se_bloquea_y_no_promueve(self):
        for kw in (dict(), dict(validated_strong_fence=True), dict(validated_antirollback=True)):
            res, w = self.correr(**kw)
            self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("automática bloqueada", res["abort_reason"]); self.assertFalse(w.standby_wrote); self.assertEqual(w.dns_applied, 0)
            self.assertTrue(any("AUTOMÁTICA" in a["message"] for a in res["alerts"]))

    def test_automatico_con_ambas_validaciones_y_protecciones_exigidas_puede_continuar_y_el_manual_no_se_ve_afectado(self):
        res, w = self.correr(validated_strong_fence=True, validated_antirollback=True); self.assertEqual(res["outcome"], "DONE")
        w2, ad, cfg = sim.make("primary_dead", 1, None, "r"); r2 = OR.Orchestrator(ad, cfg, OR.State(Path(tempfile.mkdtemp()) / "e.json", "r"), cancel_check=lambda: False).run(); self.assertEqual(r2["outcome"], "DONE")   # manual: igual que antes
        class SinSello(sim.SimAdapters): require_strong_fence = True      # automático con validaciones declaradas pero SIN sello exigido en el adaptador: bloquea
        w3, _, _ = sim.make("primary_dead", 1, None, "r"); r3 = OR.Orchestrator(SinSello(w3), OR.Config(automatic=True, validated_strong_fence=True, validated_antirollback=True), OR.State(Path(tempfile.mkdtemp()) / "e.json", "r"), cancel_check=lambda: False).run()
        self.assertEqual(r3["outcome"], "ABORTED")
