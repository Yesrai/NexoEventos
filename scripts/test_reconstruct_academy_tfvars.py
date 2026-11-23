#!/usr/bin/env python3
"""Pruebas de reconstruct-academy-tfvars.py con estados SIMULADOS (sin AWS, sin tocar work/ real).
Uso: python3 scripts/test_reconstruct_academy_tfvars.py"""
import contextlib
import importlib.util
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("recon", Path(__file__).resolve().parent / "reconstruct-academy-tfvars.py")
recon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recon)


def fake_state(multi_az=True, max_storage=20, allocated=20, apply_immediately=True, alarms=True) -> dict:
    db = {"tags": {"Name": "nexoeventos-academy-postgres"}, "region": "us-east-1", "instance_class": "db.t3.micro",
          "allocated_storage": allocated, "backup_retention_period": 7, "final_snapshot_identifier": "nexoeventos-academy-final-test",
          "max_allocated_storage": max_storage, "apply_immediately": apply_immediately}
    if multi_az is not None:
        db["multi_az"] = multi_az

    def res(t, n, a):
        return {"type": t, "name": n, "instances": [{"attributes": a}]}
    extra = [res("aws_sns_topic", "alarms", {"name": "nexoeventos-academy-alarmas"})] if alarms else []
    return {"lineage": "x", "serial": 7, "resources": extra + [
        res("aws_caller_identity", "current", {"account_id": "123456789012"}),
        res("aws_iam_instance_profile", "app", {"name": "LabInstanceProfile"}),
        res("aws_vpc", "main", {"cidr_block": "10.20.0.0/16", "tags": {"Name": "nexoeventos-academy-vpc"}}),
        res("aws_subnet", "public_a", {"cidr_block": "10.20.1.0/24"}),
        res("aws_subnet", "db_private_a", {"cidr_block": "10.20.21.0/24"}),
        res("aws_subnet", "db_private_b", {"cidr_block": "10.20.22.0/24"}),
        res("aws_instance", "app", {"tags": {"Name": "nexoeventos-academy-app"}, "region": "us-east-1", "instance_type": "t3.small",
                                    "ami": "ami-0123456789abcdef0", "root_block_device": [{"volume_size": 20}]}),
        res("aws_db_instance", "postgres", db),
        res("aws_cloudwatch_log_group", "api", {"region": "us-east-1", "retention_in_days": 7}),
    ]}


class ReconstructTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.dest = self.dir / "env" / "academy.tfvars"

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, state: dict, *extra: str):
        sp = self.dir / "state.json"
        sp.write_text(json.dumps(state))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            recon.main(["--state", str(sp), "--dest", str(self.dest), *extra])
        return out.getvalue(), err.getvalue()

    def read(self) -> str:
        return self.dest.read_text()

    def test_multi_az_se_conserva_y_se_escribe_en_minusculas(self):
        self.run_script(fake_state(multi_az=True))
        text = self.read()
        self.assertIn("db_multi_az = true", text)
        self.assertNotIn("True", text)

    def test_nunca_escribe_cero_si_el_estado_tiene_maximo(self):
        self.run_script(fake_state(max_storage=20))
        self.assertIn("db_max_allocated_storage_gib = 20", self.read())

    def test_conserva_el_mayor_entre_estado_y_archivo_actual(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_text("db_max_allocated_storage_gib = 40\ndb_multi_az = true\n")
        _, err = self.run_script(fake_state(max_storage=20))
        self.assertIn("db_max_allocated_storage_gib = 40", self.read())
        self.assertIn("AVISO", err)

    def test_si_el_estado_tiene_mas_gana_el_estado(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_text("db_max_allocated_storage_gib = 20\n")
        self.run_script(fake_state(max_storage=40))
        self.assertIn("db_max_allocated_storage_gib = 40", self.read())

    def test_aborta_si_se_quitaria_multi_az(self):
        self.dest.parent.mkdir(parents=True)
        original = "db_multi_az = true\ndb_max_allocated_storage_gib = 40\n"
        self.dest.write_text(original)
        with self.assertRaises(SystemExit):
            self.run_script(fake_state(multi_az=False))
        self.assertEqual(self.read(), original)  # no se tocó
        self.run_script(fake_state(multi_az=False), "--allow-downgrade")
        self.assertIn("db_multi_az = false", self.read())

    def test_aborta_si_el_estado_no_dice_multi_az(self):
        with self.assertRaises(SystemExit):
            self.run_script(fake_state(multi_az=None))
        self.assertFalse(self.dest.exists())

    def test_aborta_con_margen_invalido(self):
        with self.assertRaises(SystemExit):
            self.run_script(fake_state(max_storage=21, allocated=20))

    def test_dry_run_no_escribe_y_enmascara_la_cuenta(self):
        out, _ = self.run_script(fake_state(), "--dry-run")
        self.assertFalse(self.dest.exists())
        self.assertNotIn("123456789012", out)
        self.assertIn("<cuenta>", out)
        self.assertIn("db_multi_az = true", out)

    def test_archivo_con_modo_0600_y_cuenta_real(self):
        self.run_script(fake_state())
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o600)
        self.assertIn('expected_account_id = "123456789012"', self.read())

    def test_enable_alarms_se_deduce_del_estado(self):
        self.run_script(fake_state(alarms=True))
        text = self.read()
        self.assertIn("enable_alarms = true", text)
        self.assertIn("enable_cloudtrail = false", text)

    def test_aborta_si_se_quitarian_las_alarmas(self):
        self.dest.parent.mkdir(parents=True)
        original = "enable_alarms = true\n"
        self.dest.write_text(original)
        with self.assertRaises(SystemExit):
            self.run_script(fake_state(alarms=False))
        self.assertEqual(self.read(), original)
        self.run_script(fake_state(alarms=False), "--allow-downgrade")
        self.assertIn("enable_alarms = false", self.read())

    def test_el_codigo_no_tiene_valores_fijos_peligrosos(self):
        source = (Path(__file__).resolve().parent / "reconstruct-academy-tfvars.py").read_text()
        self.assertNotIn('("db_max_allocated_storage_gib", 0)', source)
        self.assertNotIn('("db_multi_az", False)', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
