import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/multicloud/failover"))
from restart_guard import RestartGuard  # noqa: E402

OKP = {"latched": True, "authority_revoked": True, "app_sessions_left": 0, "prepared_xacts": 0}


class Guard(unittest.TestCase):
    def test_con_la_RDS_detenida_no_hace_nada_y_al_reiniciar_la_valla_con_cerrojo(self):
        estado = {"rds": "stopped"}; alertas = []; ordenes = []
        g = RestartGuard(aws_read=lambda: dict(estado), hard_fence=lambda: OKP, alert=lambda s, m: alertas.append((s, m)))
        r = g.step(); self.assertEqual((r["rds"], r["acciones"], r["latched"]), ("stopped", [], False)); self.assertFalse(alertas)
        estado["rds"] = "starting"; r = g.step(); self.assertTrue(r["latched"]); self.assertIn("cerrojo y vallado fuerte aplicados (prueba completa)", r["acciones"]); self.assertTrue(alertas and alertas[0][0] == "critical")

    def test_si_la_base_aun_no_responde_reintenta_y_con_permiso_ordena_parar_de_nuevo(self):
        n = {"i": 0}; ordenes = []
        def hf():
            n["i"] += 1
            if n["i"] < 3: raise ConnectionError("arrancando")
            return OKP
        g = RestartGuard(aws_read=lambda: {"rds": "available"}, hard_fence=hf, stop_rds=lambda: ordenes.append(1), allow_stop_rds=True)
        r1 = g.step(); self.assertFalse(r1["latched"]); self.assertIn("stop-db-instance ordenado de nuevo", r1["acciones"])
        g.step(); r3 = g.step(); self.assertTrue(r3["latched"])
        sin = RestartGuard(aws_read=lambda: {"rds": "available"}, hard_fence=lambda: (_ for _ in ()).throw(ConnectionError("x")), stop_rds=lambda: ordenes.append("NO"), allow_stop_rds=False)
        sin.step(); self.assertNotIn("NO", ordenes)                                              # sin permiso expreso no se ordena nada

    def test_alerta_si_el_sello_no_esta_vigente_o_no_se_lee_el_estado(self):
        a = []
        RestartGuard(aws_read=lambda: {"rds": "stopped"}, seal_check=lambda e: (True, "sin sello"), alert=lambda s, m: a.append(m)).step()
        self.assertTrue(any("SELLO" in m for m in a))
        b = []; RestartGuard(aws_read=lambda: (_ for _ in ()).throw(OSError("x")), alert=lambda s, m: b.append(m)).step(); self.assertTrue(b)


if __name__ == "__main__":
    unittest.main()
