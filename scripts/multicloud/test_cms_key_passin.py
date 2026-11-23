#!/usr/bin/env python3
"""Prueba LOCAL (S-01) del soporte de claves privadas CMS protegidas con contraseña: lib-cms-key.sh, restore-drill.sh, prepare-oci-transfer.sh y
cms_decrypt() de scripts/cloud/db-backup-cms.py. Claves DESECHABLES en un directorio temporal (la clave real no se lee ni se modifica); PostgreSQL y Docker
se sustituyen por programas falsos en el PATH (psql/pg_restore), sin tocar ninguna base. No usa red ni credenciales.
Casos: éxito con clave protegida (env:/file:/fd:), clave sin contraseña (compatibilidad), contraseña incorrecta, contraseña ausente (sin colgarse),
`pass:` rechazado, archivo alterado, clave distinta, variable inexistente; y que la contraseña nunca aparece en la salida ni en los errores.
Uso: backend/.venv/bin/python scripts/multicloud/test_cms_key_passin.py"""
import importlib.util
import json
import os
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
H = ROOT / "scripts/multicloud"
SECRET = "Contra$ena-De-Prueba-NO-REAL-7431"
PLAIN = b"PGDMP" + bytes(range(256)) * 20


def run_ok(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"preparación de claves de prueba falló ({cmd[1]}): {r.stderr.decode(errors='replace')[:300]}")
    return r


def sh(cmd, env=None, timeout=30, **kw):
    e = {**os.environ, **(env or {})}
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, env=e, timeout=timeout, stdin=subprocess.DEVNULL, **kw)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = cls.t = Path(cls.tmp.name)
        # clave protegida + certificado; clave sin contraseña + certificado; clave ajena
        env = {**os.environ, "KP": SECRET}
        run_ok(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-aes-256-cbc", "-pass", "env:KP", "-out", str(t / "prot.pem")],
                env=env)
        run_ok(["openssl", "req", "-x509", "-new", "-key", str(t / "prot.pem"), "-passin", "env:KP", "-days", "2", "-subj", "/CN=prot", "-out", str(t / "prot.crt")],
                env=env)
        for n in ("plain", "other"):
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(t / f"{n}.pem"), "-out", str(t / f"{n}.crt"), "-days", "2",
                            "-subj", f"/CN={n}"], check=True, capture_output=True)
        (t / "dump.bin").write_bytes(PLAIN)
        for n in ("prot", "plain"):
            subprocess.run(["openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-outform", "DER", "-in", str(t / "dump.bin"), "-out", str(t / f"{n}.cms"), str(t / f"{n}.crt")],
                           check=True, capture_output=True)
        tam = bytearray((t / "prot.cms").read_bytes()); tam[len(tam) // 2] ^= 0xFF
        (t / "tampered.cms").write_bytes(bytes(tam))
        (t / "pass.txt").write_text(SECRET + "\n"); os.chmod(t / "pass.txt", 0o600)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def dec(self, cms, key, passin="", out="-", env=None):
        cmd = f'source {H}/lib-cms-key.sh; set -e; cms_decrypt_key "{self.t/cms}" "{self.t/key}" "{passin}" "{out}"'
        return sh(cmd, env=env)

    def no_leak(self, *rs):
        for r in rs:
            self.assertNotIn(SECRET, r.stdout if isinstance(r.stdout, str) else "")
            self.assertNotIn(SECRET, r.stderr if isinstance(r.stderr, str) else "")


class TestLib(Base):
    def test_clave_sin_contrasena_sigue_funcionando(self):
        r = sh(f'source {H}/lib-cms-key.sh; cms_decrypt_key "{self.t/"plain.cms"}" "{self.t/"plain.pem"}" "" "{self.t/"o1.bin"}"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.t / "o1.bin").read_bytes(), PLAIN)

    def test_protegida_con_env_file_y_fd(self):
        for spec, env, pre in (("env:NEXO_T_PASS", {"NEXO_T_PASS": SECRET}, ""), (f"file:{self.t/'pass.txt'}", {}, ""), ("fd:3", {}, f"exec 3<{self.t/'pass.txt'}; ")):
            out = self.t / "o2.bin"; out.unlink(missing_ok=True)
            r = sh(f'{pre}source {H}/lib-cms-key.sh; cms_decrypt_key "{self.t/"prot.cms"}" "{self.t/"prot.pem"}" "{spec}" "{out}"', env=env)
            self.assertEqual(r.returncode, 0, (spec, r.stderr))
            self.assertEqual(out.read_bytes(), PLAIN)
            self.no_leak(r)

    def test_salida_por_stdout_para_tuberias(self):
        r = subprocess.run(["bash", "-c", f'source {H}/lib-cms-key.sh; cms_decrypt_key "{self.t/"prot.cms"}" "{self.t/"prot.pem"}" env:NEXO_T_PASS -'],
                           capture_output=True, env={**os.environ, "NEXO_T_PASS": SECRET}, stdin=subprocess.DEVNULL, timeout=30)
        self.assertEqual(r.returncode, 0); self.assertEqual(r.stdout, PLAIN)

    def test_contrasena_incorrecta(self):
        r = self.dec("prot.cms", "prot.pem", "env:NEXO_T_PASS", env={"NEXO_T_PASS": "otra-contrasena-equivocada"})
        self.assertEqual(r.returncode, 1); self.assertIn("contraseña incorrecta", r.stderr)
        self.assertNotIn("otra-contrasena-equivocada", r.stderr + r.stdout); self.no_leak(r)

    def test_sin_contrasena_no_se_cuelga_y_explica(self):
        r = self.dec("prot.cms", "prot.pem", "")  # timeout=30 en sh(): si esperara en la terminal, la prueba fallaría
        self.assertEqual(r.returncode, 3); self.assertIn("protegida con contraseña", r.stderr); self.assertIn("--passin", r.stderr)

    def test_variable_inexistente_falla_sin_colgarse(self):
        r = self.dec("prot.cms", "prot.pem", "env:NEXO_VARIABLE_QUE_NO_EXISTE")
        self.assertEqual(r.returncode, 1); self.assertIn("contraseña", r.stderr)

    def test_pass_literal_rechazado(self):
        r = self.dec("prot.cms", "prot.pem", f"pass:{SECRET}")
        self.assertEqual(r.returncode, 2); self.assertIn("pass:", r.stderr); self.no_leak(r)

    def test_formato_desconocido_rechazado(self):
        self.assertEqual(self.dec("prot.cms", "prot.pem", "stdin").returncode, 2)

    def test_archivo_alterado_y_clave_distinta(self):
        # CMS con AES-CBC no autentica: una alteración puede fallar al descifrar o producir texto distinto; nunca debe devolver el original.
        # La integridad la garantiza el SHA-256 del texto plano que verifica restore-drill.sh (ver TestRestoreDrill.test_archivo_alterado).
        out = self.t / "o3.bin"; out.unlink(missing_ok=True)
        r = self.dec("tampered.cms", "prot.pem", "env:NEXO_T_PASS", out=str(out), env={"NEXO_T_PASS": SECRET})
        self.assertTrue(r.returncode != 0 or out.read_bytes() != PLAIN)
        # Con una clave que no es la del destinatario, openssl (defensa contra Bleichenbacher) puede devolver basura con código 0: nunca el original.
        out = self.t / "o4.bin"; out.unlink(missing_ok=True)
        r = self.dec("plain.cms", "other.pem", out=str(out))
        self.assertTrue(r.returncode != 0 or out.read_bytes() != PLAIN)


class TestRestoreDrill(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        t = cls.t
        shim = t / "shim"; shim.mkdir()
        (shim / "psql").write_text('#!/usr/bin/env bash\nif [[ "$*" == *"-d drill"* && "$*" == *"-At"* ]]; then echo "reservations=3"; echo "alembic=0008"; fi\nexit 0\n')
        (shim / "pg_restore").write_text('#!/usr/bin/env bash\nif [[ "$1" == "--list" ]]; then echo "; catalogo de prueba"; echo "1; 0 0 TABLE x"; fi\ncat >/dev/null\nexit 0\n')
        for f in shim.iterdir(): f.chmod(0o755)
        cls.shim = shim
        (t / "baseline.json").write_text(json.dumps({"baselines": {"k": {"fingerprint": {"reservations": "3", "alembic": "0008"}}}}))
        for n in ("prot", "plain"):
            b = (t / f"{n}.cms").read_bytes()
            (t / f"{n}.manifest.json").write_text(json.dumps({"oci_cms_sha256": hashlib.sha256(b).hexdigest(), "oci_cms_bytes": len(b),
                                                              "plaintext_dump_sha256": hashlib.sha256(PLAIN).hexdigest()}))

    def drill(self, n, key, *extra, env=None):
        e = {**(env or {}), "PATH": f"{self.shim}:{os.environ['PATH']}"}
        args = " ".join(f'"{x}"' for x in extra)
        return sh(f'{H}/restore-drill.sh --manifest "{self.t/(n+".manifest.json")}" --cms "{self.t/(n+".cms")}" --key "{self.t/key}" --baseline "{self.t/"baseline.json"}" '
                  f'--baseline-key k --mode local {args}', env=e)

    def test_exito_clave_protegida(self):
        r = self.drill("prot", "prot.pem", "--passin", "env:NEXO_T_PASS", env={"NEXO_T_PASS": SECRET})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("descifrado correcto", r.stdout); self.assertIn("huella idéntica", r.stdout); self.no_leak(r)

    def test_compatibilidad_clave_sin_contrasena(self):
        r = self.drill("plain", "plain.pem")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("huella idéntica", r.stdout)

    def test_contrasena_incorrecta_falla_con_motivo_visible(self):
        r = self.drill("prot", "prot.pem", "--passin", "env:NEXO_T_PASS", env={"NEXO_T_PASS": "equivocada"})
        self.assertNotEqual(r.returncode, 0); self.assertIn("FALLÓ", r.stderr); self.assertIn("contraseña incorrecta", r.stderr)
        self.assertNotIn("restauración en base aislada", r.stdout)

    def test_sin_contrasena_falla_con_instruccion(self):
        r = self.drill("prot", "prot.pem")
        self.assertNotEqual(r.returncode, 0); self.assertIn("--passin", r.stderr); self.assertNotIn("descifrado correcto", r.stdout)

    def test_pass_literal_rechazado_y_no_se_filtra(self):
        r = self.drill("prot", "prot.pem", "--passin", f"pass:{SECRET}")
        self.assertNotEqual(r.returncode, 0); self.assertIn("pass:", r.stderr); self.no_leak(r)

    def test_archivo_alterado_falla_con_motivo(self):
        t = self.t; b = (t / "tampered.cms").read_bytes()
        (t / "tampered.manifest.json").write_text(json.dumps({"oci_cms_sha256": hashlib.sha256(b).hexdigest(), "oci_cms_bytes": len(b),
                                                              "plaintext_dump_sha256": hashlib.sha256(PLAIN).hexdigest()}))
        (t / "tampered.cms")  # el manifiesto coincide con el archivo alterado: solo el hash del texto plano o el descifrado pueden detectarlo
        r = self.drill("tampered", "prot.pem", "--passin", "env:NEXO_T_PASS", env={"NEXO_T_PASS": SECRET})
        self.assertNotEqual(r.returncode, 0); self.assertIn("FALLÓ", r.stderr); self.assertNotIn("restauración en base aislada", r.stdout)

    def test_error_de_pg_restore_no_queda_oculto(self):
        (self.shim / "pg_restore").write_text('#!/usr/bin/env bash\necho "pg_restore: error simulado" >&2\nexit 1\n')
        try:
            r = self.drill("plain", "plain.pem")
            self.assertNotEqual(r.returncode, 0); self.assertIn("FALLÓ", r.stderr)
        finally:
            (self.shim / "pg_restore").write_text('#!/usr/bin/env bash\nif [[ "$1" == "--list" ]]; then echo "; catalogo de prueba"; echo "1; 0 0 TABLE x"; fi\ncat >/dev/null\nexit 0\n')


class TestPrepareTransfer(Base):
    def run_prepare(self, passin_env):
        out = self.t / f"out-{abs(hash(str(passin_env)))}"
        env = {"NEXO_AWS_KEY_PASSIN": "env:NEXO_T_PASS", **passin_env}
        r = sh(f'{H}/prepare-oci-transfer.sh "{self.t/"prot.cms"}" "{self.t/"prot.pem"}" "{self.t/"other.crt"}" "{out}"', env=env)
        return r, out

    def test_exito_y_manifiesto(self):
        r, out = self.run_prepare({"NEXO_T_PASS": SECRET})
        self.assertEqual(r.returncode, 0, r.stderr)
        m = json.loads((out / "prot.manifest.json").read_text())
        self.assertEqual(m["plaintext_dump_sha256"], hashlib.sha256(PLAIN).hexdigest()); self.no_leak(r)

    def test_clave_equivocada_que_descifra_a_basura_se_detecta(self):
        out = self.t / "out-clave-ajena"
        r = sh(f'{H}/prepare-oci-transfer.sh "{self.t/"plain.cms"}" "{self.t/"other.pem"}" "{self.t/"other.crt"}" "{out}"')
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(list(out.glob("*.oci.cms")))

    def test_contrasena_incorrecta_no_deja_cms_aparente(self):
        r, out = self.run_prepare({"NEXO_T_PASS": "equivocada"})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(list(out.glob("*.oci.cms")), "no debe quedar un CMS para OCI tras un descifrado fallido")
        self.assertIn("contraseña", r.stderr)


class TestDbBackupDecrypt(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        spec = importlib.util.spec_from_file_location("dbb", ROOT / "scripts/cloud/db-backup-cms.py")
        cls.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.m)

    def test_casos(self):
        t = self.t
        os.environ["NEXO_T_PASS"] = SECRET
        try:
            ok, plain, why = self.m.cms_decrypt(t / "prot.cms", str(t / "prot.pem"), "env:NEXO_T_PASS")
            self.assertTrue(ok); self.assertEqual(plain, PLAIN); self.assertIsNone(why)
            ok, plain, why = self.m.cms_decrypt(t / "plain.cms", str(t / "plain.pem"), "")  # compatibilidad
            self.assertTrue(ok)
            os.environ["NEXO_T_PASS"] = "equivocada"
            ok, plain, why = self.m.cms_decrypt(t / "prot.cms", str(t / "prot.pem"), "env:NEXO_T_PASS")
            self.assertFalse(ok); self.assertIn("contraseña", why)
        finally:
            os.environ.pop("NEXO_T_PASS", None)
        ok, _, why = self.m.cms_decrypt(t / "prot.cms", str(t / "prot.pem"), "")
        self.assertFalse(ok); self.assertIn("--passin", why)
        ok, _, why = self.m.cms_decrypt(t / "prot.cms", str(t / "prot.pem"), f"pass:{SECRET}")
        self.assertFalse(ok); self.assertNotIn(SECRET, why)
        ok, _, why = self.m.cms_decrypt(t / "tampered.cms", str(t / "plain.pem"), "")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
