import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "failover"))
import failback as FB  # noqa: E402


class Failback(unittest.TestCase):
    ok = dict(ledger_state="PROMOTED", primary_fenced=True, primary_data_status="REEMPLAZADO_DESDE_OCI", standby_is_writer=True, aws_health_ok=True, human_approved=True)

    def test_nunca_es_automatico_y_solo_se_permite_con_todo_cumplido(self):
        p = FB.plan_failback(**self.ok); self.assertTrue(p["allowed"]); self.assertFalse(p["automatic"]); self.assertEqual(p["blockers"], [])

    def test_cada_condicion_incumplida_bloquea(self):
        for k, v in (("ledger_state", "NONE"), ("primary_fenced", False), ("primary_data_status", "DESCONOCIDO"), ("standby_is_writer", False), ("aws_health_ok", False), ("human_approved", False)):
            p = FB.plan_failback(**{**self.ok, k: v}); self.assertFalse(p["allowed"], k); self.assertFalse(p["automatic"]); self.assertTrue(p["blockers"], k)

    def test_los_datos_de_aws_no_se_fusionan_y_los_modos_estan_distinguidos(self):
        p = FB.plan_failback(**{**self.ok, "primary_data_status": "DIVERGENTE"}); self.assertIn("no se fusionan", " ".join(p["blockers"]))
        self.assertEqual(FB.MODES, ("RECUPERACION_DESDE_RESPALDO", "STANDBY_PREPARADO", "FAILOVER_AUTOMATICO", "FAILBACK"))
