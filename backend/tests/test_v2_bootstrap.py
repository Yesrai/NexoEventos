"""Arranque de las instancias de V2 (user_data): CA de RDS fijada por huella, DATABASE_URL con verify-full y falla segura. Sin nube: `aws`, `curl` y `systemctl` son falsos."""
import base64
import datetime
import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "deploy/v2/bootstrap-instance.sh.tftpl"
HOST = "db1.abc123.us-east-1.rds.amazonaws.com"
PASSWORD_ESC = "p%40ss%2Fw%3Drd%25"
SECRET_TEXT = (
    "APP_ENV=production\n"
    f"DATABASE_URL=postgresql+psycopg://nexoeventos_app:{PASSWORD_ESC}@{HOST}/nexoeventos?sslmode=require&application_name=nexo\n"
    "TICKET_ENCRYPTION_KEY=clave-ficticia-1\nSECURITY_HASH_KEY=clave-ficticia-2\nFRONTEND_ORIGINS=https://demo.example.org\nDB_POOL_SIZE=99\n"
)


def _cert(name: str) -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=365)).sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM)


def _pin(pem: bytes) -> str:
    body = re.search(rb"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----", pem, re.S).group(1)
    return hashlib.sha256(base64.b64decode(b"".join(body.split()))).hexdigest()


def _render(pins: str) -> str:
    text = TEMPLATE.read_text()
    for key, value in {"region": "us-east-1", "secret_name": "nexoeventos/academy/backend-env", "rds_ca_url": "https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem",
                       "rds_ca_sha256": pins, "db_pool_size": "5", "db_max_overflow": "5"}.items():
        text = text.replace("${" + key + "}", value)
    return text.replace("$${", "${")  # escape de Terraform


def _run(tmp_path: Path, bundle: bytes, pins: str, secret: str = SECRET_TEXT, curl_fails: bool = False):
    bin_dir, etc = tmp_path / "bin", tmp_path / "etc"
    bin_dir.mkdir()
    (tmp_path / "secret.txt").write_text(secret)
    (tmp_path / "bundle.pem").write_bytes(bundle)
    (bin_dir / "aws").write_text('#!/bin/bash\ncat "$FAKE_SECRET"\n')
    (bin_dir / "curl").write_text('#!/bin/bash\n[ "$FAKE_CURL_FAIL" = 1 ] && exit 22\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done\ncp "$FAKE_BUNDLE" "$out"\n')
    (bin_dir / "systemctl").write_text('#!/bin/bash\necho "$@" >>"$FAKE_LOG"\n')
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    script = tmp_path / "bootstrap.sh"
    script.write_text(_render(pins))
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "NEXO_ENV_DIR": str(etc), "NEXO_APP_DIR": str(ROOT / "backend"),
           "NEXO_APP_PY": str(ROOT / "backend/.venv/bin/python"), "FAKE_SECRET": str(tmp_path / "secret.txt"), "FAKE_BUNDLE": str(tmp_path / "bundle.pem"),
           "FAKE_LOG": str(tmp_path / "systemctl.log"), "FAKE_CURL_FAIL": "1" if curl_fails else "0", "TMPDIR": str(tmp_path)}
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=120)
    return result, etc


def _no_leaks(result) -> None:
    out = result.stdout + result.stderr
    for secret in (PASSWORD_ESC, "p@ss", "clave-ficticia", "postgresql+psycopg://", "DATABASE_URL="):
        assert secret not in out


def test_bootstrap_installs_only_pinned_ca_and_rewrites_database_url_for_verify_full(tmp_path: Path) -> None:
    ca, extra1, extra2 = _cert("RDS Root CA ficticia"), _cert("Otra CA"), _cert("CA intrusa")
    result, etc = _run(tmp_path, extra1 + ca + extra2, _pin(ca))
    assert result.returncode == 0, result.stderr
    _no_leaks(result)
    bundle = (etc / "rds-ca-bundle.pem").read_bytes()
    assert bundle.count(b"BEGIN CERTIFICATE") == 1 and _pin(bundle) == _pin(ca)  # los certificados no fijados se descartan
    env_text = (etc / "backend.env").read_text()
    assert oct((etc / "backend.env").stat().st_mode & 0o777) == "0o600"
    assert env_text.count("DB_POOL_SIZE=") == 1 and "DB_POOL_SIZE=5" in env_text and "DB_MAX_OVERFLOW=5" in env_text and "DB_POOL_SIZE=99" not in env_text
    url = next(l.split("=", 1)[1] for l in env_text.splitlines() if l.startswith("DATABASE_URL="))
    assert f"nexoeventos_app:{PASSWORD_ESC}@{HOST}/nexoeventos?" in url  # usuario, contraseña codificada, host y base intactos
    parsed = make_url(url)
    assert parsed.password == "p@ss/w=rd%" and parsed.host == HOST and parsed.database == "nexoeventos"
    assert parsed.query["sslmode"] == "verify-full" and parsed.query["sslrootcert"] == str(etc / "rds-ca-bundle.pem") and parsed.query["application_name"] == "nexo"
    for line in ("APP_ENV=production", "TICKET_ENCRYPTION_KEY=clave-ficticia-1", "SECURITY_HASH_KEY=clave-ficticia-2", "FRONTEND_ORIGINS=https://demo.example.org"):
        assert line in env_text  # el resto del secreto se conserva
    assert "enable --now nexoeventos-api.service nginx.service" in (tmp_path / "systemctl.log").read_text()
    assert not list(tmp_path.glob("tmp.*"))  # sin temporales


@pytest.mark.parametrize("case", ["download_fails", "pin_not_in_bundle", "bundle_garbage", "host_not_rds", "no_database_url"])
def test_bootstrap_fails_safely_without_starting_the_api(tmp_path: Path, case: str) -> None:
    ca = _cert("RDS Root CA ficticia")
    bundle, pins, secret, curl_fails = ca, _pin(ca), SECRET_TEXT, False
    if case == "download_fails":
        curl_fails = True
    elif case == "pin_not_in_bundle":
        bundle = _cert("CA distinta")  # el servidor de descarga entrega otra CA
    elif case == "bundle_garbage":
        bundle = b"esto no es un certificado\n"
    elif case == "host_not_rds":
        secret = SECRET_TEXT.replace(HOST, "10.0.0.5")  # verify-full no validaría una IP
    elif case == "no_database_url":
        secret = "\n".join(l for l in SECRET_TEXT.splitlines() if not l.startswith("DATABASE_URL")) + "\n"
    result, etc = _run(tmp_path, bundle, pins, secret, curl_fails)
    assert result.returncode != 0
    _no_leaks(result)
    assert not (etc / "backend.env").exists()  # no queda una configuración a medias
    assert "enable" not in ((tmp_path / "systemctl.log").read_text() if (tmp_path / "systemctl.log").exists() else "")
    assert not list(tmp_path.glob("tmp.*"))


def test_bootstrap_template_has_no_secret_values_and_pins_come_from_terraform_variable() -> None:
    template = TEMPLATE.read_text()
    code = "\n".join(line for line in template.splitlines() if not line.lstrip().startswith("#"))
    assert "set -x" not in code and "xtrace" not in code and 'echo "$tmp' not in code and 'cat "$tmp' not in code
    assert "sslmode=verify-full" in template or '"verify-full"' in template
    compute = (ROOT / "infra/aws-v2/compute.tf").read_text()
    variables = (ROOT / "infra/aws-v2/variables.tf").read_text()
    assert "rds_ca_sha256" in compute and 'variable "rds_ca_sha256"' in variables
    assert re.search(r'default\s*=\s*\["[0-9a-f]{64}"\]', variables.split('variable "rds_ca_sha256"')[1].split("\n}\n")[0])
