import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]; TOOL = ROOT / "scripts/multicloud/hybrid/lease_keys.py"; PY = ROOT / "backend/.venv/bin/python"
GEN = "GENERAR CLAVES DEL LEASE"


def sh(*a, env=None):
    return subprocess.run([str(PY if PY.exists() else sys.executable), str(TOOL), *a], capture_output=True, text=True, env={**os.environ, **(env or {})})


def modes(d): return {str(p.relative_to(d)): oct(p.stat().st_mode & 0o777) for p in Path(d).rglob("*")}


class Keys(unittest.TestCase):
    def setUp(self): self.base = Path(tempfile.mkdtemp()); self.out = self.base / "claves"

    def gen(self, scheme="ed25519", **kw):
        return sh("generate", "--out-dir", str(self.out), "--holders", "aws,oci", "--scheme", scheme, "--confirm", kw.get("confirm", GEN), env={"NEXO_ALLOW_KEY_GENERATION": kw.get("allow", "YES")})

    def secretos(self):
        out = []
        for p in self.out.rglob("*"):
            if p.is_file(): out.append(p.read_text().strip())
        return out

    def test_doble_llave_y_no_imprime_ninguna_clave(self):
        self.assertEqual(self.gen(confirm="x").returncode, 3); self.assertEqual(self.gen(allow="NO").returncode, 3); self.assertFalse(self.out.exists())
        r = self.gen(); self.assertEqual(r.returncode, 0, r.stderr)
        for s in self.secretos():
            for trozo in {s, *s.replace('"', " ").replace(",", " ").replace(":", " ").replace("[", " ").replace("]", " ").replace("{", " ").replace("}", " ").split()}:
                if len(trozo) >= 20: self.assertNotIn(trozo, r.stdout + r.stderr)

    def test_permisos_0700_0600_y_cada_nodo_solo_tiene_su_privada(self):
        self.assertEqual(self.gen().returncode, 0)
        m = modes(self.out); self.assertTrue(all(v in ("0o700", "0o600") for v in m.values()), m)
        self.assertEqual(oct(self.out.stat().st_mode & 0o777), "0o700")
        priv_aws = (self.out / "aws/lease-signing.key").read_text().strip(); priv_oci = (self.out / "oci/lease-signing.key").read_text().strip()
        self.assertNotEqual(priv_aws, priv_oci)
        self.assertNotIn(priv_oci, (self.out / "aws/lease-peers.json").read_text()); self.assertNotIn(priv_aws, (self.out / "oci/lease-peers.json").read_text())   # nadie tiene la privada ajena
        self.assertEqual(sorted(json.loads((self.out / "aws/lease-peers.json").read_text())), ["oci"])

    def test_pareja_firma_en_un_nodo_y_verifica_en_el_otro(self):
        for scheme in ("ed25519", "hmac"):
            self.out = self.base / f"c-{scheme}"; self.assertEqual(self.gen(scheme).returncode, 0)
            self.assertEqual(sh("verify", "--node-dir", str(self.out / "aws"), "--holder", "aws").returncode, 0)
            r = sh("verify-pair", "--node-dir", str(self.out / "aws"), "--holder", "aws", "--peer-dir", str(self.out / "oci"), "--peer-holder", "oci"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_rechaza_git_carpeta_no_vacia_y_permisos_abiertos(self):
        repo = self.base / "repo"; (repo / ".git").mkdir(parents=True); self.out = repo / "claves"; self.assertEqual(self.gen().returncode, 2)
        self.out = self.base / "vacia"; self.out.mkdir(); (self.out / "x").write_text("a"); self.assertEqual(self.gen().returncode, 2)
        self.out = self.base / "ok"; self.assertEqual(self.gen().returncode, 0); self.assertNotEqual(self.gen().returncode, 0)         # no sobrescribe
        os.chmod(self.out / "aws/lease-signing.key", 0o644)
        self.assertEqual(sh("verify", "--node-dir", str(self.out / "aws"), "--holder", "aws").returncode, 2)

    def test_hmac_repetido_o_trivial_se_rechaza_y_la_rotacion_acepta_dos_publicas(self):
        self.assertEqual(self.gen("hmac").returncode, 0)
        p = self.out / "aws/lease-auth.json"; d = json.loads(p.read_text()); d["oci"] = d["aws"]; os.chmod(p, 0o600); p.write_text(json.dumps(d))
        self.assertEqual(sh("verify", "--node-dir", str(self.out / "aws"), "--holder", "aws").returncode, 2)
        # rotación Ed25519: la pública NUEVA se añade a la lista del par ANTES de firmar con ella; ambas verifican
        self.out = self.base / "rot"; self.gen(); sys.path.insert(0, str(ROOT / "backend"))
        from app.failover.lease import Ed25519Auth
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import base64
        vieja = base64.b64decode((self.out / "oci/lease-signing.key").read_text().strip()); nueva = Ed25519PrivateKey.generate()
        raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        pubn = nueva.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        peers_aws = {h: [base64.b64decode(k) for k in ks] for h, ks in json.loads((self.out / "aws/lease-peers.json").read_text()).items()}; peers_aws["oci"].append(pubn)
        aws = Ed25519Auth("aws", base64.b64decode((self.out / "aws/lease-signing.key").read_text().strip()), peers_aws)
        for priv in (vieja, raw(nueva)):
            o = Ed25519Auth("oci", priv, {"aws": [b"\x00" * 32]}); self.assertTrue(aws.verify("oci", b"m", o.sign("oci", b"m")))


if __name__ == "__main__":
    unittest.main()
