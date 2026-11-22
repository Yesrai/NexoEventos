"""B-13 ↔ B-14 ↔ S-01 · El orquestador usa un `restore_latest` REAL (local): respaldos cifrados de verdad (backup_cycle.dump_and_encrypt), manifiestos reales,
clave privada protegida con contraseña y restore-drill.sh; solo PostgreSQL (psql/pg_restore) y la nube están sustituidos. Claves desechables; no hay red, Docker ni nubes.
Uso: backend/.venv/bin/python -m unittest discover -s scripts/multicloud/tests -p 'test_backup_source.py' -v"""
import json, os, subprocess, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for sub in ("scripts/multicloud/failover", "scripts/multicloud", "backend"):
    sys.path.insert(0, str(ROOT / sub))
import backup_cycle as bc  # noqa: E402
import backup_source as bs  # noqa: E402
import sim  # noqa: E402
from orchestrator import Config, Orchestrator, State  # noqa: E402

SECRET = "frase-de-prueba-no-real-9921"
FP_BEFORE = {"alembic": "0008", "reservations": "10", "inventory_md5": "aaa"}
FP_AFTER = {"alembic": "0008", "reservations": "12", "inventory_md5": "bbb"}
UTC = timezone.utc


def dump_bytes(tag: str) -> bytes:
    return b"PGDMP" + tag.encode() + bytes(range(256)) * 8


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); t = cls.t = Path(cls.tmp.name)
        env = {**os.environ, "KP": SECRET}
        for cmd in (["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-aes-256-cbc", "-pass", "env:KP", "-out", str(t / "k.pem")],
                    ["openssl", "req", "-x509", "-new", "-key", str(t / "k.pem"), "-passin", "env:KP", "-days", "2", "-subj", "/CN=t", "-out", str(t / "c.crt")]):
            r = subprocess.run(cmd, capture_output=True, env=env, stdin=subprocess.DEVNULL)
            assert r.returncode == 0, r.stderr.decode()[:200]
        shim = cls.shim = t / "shim"; shim.mkdir()
        (shim / "psql").write_text('#!/usr/bin/env bash\nif [[ "$*" == *"-d drill"* && "$*" == *"-At"* ]]; then echo "alembic=0008"; echo "reservations=${SHIM_RES:-11}"; echo "inventory_md5=${SHIM_MD5:-aaa}"; fi\nexit 0\n')
        (shim / "pg_restore").write_text('#!/usr/bin/env bash\nif [[ "$1" == "--list" ]]; then echo "; toc"; echo "1; 0 0 TABLE x"; fi\ncat >/dev/null\nexit 0\n')
        for f in shim.iterdir(): f.chmod(0o755)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(dir=self.tmp.name))
        self.now = datetime.now(UTC).replace(microsecond=0)

    def make_backup(self, minutes_ago, tag="a", fp=True, env="aws-academy"):
        t0 = self.now - timedelta(minutes=minutes_ago)
        name = f"nexoeventos-rds-{t0:%Y%m%dT%H%M%SZ}.cms"
        src = self.d / f".src-{tag}.bin"; src.write_bytes(dump_bytes(tag))
        info = bc.dump_and_encrypt(f"cat {src}", self.t / "c.crt", self.d / name)  # cifrado real con el certificado público; deja el .cms en su lugar
        src.unlink()
        m = bc.build_manifest(env, name, t0, info, FP_BEFORE if fp else None, FP_AFTER if fp else None)
        (self.d / f"{name[:-4]}.manifest.json").write_text(json.dumps(m))
        return name

    def restore(self, **kw):
        e = {**os.environ, "PATH": f"{self.shim}:{os.environ['PATH']}", "NEXO_T_PASS": kw.pop("password", SECRET), **kw.pop("extra_env", {})}
        return bs.restore_latest(self.d, self.t / "k.pem", kw.pop("passin", "env:NEXO_T_PASS"), now=self.now, restore_env=e, **kw)


class TestSelector(Base):
    def test_elige_el_mas_reciente_valido_y_lo_restaura_con_clave_protegida(self):
        self.make_backup(90, "viejo"); n = self.make_backup(10, "nuevo")
        r = self.restore()
        self.assertTrue(r["fingerprint_ok"], r); self.assertEqual(r["backup"], n[:-4]); self.assertAlmostEqual(r["backup_age_s"], 600, delta=1)
        self.assertNotIn(SECRET, json.dumps(r))

    def test_huella_dentro_del_rango_acepta_y_fuera_del_rango_rechaza(self):
        self.make_backup(5)
        self.assertTrue(self.restore(extra_env={"SHIM_RES": "12"})["fingerprint_ok"])   # el contador creció durante el volcado: entre 10 y 12
        r = self.restore(extra_env={"SHIM_RES": "13"})
        self.assertFalse(r["fingerprint_ok"]); self.assertIn("FALLÓ", r["reason"])
        r = self.restore(extra_env={"SHIM_RES": "9"})
        self.assertFalse(r["fingerprint_ok"])
        r = self.restore(extra_env={"SHIM_MD5": "ccc"})                               # hash que no es ni el de antes ni el de después
        self.assertFalse(r["fingerprint_ok"])

    def test_objeto_alterado_se_descarta_y_se_usa_el_anterior(self):
        ok_name = self.make_backup(60, "bueno"); bad = self.make_backup(5, "malo")
        p = self.d / bad; b = bytearray(p.read_bytes()); b[len(b) // 2] ^= 0xFF; p.write_bytes(bytes(b))
        r = self.restore()
        self.assertTrue(r["fingerprint_ok"], r); self.assertEqual(r["backup"], ok_name[:-4])
        self.assertTrue(any("SHA-256" in s["reason"] for s in r["skipped"]))

    def test_objeto_truncado_o_ausente_se_descarta(self):
        a = self.make_backup(60, "a"); b = self.make_backup(30, "b"); c = self.make_backup(5, "c")
        (self.d / c).write_bytes((self.d / c).read_bytes()[:100]); (self.d / b).unlink()
        r = self.restore(); self.assertEqual(r["backup"], a[:-4]); self.assertEqual(len(r["skipped"]), 2)

    def test_manifiesto_corrupto_o_incompleto_se_descarta(self):
        a = self.make_backup(60); (self.d / "zzz.manifest.json").write_text("{no es json")
        (self.d / "yyy.manifest.json").write_text(json.dumps({"name": "x"}))
        r = self.restore(); self.assertTrue(r["fingerprint_ok"]); self.assertEqual(r["backup"], a[:-4]); self.assertEqual(len(r["skipped"]), 2)

    def test_sin_huella_en_el_manifiesto_no_es_verificable(self):
        self.make_backup(5, fp=False)
        r = self.restore(); self.assertFalse(r["fingerprint_ok"]); self.assertIn("falla cerrada", r["reason"])

    def test_sin_respaldos_validos(self):
        r = self.restore(); self.assertFalse(r["fingerprint_ok"]); self.assertIn("ningún respaldo válido", r["reason"]); self.assertGreater(r["backup_age_s"], 1e9)

    def test_contrasena_incorrecta_o_ausente_falla_cerrado_sin_filtrar(self):
        self.make_backup(5)
        r = self.restore(password="equivocada-no-real"); self.assertFalse(r["fingerprint_ok"]); self.assertNotIn("equivocada-no-real", json.dumps(r))
        r = self.restore(passin=""); self.assertFalse(r["fingerprint_ok"])
        self.assertNotIn(SECRET, json.dumps(r))

    def test_filtro_por_entorno(self):
        self.make_backup(5, env="oci-recuperacion")
        self.assertFalse(self.restore(env="aws-academy")["fingerprint_ok"])
        self.assertTrue(self.restore(env="oci-recuperacion")["fingerprint_ok"])

    def test_manifiesto_no_puede_apuntar_fuera_del_directorio(self):
        n = self.make_backup(5); mp = self.d / f"{n[:-4]}.manifest.json"; m = json.loads(mp.read_text())
        m["object_name"] = "../../etc/passwd"; mp.write_text(json.dumps(m))
        r = self.restore(); self.assertFalse(r["fingerprint_ok"]); self.assertTrue(any("falta el objeto" in s["reason"] for s in r["skipped"]))


class RealRestoreAdapters(sim.SimAdapters):
    """Mundo simulado (sondas, lease, DNS) con el restore_latest REAL: lo único cruzado es el reloj de la simulación frente al reloj real del respaldo."""
    def __init__(self, w, test): super().__init__(w); self.test = test
    def restore_latest(self):
        self.w.restore_calls += 1
        return self.test.restore()


class TestOrquestadorConRestauracionReal(Base):
    def run_orch(self, cfg=None):
        w, _, c = sim.make("primary_dead", 1, None, "r")
        ad = RealRestoreAdapters(w, self)
        st = State(Path(tempfile.mkdtemp()) / "estado.json", "r")
        res = Orchestrator(ad, cfg or c, st, dry_run=False).run()
        w.advance(5)
        return res, w

    def test_respaldo_reciente_y_verificado_permite_promover_con_un_escritor(self):
        self.make_backup(3)
        res, w = self.run_orch()
        self.assertEqual(res["outcome"], "DONE", res); self.assertEqual((w.violations, w.dns_applied, w.dns_violation), (0, 1, False))

    def test_respaldo_demasiado_viejo_aborta_por_rpo_y_no_cambia_nada(self):
        self.make_backup(180)  # 3 h > max_backup_age_s (1 h)
        res, w = self.run_orch()
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("RPO", res["abort_reason"]); self.assertEqual((w.dns_applied, w.standby_wrote), (0, False))

    def test_huella_distinta_aborta_y_no_toca_el_dns(self):
        self.make_backup(3)
        orig = self.restore
        self.restore = lambda: orig(extra_env={"SHIM_RES": "99"})
        res, w = self.run_orch()
        self.assertEqual(res["outcome"], "ABORTED"); self.assertIn("huella", res["abort_reason"]); self.assertEqual((w.dns_applied, w.standby_wrote), (0, False))

    def test_sin_respaldos_o_sin_huella_aborta(self):
        res, w = self.run_orch()
        self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.dns_applied, 0)
        self.make_backup(3, fp=False)
        res, w = self.run_orch()
        self.assertEqual(res["outcome"], "ABORTED"); self.assertEqual(w.dns_applied, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
