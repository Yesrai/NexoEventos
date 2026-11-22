"""Pruebas de la AUTOPRUEBA del lease (lease_selftest.py) contra una CLI de OCI SIMULADA. No usa red ni nubes."""
import json, os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lease_selftest as ls  # noqa: E402

SHIM = r'''#!/usr/bin/env python3
import fcntl, json, os, sys
a = sys.argv[1:]; d = os.environ["SHIM_DIR"]
log = open(f"{d}/calls.log", "a"); log.write(" ".join(a[:3]) + "\n"); log.close()
if a[0] == "--version": print("3.99.0"); sys.exit(0)
if a[:2] == ["os", "bucket"]:
    print(json.dumps({"data": {"versioning": os.environ.get("SHIM_VERSIONING", "Disabled"), "public-access-type": os.environ.get("SHIM_PUBLIC", "NoPublicAccess")}})); sys.exit(0)
sub = a[2]; g = lambda k: a[a.index(k) + 1] if k in a else None
if sub == "put" and "--help" in a:
    print("Usage ... --if-match TEXT" if not os.environ.get("SHIM_NO_IFMATCH_HELP") else "Usage ... --force"); sys.exit(0)
name = g("--name") or g("--object-name"); data_p, gen_p = f"{d}/{name}.data", f"{d}/{name}.gen"
lk = os.open(f"{d}/lock", os.O_CREAT | os.O_RDWR); fcntl.flock(lk, fcntl.LOCK_EX)
exists = os.path.exists(data_p); gen = int(open(gen_p).read()) if exists else 0
if sub == "head":
    if not exists: sys.stderr.write("ServiceError: ObjectNotFound (404)\n"); sys.exit(1)
    print(json.dumps({"etag": f"e{gen}"})); sys.exit(0)
if sub == "get":
    if not exists: sys.stderr.write("ServiceError: ObjectNotFound (404)\n"); sys.exit(1)
    sys.stdout.buffer.write(open(data_p, "rb").read()); sys.exit(0)
if sub == "delete":
    if exists: os.remove(data_p); os.remove(gen_p)
    sys.exit(0)
if sub == "put":
    body = open(g("--file"), "rb").read()
    if "--no-overwrite" in a and exists: sys.stderr.write("object already exists\n"); sys.exit(1)
    im = g("--if-match")
    if im and not os.environ.get("SHIM_BROKEN_IFMATCH") and (not exists or im != f"e{gen}"):
        sys.stderr.write("ServiceError: IfMatchFailed (412)\n"); sys.exit(1)
    open(data_p, "wb").write(body); open(gen_p, "w").write(str(gen + 1)); print(json.dumps({"etag": f"e{gen + 1}"})); sys.exit(0)
sys.exit(2)
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.bucket_dir = Path(self.tmp, "bucket"); self.bucket_dir.mkdir()
        self.shim = Path(self.tmp, "oci"); self.shim.write_text(SHIM); self.shim.chmod(self.shim.stat().st_mode | stat.S_IEXEC)
        self.old = dict(os.environ)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self.old)

    def runner(self, **env):
        full = dict(os.environ, SHIM_DIR=str(self.bucket_dir), **env)
        return lambda argv: subprocess.run(argv, capture_output=True, timeout=60, env=full)

    def calls(self):
        p = self.bucket_dir / "calls.log"; return p.read_text().splitlines() if p.exists() else []

    def objects(self):
        return sorted(f.name for f in self.bucket_dir.glob("*.data"))

    def selftest(self, bucket="nexoeventos-lease-test", **env):
        return ls.run_selftest("ns", bucket, "PERFIL", "ADMIN", rounds=5, writers=8, max_minutes=2, oci=str(self.shim), runner=self.runner(**env), log=lambda *_: None, lease_ttl=2.0, lease_margin=0.6)


class Cases(Base):
    def test_exito_completo_y_limpieza_de_todo_lo_creado(self):
        rep, code = self.selftest()
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["pasos"]["2_carrera"]["ganadores_por_ronda"], [1] * 5)
        self.assertTrue(all(v for k, v in rep["pasos"]["3_lease"].items() if k != "tiempo_de_toma_s"))
        lim = rep["pasos"]["4_limpieza"]; self.assertEqual(lim["objetos_creados"], lim["borrados"]); self.assertEqual(self.objects(), [])

    def test_cli_sin_if_match_falla_la_semantica_se_detiene_y_aun_asi_limpia(self):
        rep, code = self.selftest(SHIM_BROKEN_IFMATCH="1")
        self.assertEqual(code, 1); self.assertFalse(rep["pasos"]["1_semantica"]["cas_con_etag_viejo_rechazado"]); self.assertNotIn("2_carrera", rep["pasos"]); self.assertEqual(self.objects(), [])

    def test_bucket_con_versionado_o_publico_se_rechaza_antes_de_escribir(self):
        for env in ({"SHIM_VERSIONING": "Enabled"}, {"SHIM_PUBLIC": "ObjectRead"}):
            with self.assertRaises(ls.Refused): self.selftest(**env)
        self.assertEqual(self.objects(), [])

    def test_cli_que_no_ofrece_if_match_se_rechaza(self):
        with self.assertRaises(ls.Refused): self.selftest(SHIM_NO_IFMATCH_HELP="1")

    def test_el_bucket_de_respaldos_jamas_se_acepta(self):
        for b in ("nexoeventos-recovery", "nexoeventos-lease-test/../x", "otro", "nexoeventos-lease-testX!"):
            with self.assertRaises(ls.Refused): self.selftest(bucket=b)
        self.assertEqual(self.calls(), [])                                              # ni una llamada

    def test_tope_de_tiempo(self):
        runner = self.runner()
        with self.assertRaises(ls.Refused) as cm:
            ls.run_selftest("ns", "nexoeventos-lease-test", "P", "A", rounds=5, writers=8, max_minutes=0.0001, oci=str(self.shim), runner=runner, log=lambda *_: None)
        self.assertEqual(cm.exception.code, 3); self.assertEqual(self.objects(), [])      # limpió aunque abortó

    def test_la_limpieza_solo_borra_objetos_selftest(self):
        (self.bucket_dir / "respaldo-real.data").write_text("x"); (self.bucket_dir / "respaldo-real.gen").write_text("1")
        n = ls.cleanup(str(self.shim), "ns", "nexoeventos-lease-test", "ADMIN", ["respaldo-real", "selftest-a"], self.runner())
        self.assertEqual(n, 1); self.assertIn("respaldo-real.data", self.objects())


class Cli(Base):
    def cli(self, *extra, env=None):
        e = {k: v for k, v in os.environ.items() if k != "NEXO_ALLOW_LEASE_SELFTEST"}; e.update(env or {})
        return subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "..", "lease_selftest.py"), "--namespace", "ns", "--profile", "P", "--cleanup-profile", "A", "--oci-bin", str(self.shim), *extra], capture_output=True, text=True, env=e)

    def test_por_defecto_solo_planifica_y_no_llama_a_la_nube(self):
        r = self.cli("--bucket", "nexoeventos-lease-test"); self.assertEqual(r.returncode, 0); self.assertIn("PLAN (no se llamó a la nube)", r.stdout); self.assertEqual(self.calls(), [])

    def test_ejecutar_exige_entorno_frase_exacta_y_parametros_minimos(self):
        phrase = ls.PHRASE.format(bucket="nexoeventos-lease-test")
        self.assertEqual(self.cli("--bucket", "nexoeventos-lease-test", "--execute", "--confirm", phrase).returncode, 2)                              # sin entorno
        env = {"NEXO_ALLOW_LEASE_SELFTEST": "YES", "SHIM_DIR": str(self.bucket_dir)}
        self.assertEqual(self.cli("--bucket", "nexoeventos-lease-test", "--execute", "--confirm", "si", env=env).returncode, 2)                      # frase mala
        self.assertEqual(self.cli("--bucket", "nexoeventos-lease-test", "--execute", "--confirm", phrase, "--writers", "2", env=env).returncode, 2)  # muy pocos escritores
        self.assertEqual(self.calls(), [])
        r = self.cli("--bucket", "nexoeventos-recovery", "--execute", "--confirm", ls.PHRASE.format(bucket="nexoeventos-recovery"), env=env); self.assertEqual(r.returncode, 2)

    def test_ejecucion_correcta_por_cli_y_salida_sin_secretos(self):
        phrase = ls.PHRASE.format(bucket="nexoeventos-lease-test")
        r = self.cli("--bucket", "nexoeventos-lease-test", "--execute", "--confirm", phrase, "--rounds", "5", "--writers", "8", env={"NEXO_ALLOW_LEASE_SELFTEST": "YES", "SHIM_DIR": str(self.bucket_dir)})
        self.assertEqual(r.returncode, 0, r.stderr[-300:]); rep = json.loads(r.stdout); self.assertEqual(rep["pasos"]["2_carrera"]["ganadores_por_ronda"], [1] * 5)
        for bad in ("ocid1.", "BEGIN", "token"): self.assertNotIn(bad, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
