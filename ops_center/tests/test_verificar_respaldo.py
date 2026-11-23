"""verificar_respaldo_c04.py con paquetes SINTÉTICOS (claves, certificado y CMS reales de openssl): válido y cada manipulación debe ser detectada. Sin nube, sin frases."""
import base64, hashlib, json, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import verificar_respaldo_c04 as V  # noqa: E402


def run(*a, **k): return subprocess.run(list(a), check=True, capture_output=True, **k)


def cert(tmp, name):
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(tmp / f"{name}.key"), "-out", str(tmp / f"{name}.crt"), "-days", "30", "-subj", f"/CN={name}")
    fp = subprocess.run(f"openssl x509 -in {tmp}/{name}.crt -outform DER | openssl sha256 | awk '{{print $NF}}'", shell=True, capture_output=True, text=True).stdout.strip(); return tmp / f"{name}.crt", fp


@pytest.fixture
def env(tmp_path):
    t = tmp_path; crt, fp = cert(t, "dest"); other, fp2 = cert(t, "otro")
    run("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(t / "sign.key")); run("openssl", "ec", "-in", str(t / "sign.key"), "-pubout", "-out", str(t / "sign.pub"))
    def bundle(name, kind, cert_file=crt, tamper=None):
        (t / "plain").write_bytes(b"datos de prueba " * 50); run("openssl", "cms", "-encrypt", "-binary", "-aes256", "-outform", "DER", "-in", str(t / "plain"), "-out", str(t / f"{name}.cms"), str(cert_file))
        data = (t / f"{name}.cms").read_bytes(); m = {"oci_cms_sha256" if kind == "datos" else "cms_sha256": hashlib.sha256(data).hexdigest(), "oci_cms_bytes" if kind == "datos" else "cms_bytes": len(data)}
        if kind == "claves": m["recipient_cert_sha256"] = fp
        (t / f"{name}.manifest.json").write_text(json.dumps(m)); run("openssl", "dgst", "-sha256", "-sign", str(t / "sign.key"), "-out", str(t / f"{name}.manifest.json.sig"), str(t / f"{name}.manifest.json"))
        if tamper == "manifiesto": (t / f"{name}.manifest.json").write_text(json.dumps({**m, "x": 1}))
        if tamper == "cms": (t / f"{name}.cms").write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    return t, crt, fp, bundle


def check(env, name="d1", kind="datos", fp_override=None, remote=None, **kw):
    t, crt, fp, bundle = env; bundle(name, kind, **kw); return V.verify_one(t, name, kind, crt, fp_override or fp, t / "sign.pub", remote)


def test_paquete_valido_es_integro(env):
    for kind in ("datos", "claves"):
        r = check(env, f"p-{kind}", kind); assert r["ok"], r["comprobaciones"]


@pytest.mark.parametrize("kw,clave", [({"tamper": "manifiesto"}, "firma_del_manifiesto"), ({"tamper": "cms"}, "sha256_y_tamano_del_cifrado")])
def test_manipulaciones_se_detectan(env, kw, clave):
    r = check(env, **kw); assert not r["ok"] and not r["comprobaciones"][clave]["ok"]


def test_cms_para_otro_certificado_o_huella_distinta_se_rechaza(env):
    t, crt, fp, bundle = env; other = t / "otro.crt"
    r = check(env, "x1", cert_file=other); assert not r["ok"] and not r["comprobaciones"]["cms_dirigido_al_certificado"]["ok"]
    r = check(env, "x2", fp_override="0" * 64); assert not r["ok"] and not r["comprobaciones"]["certificado_con_la_huella_fijada"]["ok"]


def test_bucket_distinto_o_ilegible_se_rechaza(env):
    r = check(env, "b1", remote=lambda n: "AAAA=="); assert not r["ok"] and not r["comprobaciones"]["bucket_igual_a_la_copia_local_md5"]["ok"]
    r = check(env, "b2", remote=lambda n: None); assert not r["ok"]
    t = env[0]; good = base64.b64encode(hashlib.md5((t / "b3.cms").read_bytes() if (t / "b3.cms").exists() else b"").digest()).decode()
    env[3]("b3", "datos"); good = base64.b64encode(hashlib.md5((t / "b3.cms").read_bytes()).digest()).decode()
    r = V.verify_one(t, "b3", "datos", env[1], env[2], t / "sign.pub", lambda n: good); assert r["ok"], r["comprobaciones"]


def test_archivo_ausente_es_fallo(env):
    t, crt, fp, bundle = env; r = V.verify_one(t, "no-existe", "datos", crt, fp, t / "sign.pub"); assert not r["ok"]
