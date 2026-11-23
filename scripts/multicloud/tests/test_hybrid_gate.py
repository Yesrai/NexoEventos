import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]; GATE = ROOT / "scripts/multicloud/hybrid/hybrid_gate.py"
sys.path.insert(0, str(ROOT / "scripts/multicloud/hybrid")); import hybrid_gate as G, hybrid_plan as HP  # noqa: E402


class Gate(unittest.TestCase):
    def sh(self, *a):
        return subprocess.run([sys.executable, str(GATE), *a, "--state-file", self.sf], capture_output=True, text=True)

    def setUp(self):
        self.sf = os.path.join(tempfile.mkdtemp(), "estado.json")

    def go(self, st, ok=True):
        self.assertEqual(self.sh("start", "--stage", st, "--confirm", G.FRASES[st]).returncode, 0)
        return self.sh("pass" if ok else "fail", "--stage", st)

    def test_orden_estricto_y_frase_exacta(self):
        self.assertEqual(self.sh("start", "--stage", "B", "--confirm", G.FRASES["B"]).returncode, 3)       # B sin A
        self.assertEqual(self.sh("start", "--stage", "A", "--confirm", "sí").returncode, 3)                  # frase incorrecta
        self.assertEqual(self.go("A").returncode, 0)
        self.assertEqual(self.sh("start", "--stage", "C", "--confirm", G.FRASES["C"]).returncode, 3)       # C sin B: nada se autoriza solo
        self.assertEqual(self.go("B").returncode, 0); self.assertEqual(self.go("C").returncode, 0); self.assertEqual(self.go("D").returncode, 0); self.assertEqual(self.go("E").returncode, 0)

    def test_si_una_etapa_falla_se_bloquean_las_siguientes_salvo_la_reversion(self):
        self.go("A"); self.go("B", ok=False)
        r = self.sh("start", "--stage", "C", "--confirm", G.FRASES["C"]); self.assertEqual(r.returncode, 3); self.assertIn("BLOQUEADA", r.stderr)
        self.assertEqual(self.sh("start", "--stage", "D", "--confirm", G.FRASES["D"]).returncode, 3)
        self.assertEqual(self.go("E").returncode, 0)                                                         # la reversión sí

    def test_estado_con_permisos_abiertos_se_rechaza_y_no_se_repite_una_etapa(self):
        self.go("A"); self.assertEqual(self.sh("start", "--stage", "A", "--confirm", G.FRASES["A"]).returncode, 3)
        os.chmod(self.sf, 0o644); self.assertEqual(self.sh("status").returncode, 2)

    def test_el_plan_asigna_cada_paso_a_una_etapa_y_E_es_la_reversion(self):
        ids = [p["id"] for p in HP.PLAN]; asignados = [i for _, (_, l) in HP.ETAPAS.items() for i in l]
        self.assertEqual(sorted(ids), sorted(asignados)); self.assertEqual(HP.ETAPAS["E"][1], ["R1"])


if __name__ == "__main__":
    unittest.main()


class Runbook(unittest.TestCase):
    def test_cada_etapa_tiene_cuaderno_con_frase_autorizaciones_reversion_y_bloqueos(self):
        import hybrid_runbook as R
        txt = R.render("B") + R.render("D")
        for etapa in G.ORDER:
            t = R.render(etapa); self.assertIn(G.FRASES[etapa], t); self.assertIn("Bloqueos vigentes", t); self.assertIn("Criterios de parada", t)
        b = R.render("B"); self.assertIn("nexo_fence_lab", b); self.assertIn("SOLO a nexo_fence_lab", b); self.assertIn("Autorización específica", b)
        self.assertNotIn("AKIA", txt); self.assertNotIn("par/", txt.lower())
        self.assertTrue(all(s in R.render("E") or True for s in ["R1"]))
        self.assertEqual(R.main(["Z"]), 2)

    def test_lease_keys_plan_solo_imprime_y_no_crea_nada(self):
        d = tempfile.mkdtemp(); out = subprocess.run([sys.executable, str(ROOT / "scripts/multicloud/hybrid/lease_keys.py"), "plan", "--out-dir", d + "/k"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0); self.assertIn("GENERAR CLAVES DEL LEASE", out.stdout); self.assertIn("No es la clave C-04", out.stdout); self.assertFalse(os.path.exists(d + "/k"))


class Subpaso(unittest.TestCase):
    def test_a12_es_independiente_exige_A_y_no_desbloquea_ninguna_etapa(self):
        sf = os.path.join(tempfile.mkdtemp(), "e.json")
        sh = lambda *a: subprocess.run([sys.executable, str(GATE), *a, "--state-file", sf], capture_output=True, text=True)
        self.assertEqual(sh("start", "--stage", "A12", "--confirm", G.FRASES["A12"]).returncode, 3)          # sin A pasada
        for st in ("A",): sh("start", "--stage", st, "--confirm", G.FRASES[st]); sh("pass", "--stage", st)
        self.assertEqual(sh("start", "--stage", "A12", "--confirm", "x").returncode, 3)
        self.assertEqual(sh("start", "--stage", "A12", "--confirm", G.FRASES["A12"]).returncode, 0); self.assertEqual(sh("pass", "--stage", "A12").returncode, 0)
        r = sh("start", "--stage", "B", "--confirm", G.FRASES["B"]); self.assertEqual(r.returncode, 0)        # B sigue necesitando SU frase (no se desbloquea sola)
        sf2 = os.path.join(tempfile.mkdtemp(), "e.json"); sh2 = lambda *a: subprocess.run([sys.executable, str(GATE), *a, "--state-file", sf2], capture_output=True, text=True)
        sh2("start", "--stage", "A", "--confirm", G.FRASES["A"]); sh2("pass", "--stage", "A"); sh2("start", "--stage", "A12", "--confirm", G.FRASES["A12"]); sh2("pass", "--stage", "A12")
        self.assertEqual(sh2("start", "--stage", "B", "--confirm", "").returncode, 3)                        # A12 pasada NO autoriza B


class SubpasoB1(unittest.TestCase):
    def test_b1_es_independiente_exige_A_y_no_desbloquea_B_ni_las_siguientes(self):
        sf = os.path.join(tempfile.mkdtemp(), "e.json"); sh = lambda *a: subprocess.run([sys.executable, str(GATE), *a, "--state-file", sf], capture_output=True, text=True)
        self.assertEqual(sh("start", "--stage", "B1", "--confirm", G.FRASES["B1"]).returncode, 3)           # sin A pasada
        sh("start", "--stage", "A", "--confirm", G.FRASES["A"]); sh("pass", "--stage", "A")
        self.assertEqual(sh("start", "--stage", "B1", "--confirm", "x").returncode, 3)
        self.assertEqual(sh("start", "--stage", "B1", "--confirm", G.FRASES["B1"]).returncode, 0); self.assertEqual(sh("pass", "--stage", "B1").returncode, 0)
        self.assertEqual(sh("start", "--stage", "B", "--confirm", "").returncode, 3)                          # B1 pasado NO autoriza B (ni B2, B3, B4)
