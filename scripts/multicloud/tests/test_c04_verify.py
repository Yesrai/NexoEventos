"""c04_verify.py con un lector FALSO en memoria (sin OCI, sin red): ciclos válidos, sustitución, firma inválida, nombre ya existente y ciclos insuficientes.
Uso: backend/.venv/bin/python -m unittest discover -s scripts/multicloud/tests -p 'test_c04_verify.py' -v"""
import hashlib, json, subprocess, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for sub in ("scripts/multicloud/failover", "scripts/multicloud"):
    sys.path.insert(0, str(ROOT / sub))
import c04_verify as cv  # noqa: E402
import oci_source as oc  # noqa: E402

T0 = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)


class FakeReader:
    def __init__(self, store): self.store = store
    def list_stems(self): return sorted(n[: -len(oc.MANIFEST_SUFFIX)] for n in self.store if n.endswith(oc.MANIFEST_SUFFIX))
    def get(self, name, max_bytes, sink=None, expected_size=None):
        if name not in self.store: raise oc.FetchError("no existe")
        data = self.store[name]
        if len(data) > max_bytes: raise oc.FetchError("excede")
        if expected_size is not None and len(data) != expected_size: raise oc.FetchError("tamaño")
        if sink is None: return data
        Path(sink).write_bytes(data); return len(data)


def keypair(d: Path, name: str):
    priv, pub = d / f"{name}.key", d / f"{name}.pub"
    subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(priv)], check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(priv), "-pubout", "-out", str(pub)], check=True, capture_output=True)
    return priv, pub


def sign(priv: Path, data: bytes) -> bytes:
    return subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(priv)], input=data, capture_output=True, check=True).stdout


def build(priv, minutes, cert=None):
    store = {}
    for i, mins in enumerate(minutes):
        ts = (T0 + timedelta(minutes=mins))
        stem = f"nexoeventos-rds-{ts:%Y%m%dT%H%M%SZ}"
        blob = (f"cms-{i}-" * 50).encode()
        m = {"schema": 1, "name": stem, "object_name": stem + ".oci.cms", "created_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "env": "aws-academy",
             "oci_cms_sha256": hashlib.sha256(blob).hexdigest(), "oci_cms_bytes": len(blob), "plaintext_dump_sha256": "a" * 64}
        if cert: m["recipient_cert_sha256"] = cert
        mb = json.dumps(m).encode()
        store.update({stem + ".oci.cms": blob, stem + oc.MANIFEST_SUFFIX: mb, stem + oc.SIG_SUFFIX: sign(priv, mb)})
    return store


class C04VerifyTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.d = Path(self._td.name)
        self.priv, self.pub = keypair(self.d, "firma")
        self.other_priv, _ = keypair(self.d, "otra")
    def tearDown(self): self._td.cleanup()
    def run_(self, store, **kw):
        base = dict(since=T0 - timedelta(minutes=1), before=set(), expect=3, env="aws-academy")
        base.update(kw)
        return cv.verify_cycles(FakeReader(store), self.pub, **base)

    def test_three_valid_signed_cycles_are_admissible_and_rpo_is_an_observation(self):
        r = self.run_(build(self.priv, [0, 31, 60]))
        self.assertTrue(r["ok"]); self.assertEqual(r["intervalos_min"], [31.0, 29.0]); self.assertEqual(r["rpo_observado_max_min"], 31.0)
        self.assertIn("no es un RPO garantizado", r["rpo_observado_nota"])

    def test_certificate_identity_in_manifest_is_enforced_when_expected(self):
        good, bad = "5c6d" * 16, "981c" * 16
        r = self.run_(build(self.priv, [0, 30, 60], cert=good), expect_cert_sha256=":".join(good[i:i + 2] for i in range(0, 64, 2)).upper())
        self.assertTrue(r["ok"]); self.assertTrue(all(c["certificado"] == "ok" for c in r["ciclos"]))
        r = self.run_(build(self.priv, [0, 30, 60], cert=bad), expect_cert_sha256=good)
        self.assertFalse(r["ok"]); self.assertTrue(all(c["certificado"] == "distinto" for c in r["ciclos"]))
        r = self.run_(build(self.priv, [0, 30, 60]), expect_cert_sha256=good)  # respaldos anteriores al campo: se aceptan con advertencia
        self.assertTrue(r["ok"]); self.assertTrue(any("recipient_cert_sha256" in w for w in r["advertencias"]))

    def test_older_backups_are_not_counted_as_cycles(self):
        store = build(self.priv, [-60 * 24 * 7, 0, 30, 60])
        r = self.run_(store); self.assertTrue(r["ok"]); self.assertEqual(len(r["ciclos"]), 3)

    def test_invalid_signature_fails(self):
        store = build(self.priv, [0, 30, 60]); stem = sorted(store)[0].split(".")[0]
        store[stem + oc.SIG_SUFFIX] = sign(self.other_priv, store[stem + oc.MANIFEST_SUFFIX])
        r = self.run_(store); self.assertFalse(r["ok"]); self.assertFalse([c for c in r["ciclos"] if c["stem"] == stem][0]["firma_ok"])

    def test_tampered_object_fails_sha256(self):
        store = build(self.priv, [0, 30, 60]); name = [k for k in store if k.endswith(".oci.cms")][1]
        store[name] = store[name][:-1] + b"X"
        r = self.run_(store); self.assertFalse(r["ok"]); self.assertEqual(sum(1 for c in r["ciclos"] if not c["objeto_ok"]), 1)

    def test_name_that_already_existed_before_the_test_is_rejected(self):
        store = build(self.priv, [0, 30, 60]); first = sorted(k for k in store if k.endswith(oc.MANIFEST_SUFFIX))[0]
        r = self.run_(store, before={first}); self.assertFalse(r["ok"])
        self.assertFalse([c for c in r["ciclos"] if c["stem"] == first[: -len(oc.MANIFEST_SUFFIX)]][0]["nombre_nuevo"])

    def test_fewer_cycles_than_expected_is_not_ok(self):
        r = self.run_(build(self.priv, [0, 30])); self.assertFalse(r["ok"]); self.assertTrue(any("se esperaban 3" in w for w in r["advertencias"]))

    def test_wrong_environment_is_rejected(self):
        r = self.run_(build(self.priv, [0, 30, 60]), env="otro-entorno"); self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
