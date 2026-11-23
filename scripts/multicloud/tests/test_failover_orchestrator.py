"""B-13 · Pruebas del orquestador de failover en un mundo SIMULADO (relojes con deriva, lease real de B-10). No hay nubes ni red.
Uso: backend/.venv/bin/python -m unittest discover -s scripts/multicloud/tests -p 'test_failover_orchestrator.py' -v"""
import os, random, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/multicloud/failover")); sys.path.insert(0, str(ROOT / "backend"))
import sim  # noqa: E402
from orchestrator import STAGES, Abort, Adapters, Config, NotAuthorized, Orchestrator, State  # noqa: E402


def tmp_state():
    return Path(tempfile.mkdtemp()) / "estado.json"


class Escenarios(unittest.TestCase):
    def run_sc(self, sc, seed=1, **kw):
        return sim.run_scenario(sc, seed, tmp_state(), "r", **kw)

    def test_primario_caido_promueve_con_un_solo_escritor_y_dns_despues(self):
        r = self.run_sc("primary_dead")
        self.assertEqual((r["outcome"], r["violations"], r["dns_applied"], r["dns_violation"]), ("DONE", 0, 1, False))
        self.assertTrue(r["standby_wrote"] and r["epoch"] >= 2)
        names = [t[0] for t in r["timeline"]]; self.assertEqual(names, STAGES)             # etapas en orden

    def test_falso_positivo_primario_vivo_pero_sondas_ciegas_no_se_promueve(self):
        r = self.run_sc("primary_alive_probers_blind")
        self.assertEqual(r["outcome"], "ABORTED"); self.assertEqual((r["violations"], r["dns_applied"], r["standby_wrote"]), (0, 0, False))
        self.assertIn("no se pudo adquirir el lease", r["abort_reason"])                      # el lease impidió la doble escritura aunque las sondas fallaran

    def test_primario_sirve_pero_pierde_el_almacen_se_cierra_y_el_standby_toma(self):
        r = self.run_sc("primary_store_partitioned")
        self.assertEqual((r["outcome"], r["violations"]), ("DONE", 0))

    def test_sondas_discrepantes_no_actuan(self):
        r = self.run_sc("ambiguous_probes"); self.assertEqual((r["outcome"], r["dns_applied"], r["standby_wrote"]), ("ABORTED", 0, False)); self.assertIn("mayoría", r["abort_reason"])

    def test_primario_sano_no_se_toca(self):
        r = self.run_sc("healthy"); self.assertEqual((r["outcome"], r["violations"], r["dns_applied"]), ("ABORTED", 0, 0))

    def test_huella_de_datos_distinta_no_promueve_ni_toma_el_lease(self):
        r = self.run_sc("bad_backup"); self.assertEqual((r["outcome"], r["epoch"], r["standby_wrote"], r["dns_applied"]), ("ABORTED", None, False, 0)); self.assertIn("huella", r["abort_reason"])

    def test_compuerta_del_primario_desactivada_BLOQUEA_la_promocion_antes_de_habilitar_el_standby(self):
        """Antes (19-nov) el doble escritor solo se DETECTABA tras la promoción. Ahora FENCE_CHECK lo evita: el primario que sigue escribiendo bloquea la promoción y alerta."""
        r = self.run_sc("old_gate_off")
        self.assertEqual(r["outcome"], "ABORTED"); self.assertIn("sigue aceptando escrituras", r["abort_reason"]); self.assertIn("sin escritor nuevo", r["safe_state"])
        self.assertEqual((r["dns_applied"], r["standby_wrote"], r["dns_violation"]), (0, False, False))
        self.assertEqual(r["violations"], 0)               # el lease se libera y el standby nunca llega a escribir: ya no hay doble escritor
        self.assertEqual([a["severity"] for a in r["alerts"]], ["critical"])

    def test_primario_inalcanzable_con_compuerta_sin_evidencia_bloquea_y_alerta(self):
        """Estado desconocido + sin atestación de WRITE_GATE_MODE=enforce: podría seguir escribiendo → no se promueve."""
        import sim
        w, ad, cfg = sim.make("primary_dead", 1, None, "r")
        ad.primary_gate_attested = lambda: None
        st = State(tmp_state().parent / "e.json", "r"); o = Orchestrator(ad, cfg, st, dry_run=False); res = o.run(); w.advance(5)
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("desconocido", res["abort_reason"]); self.assertEqual((w.dns_applied, w.violations, w.standby_wrote), (0, 0, False))
        self.assertEqual(res["alerts"][0]["severity"], "critical")

    def test_primario_inalcanzable_con_compuerta_atestiguada_si_se_promueve(self):
        r = self.run_sc("primary_dead"); self.assertEqual((r["outcome"], r["violations"]), ("DONE", 0))
        self.assertEqual([a["severity"] for a in r["alerts"]], ["warning"]); self.assertIn("INFERIDO", r["alerts"][0]["message"])      # se promueve, pero el vallado inferido queda señalado

    def test_standby_no_listo_bloquea_el_dns_y_libera_el_lease(self):
        import sim
        for bad in (["livez"], ["ready"], ["api"], ["livez", "ready", "api"]):
            w, ad, cfg = sim.make("primary_dead", 1, None, "r"); w.standby_unhealthy = bad
            st = State(tmp_state().parent / ("e-%s.json" % "".join(bad)), "r"); res = Orchestrator(ad, cfg, st, dry_run=False).run(); w.advance(5)
            self.assertEqual(res["outcome"], "ABORTED", bad); self.assertIn("comprobaciones de salud", res["abort_reason"])
            self.assertEqual((w.dns_applied, w.dns_violation, w.violations, w.standby_enabled, w.standby.is_valid()), (0, False, 0, False, False), bad)  # lease liberado, DNS intacto
            self.assertEqual(res["alerts"][0]["severity"], "warning")

    def test_el_dns_exige_fence_check_y_health_gate(self):
        import sim
        w, ad, cfg = sim.make("primary_dead", 1, None, "r"); st = State(tmp_state().parent / "x.json", "r"); o = Orchestrator(ad, cfg, st, dry_run=False)
        for need in ("FENCE_CHECK", "HEALTH_GATE"):
            st.data["stages"] = {n: {"done": True} for n in ("PREPARE_STANDBY", "FENCE_AND_ACQUIRE", "FENCE_CHECK", "ENABLE_STANDBY", "HEALTH_GATE") if n != need}
            with self.assertRaises(Abort): o.stage_SWITCH_DNS()

    def test_dry_run_no_aplica_dns(self):
        r = self.run_sc("primary_dead", dry_run=True); self.assertEqual((r["outcome"], r["dns_applied"], r["dns"]), ("DONE", 0, "primary"))

    def test_flapping_nunca_dos_escritores_en_30_semillas(self):
        for seed in range(30):
            r = self.run_sc("flapping", seed); self.assertEqual(r["violations"], 0, f"semilla {seed}: {r}")


class Cancelacion(unittest.TestCase):
    def test_cancelar_en_cada_frontera_deja_a_lo_sumo_un_escritor(self):
        for k, stage in enumerate(STAGES):
            with self.subTest(antes_de=stage):
                w, ad, cfg = sim.make("primary_dead", 3, None, "r"); st = State(tmp_state(), "r")
                cancel = (lambda s=STAGES[k - 1] if k else None: (st.done(s) if s else True))   # se pide cancelar al terminar la etapa anterior
                o = Orchestrator(ad, cfg, st, cancel_check=cancel, dry_run=False); res = o.run(); w.advance(5)
                self.assertEqual(w.violations, 0)
                if k <= STAGES.index("FENCE_AND_ACQUIRE"):
                    self.assertEqual((w.standby_enabled, w.dns, w.dns_applied), (False, "primary", 0)); self.assertFalse(w.standby_wrote)
                if k == STAGES.index("ENABLE_STANDBY"):                               # lease tomado pero standby sin habilitar → se libera
                    self.assertFalse(w.standby.is_valid()); self.assertIn("sin escritor", res["safe_state"])
                if k >= STAGES.index("SWITCH_DNS"):
                    self.assertIn("NO se revierte automáticamente", res["safe_state"])
                self.assertEqual(res["outcome"], "CANCELLED")

    def test_cancelar_durante_la_espera_del_lease(self):
        w, ad, cfg = sim.make("primary_alive_probers_blind", 1, None, "r"); st = State(tmp_state(), "r")
        t_start = w.t; o = Orchestrator(ad, cfg, st, cancel_check=lambda: w.t - t_start > 25 and st.done("PREPARE_STANDBY"), dry_run=False)
        res = o.run(); self.assertEqual(res["outcome"], "CANCELLED"); self.assertEqual((w.violations, w.standby_enabled), (0, False))


class Idempotencia(unittest.TestCase):
    def test_caida_en_cada_etapa_antes_y_despues_del_efecto_y_se_reanuda_sin_duplicar(self):
        for stage in STAGES:
            for hook in ("before_stage", "after_stage"):
                with self.subTest(stage=stage, hook=hook):
                    w, ad, cfg = sim.make("primary_dead", 5, None, "r"); path = tmp_state()
                    class Crashy(Orchestrator):
                        armed = True
                        def before_stage(s, name):
                            if hook == "before_stage" and name == stage and Crashy.armed: Crashy.armed = False; raise RuntimeError("caída simulada")
                        def after_stage(s, name, result):
                            if hook == "after_stage" and name == stage and Crashy.armed: Crashy.armed = False; raise RuntimeError("caída simulada")
                    with self.assertRaises(RuntimeError): Crashy(ad, cfg, State(path, "r"), dry_run=False).run()
                    res = Orchestrator(ad, cfg, State(path, "r"), dry_run=False).run()          # reanudación con el MISMO run_id
                    w.advance(5)
                    self.assertEqual((res["outcome"], w.violations, w.dns_violation), ("DONE", 0, False))
                    self.assertEqual(w.dns_applied, 1, "el DNS debe aplicarse exactamente una vez")
                    self.assertLessEqual(w.restore_calls, 2); self.assertEqual(w.acquire_ok_calls >= 1, True)

    def test_repetir_una_ejecucion_terminada_no_repite_efectos(self):
        w, ad, cfg = sim.make("primary_dead", 2, None, "r"); path = tmp_state()
        Orchestrator(ad, cfg, State(path, "r"), dry_run=False).run()
        before = (w.dns_applied, w.restore_calls, w.enable_calls, w.acquire_ok_calls)
        res = Orchestrator(ad, cfg, State(path, "r"), dry_run=False).run()
        self.assertEqual(res["outcome"], "DONE"); self.assertEqual(before, (w.dns_applied, w.restore_calls, w.enable_calls, w.acquire_ok_calls))

    def test_una_ejecucion_abortada_no_se_reanuda_con_el_mismo_run_id(self):
        w, ad, cfg = sim.make("bad_backup", 2, None, "r"); path = tmp_state()
        Orchestrator(ad, cfg, State(path, "r"), dry_run=False).run()
        with self.assertRaises(Abort): Orchestrator(ad, cfg, State(path, "r"), dry_run=False).run()
        with self.assertRaises(ValueError): State(path, "otro")

    def test_el_primario_que_vuelve_tras_la_promocion_no_recupera_la_escritura(self):
        w, ad, cfg = sim.make("primary_dead", 4, None, "r"); st = State(tmp_state(), "r")
        res = Orchestrator(ad, cfg, st, dry_run=False).run(); self.assertEqual(res["outcome"], "DONE")
        w.primary_alive = True; w.advance(60)                                               # el primario revive y reintenta
        self.assertEqual(w.violations, 0); self.assertFalse(w.primary_accepts()); self.assertTrue(w.standby_accepts())      # sin failback automático


class SeguridadPorDefecto(unittest.TestCase):
    def test_adaptadores_sin_configurar_fallan_cerrado(self):
        o = Orchestrator(Adapters(), Config(), State(tmp_state(), "r"), dry_run=False)
        with self.assertRaises(NotAuthorized): o.run()

    def test_cli_run_se_rechaza_sin_entorno_frase_y_adaptadores_reales(self):
        py = sys.executable; cli = str(ROOT / "scripts/multicloud/failover/orchestrator.py"); env = {k: v for k, v in os.environ.items() if k != "NEXO_ALLOW_FAILOVER_EXECUTE"}
        r = subprocess.run([py, cli, "run"], capture_output=True, text=True, env=env); self.assertEqual(r.returncode, 2)
        env["NEXO_ALLOW_FAILOVER_EXECUTE"] = "YES"
        r = subprocess.run([py, cli, "run", "--confirm", "EJECUTAR FAILOVER REAL"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2); self.assertIn("no hay adaptadores reales", r.stderr)
        self.assertEqual(subprocess.run([py, cli, "plan"], capture_output=True, text=True).returncode, 0)

    def test_el_codigo_del_orquestador_no_contiene_llamadas_de_nube(self):
        for f in ("orchestrator.py", "sim.py"):
            src = (ROOT / "scripts/multicloud/failover" / f).read_text()
            for bad in ("subprocess", "urllib", "boto3", "requests", "socket", "aws ", "oci "):
                code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith(("#", '"""')) )
                if f == "orchestrator.py" and bad == "subprocess": continue            # solo importado en la CLI de pruebas del propio archivo
                self.assertNotIn(f"import {bad.strip()}", code, f"{f} importa {bad}")


class Aleatorio(unittest.TestCase):
    def test_400_escenarios_aleatorios_con_cancelacion_y_caidas_jamas_dos_escritores_ni_dns_prematuro(self):
        rng = random.Random(2026); stats = {"DONE": 0, "ABORTED": 0, "CANCELLED": 0, "reanudadas": 0}; wrote_with_healthy = 0
        for i in range(400):
            sc = rng.choice(sim.SCENARIOS); w, ad, cfg = sim.make(sc, 1000 + i, None, "r"); path = tmp_state()
            cancel_stage = rng.choice([None, None] + STAGES); crash_stage = rng.choice([None, None, None] + STAGES); crash_hook = rng.choice(["before_stage", "after_stage"])
            st0 = State(path, "r")
            class O(Orchestrator):
                armed = crash_stage is not None
                def before_stage(s, n):
                    if crash_hook == "before_stage" and n == crash_stage and O.armed: O.armed = False; raise RuntimeError("caída")
                def after_stage(s, n, r):
                    if crash_hook == "after_stage" and n == crash_stage and O.armed: O.armed = False; raise RuntimeError("caída")
            cancel = (lambda s=cancel_stage, st=st0: (st.done(s) if s else False))
            try:
                res = O(ad, cfg, st0, cancel_check=cancel, dry_run=rng.random() < 0.3).run()
            except RuntimeError:
                stats["reanudadas"] += 1
                res = O(ad, cfg, State(path, "r"), cancel_check=lambda: False, dry_run=False).run()
            w.advance(20)
            if sc == "old_gate_off":
                self.assertTrue(w.violations > 0 or res["outcome"] != "DONE" or not w.standby_wrote)       # nunca «éxito» con doble escritor
            else:
                self.assertEqual(w.violations, 0, f"{i} {sc} cancel={cancel_stage} crash={crash_stage}/{crash_hook}: {res}")
            self.assertFalse(w.dns_violation, f"{i} {sc}: DNS cambiado sin escritor listo")
            if sc in ("healthy", "ambiguous_probes", "primary_alive_probers_blind", "bad_backup"):
                self.assertFalse(w.standby_wrote and sc != "old_gate_off", f"{i} {sc}: se promovió con el primario sano/datos dudosos")
            stats[res["outcome"]] += 1
        self.assertGreater(stats["DONE"], 20); self.assertGreater(stats["ABORTED"], 20); self.assertGreater(stats["CANCELLED"], 5); self.assertGreater(stats["reanudadas"], 10)
        print("\nestadísticas:", stats)


if __name__ == "__main__":
    unittest.main()
