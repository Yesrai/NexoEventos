import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/multicloud/hybrid"))
import hybrid_b1 as B  # noqa: E402


class FakeAws:
    """Simulador de AWS: las transiciones avanzan con cada consulta (como la API real, asíncrona)."""
    def __init__(self, ec2="stopped", rds="stopped", account=B.EXPECT["account"], asg=0, fail_on=None, replicas=None, project="NexoEventos", n_ec2=1):
        self.ec2, self.rds, self.account, self.asg, self.fail_on, self.calls = ec2, rds, account, asg, fail_on, []
        self.replicas, self.project, self.n_ec2 = replicas or [], project, n_ec2; self.tick = 0
    def advance(self):
        self.ec2 = {"pending": "running", "stopping": "stopped"}.get(self.ec2, self.ec2); self.rds = {"starting": "available", "stopping": "stopped"}.get(self.rds, self.rds)
    def run(self, argv):
        svc, op = argv[5], argv[6]; self.calls.append((svc, op))
        if self.fail_on == (svc, op): raise B.B1Error("fallo simulado")
        if (svc, op) == ("sts", "get-caller-identity"): return json.dumps({"Account": self.account, "Arn": "arn:aws:sts::1:assumed-role/voclabs/usr"})
        if (svc, op) == ("ec2", "describe-instances"):
            self.advance(); return json.dumps([{"id": f"i-{k}", "state": self.ec2, "proj": self.project} for k in range(self.n_ec2)])
        if (svc, op) == ("rds", "describe-db-instances"):
            self.advance(); return json.dumps([{"status": self.rds, "engine": "postgres", "ver": "18.3", "multi": True, "replicas": self.replicas, "auto": None}])
        if (svc, op) == ("autoscaling", "describe-auto-scaling-groups"): return json.dumps([{"d": self.asg, "i": self.asg}])
        if (svc, op) == ("ec2", "start-instances"): self.ec2 = "pending"; return "{}"
        if (svc, op) == ("ec2", "stop-instances"): self.ec2 = "stopping"; return "{}"
        if (svc, op) == ("rds", "start-db-instance"): self.rds = "starting"; return "{}"
        if (svc, op) == ("rds", "stop-db-instance"): self.rds = "stopping"; return "{}"
        raise AssertionError(f"llamada no esperada {svc} {op}")


def mk(**kw):
    f = FakeAws(**kw); t = {"t": 1000.0}
    b = B.B1(B.Aws(run=f.run), sleep=lambda s: t.__setitem__("t", t["t"] + s), now=lambda: t["t"]); return b, f, t


class Preflight(unittest.TestCase):
    def test_ok_y_solo_lee(self):
        b, f, _ = mk(); r = b.preflight(24.6, 90); self.assertTrue(r["ok"], r); self.assertEqual(r["gasto_estimado_usd"], 0.09)
        self.assertTrue(all(op.startswith("describe") or op == "get-caller-identity" for _, op in f.calls))      # solo lectura
    def test_bloqueos(self):
        for kw, frag in ((dict(account="999"), "identidad"), (dict(project="Otro"), "Project"), (dict(n_ec2=2), "exactamente 1")):
            with self.assertRaises(B.B1Error) as c: mk(**kw)[0].preflight(24.6, 90)
            self.assertIn(frag, str(c.exception))
        for kw, args, frag in ((dict(ec2="running"), (24.6, 90), "EC2"), (dict(rds="available"), (24.6, 90), "RDS"), (dict(asg=1), (24.6, 90), "Auto Scaling"), ({}, (5.0, 90), "crédito"), ({}, (24.6, 1000), "gasto"), ({}, (24.6, 2), "max-minutes")):
            r = mk(**kw)[0].preflight(*args); self.assertFalse(r["ok"]); self.assertTrue(any(frag in x for x in r["blockers"]), (frag, r["blockers"]))


class Start(unittest.TestCase):
    def test_enciende_rds_primero_luego_ec2_y_la_parada_deja_todo_stopped(self):
        b, f, t = mk(); sp = Path(tempfile.mkdtemp()) / "s.json"; st = b.start(sp, 90, log=lambda m: None)
        self.assertEqual((f.rds, f.ec2, st["estado"]), ("available", "running", "encendidas")); ops = [c for c in f.calls if c[1].startswith("start")]; self.assertEqual(ops, [("rds", "start-db-instance"), ("ec2", "start-instances")])
        r = b.stop_all(sp, log=lambda m: None); self.assertEqual((r["ec2"], r["rds"]), ("stopped", "stopped")); self.assertEqual(json.loads(sp.read_text())["estado"], "detenidas")
        self.assertEqual(oct(sp.stat().st_mode & 0o777), "0o600")
    def test_stop_es_idempotente_y_espera_a_que_la_RDS_pueda_pararse(self):
        b, f, _ = mk(ec2="running", rds="starting"); r = b.stop_all(log=lambda m: None); self.assertEqual((r["ec2"], r["rds"]), ("stopped", "stopped"))
        r2 = b.stop_all(log=lambda m: None); self.assertEqual((r2["ec2"], r2["rds"]), ("stopped", "stopped"))
    def test_lista_blanca_el_cliente_rechaza_cualquier_otra_operacion(self):
        a = B.Aws(run=lambda argv: "{}")
        for svc, op in (("rds", "modify-db-instance"), ("rds", "delete-db-instance"), ("ec2", "terminate-instances"), ("ec2", "run-instances"), ("rds", "reboot-db-instance"), ("autoscaling", "update-auto-scaling-group"), ("iam", "put-role-policy"), ("route53", "change-resource-record-sets")):
            with self.assertRaises(B.B1Error): a.call(svc, op)
    def test_el_script_solo_usa_operaciones_de_la_lista_blanca(self):
        src = (Path(B.__file__)).read_text()
        for peligro in ("modify-db", "delete-", "terminate", "run-instances", "create-", "put-", "terraform"): self.assertNotIn(f'"{peligro}', src.replace("'", '"'))


class Errores(unittest.TestCase):
    def test_un_error_al_encender_apaga_todo_via_main(self):
        f = FakeAws(fail_on=("ec2", "start-instances")); sp = Path(tempfile.mkdtemp()) / "s.json"; gs = Path(tempfile.mkdtemp()) / "g.json"; gs.write_text(json.dumps({"stages": {"B": {"estado": "en curso"}}}))
        import os; os.environ["NEXO_ALLOW_CLOUD_CHANGES"] = "YES"
        try:
            aws = B.Aws(run=f.run); rc = B.main(["start", "--credit-remaining", "24.6", "--max-minutes", "60", "--confirm", B.CONFIRM, "--state-file", str(sp), "--gate-state", str(gs)], aws=aws)
        finally: os.environ.pop("NEXO_ALLOW_CLOUD_CHANGES")
        self.assertEqual(rc, 1); self.assertEqual((f.ec2, f.rds), ("stopped", "stopped")); self.assertEqual(json.loads(sp.read_text())["estado"], "detenidas")
    def test_rechaza_sin_frase_sin_variable_o_sin_etapa_B_en_curso(self):
        f = FakeAws(); gs = Path(tempfile.mkdtemp()) / "g.json"; aws = B.Aws(run=f.run); base = ["start", "--credit-remaining", "24.6", "--confirm", B.CONFIRM, "--gate-state", str(gs), "--state-file", str(gs) + ".s"]
        self.assertEqual(B.main(base, aws=aws), 3)                                                          # sin variable de entorno
        import os; os.environ["NEXO_ALLOW_CLOUD_CHANGES"] = "YES"
        try:
            self.assertEqual(B.main(["start", "--credit-remaining", "24.6", "--confirm", "no", "--gate-state", str(gs)], aws=aws), 3)
            self.assertEqual(B.main(base, aws=aws), 3)                                                      # sin etapa B en curso
        finally: os.environ.pop("NEXO_ALLOW_CLOUD_CHANGES")
        self.assertEqual((f.ec2, f.rds), ("stopped", "stopped")); self.assertFalse([c for c in f.calls if "start" in c[1]])
    def test_watchdog_apaga_a_la_hora_limite_aunque_el_resto_haya_muerto(self):
        b, f, t = mk(ec2="running", rds="available"); sp = Path(tempfile.mkdtemp()) / "s.json"; b._save(sp, {"limite": t["t"] + 600, "estado": "encendidas"})
        r = b.watchdog(sp, log=lambda m: None, poll_s=60); self.assertEqual((r["ec2"], r["rds"]), ("stopped", "stopped")); self.assertGreaterEqual(t["t"], 1600)
    def test_parada_incompleta_se_declara_no_se_oculta(self):
        b, f, t = mk(ec2="running", rds="available"); f.fail_on = ("rds", "stop-db-instance"); sp = Path(tempfile.mkdtemp()) / "s.json"; b._save(sp, {"limite": 0, "estado": "encendidas"})
        r = b.stop_all(sp, log=lambda m: None, attempts=2); self.assertNotEqual(r["rds"], "stopped"); self.assertEqual(json.loads(sp.read_text())["estado"], "PARADA_INCOMPLETA")


if __name__ == "__main__":
    unittest.main()


class FakeAws2(FakeAws):
    def __init__(self, cmds=0, sess=0, cpu=None, **kw):
        super().__init__(**kw); self.cmds, self.sess, self.cpu = cmds, sess, cpu if cpu is not None else [1.2]
    def run(self, argv):
        svc, op = argv[5], argv[6]
        if (svc, op) == ("ssm", "list-commands"): self.calls.append((svc, op)); return json.dumps(["c"] * self.cmds) if "InProgress" in " ".join(argv) else "[]"
        if (svc, op) == ("ssm", "describe-sessions"): self.calls.append((svc, op)); return json.dumps(["s"] * self.sess)
        if (svc, op) == ("cloudwatch", "get-metric-statistics"): self.calls.append((svc, op)); return json.dumps(self.cpu)
        return super().run(argv)


class ReutilizarEC2(unittest.TestCase):
    def mk(self, **kw):
        f = FakeAws2(**kw); t = {"t": 1000.0}
        return B.B1(B.Aws(run=f.run), sleep=lambda s: t.__setitem__("t", t["t"] + s), now=lambda: t["t"]), f, t
    def test_preflight_con_ec2_encendida_exige_que_no_haya_operaciones_criticas(self):
        b, f, _ = self.mk(ec2="running"); r = b.preflight(24.0, 90, reuse_ec2=True); self.assertTrue(r["ok"], r); self.assertEqual(r["operaciones_criticas_ec2"]["critica"], False)
        for kw in (dict(cmds=1), dict(sess=1), dict(cpu=[80.0])):
            b, f, _ = self.mk(ec2="running", **kw); r = b.preflight(24.0, 90, reuse_ec2=True); self.assertFalse(r["ok"]); self.assertTrue(any("operación crítica" in x for x in r["blockers"]), kw)
        b, f, _ = self.mk(ec2="stopped"); self.assertFalse(b.preflight(24.0, 90, reuse_ec2=True)["ok"])           # con --reuse-ec2 se espera running
        b, f, _ = self.mk(ec2="running"); self.assertFalse(b.preflight(24.0, 90)["ok"])                          # sin --reuse-ec2, running sigue bloqueando
    def test_start_con_reutilizacion_enciende_solo_la_RDS_y_no_toca_la_EC2(self):
        b, f, _ = self.mk(ec2="running"); sp = Path(tempfile.mkdtemp()) / "s.json"; b.ec2(); st = b.start(sp, 90, log=lambda m: None, reuse_ec2=True)
        self.assertEqual((f.rds, f.ec2, st["ec2_reutilizada"]), ("available", "running", True)); self.assertNotIn(("ec2", "start-instances"), f.calls); self.assertNotIn(("ec2", "stop-instances"), f.calls)
        r = b.stop_all(sp, log=lambda m: None); self.assertEqual((r["ec2"], r["rds"]), ("stopped", "stopped"))         # al terminar se detienen AMBAS
    def test_main_exige_el_subpaso_B1_y_no_la_etapa_B(self):
        import os
        f = FakeAws2(ec2="running"); aws = B.Aws(run=f.run); gs = Path(tempfile.mkdtemp()) / "g.json"; sp = str(gs) + ".s"
        gs.write_text(json.dumps({"stages": {"B": {"estado": "pendiente"}, "B1": {"estado": "pendiente"}}}))
        base = ["start", "--reuse-ec2", "--gate-stage", "B1", "--credit-remaining", "24.0", "--max-minutes", "90", "--confirm", B.CONFIRM, "--gate-state", str(gs), "--state-file", sp]
        os.environ["NEXO_ALLOW_CLOUD_CHANGES"] = "YES"
        try:
            self.assertEqual(B.main(base, aws=aws), 3)                                                         # B1 no está en curso
            gs.write_text(json.dumps({"stages": {"B": {"estado": "pendiente"}, "B1": {"estado": "en curso"}}}))
            self.assertEqual(B.main(base, aws=aws), 0)                                                         # solo con B1 en curso (B sigue pendiente)
        finally: os.environ.pop("NEXO_ALLOW_CLOUD_CHANGES")
        self.assertEqual((f.rds, f.ec2), ("available", "running"))
