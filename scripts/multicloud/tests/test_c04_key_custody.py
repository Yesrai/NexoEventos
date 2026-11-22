"""Custodia de la clave de recuperación con material FICTICIO (claves/certificados desechables, sin red, sin la clave real): comprobación, copia, protección con frase nueva y
prueba real de descifrado con la copia protegida."""
import hashlib
import json
import os
import pty
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/multicloud/c04-key-custody.sh"
STEM = "nexoeventos-rds-20261119T055432Z"
PHRASE = "frase-ficticia-de-prueba-9x"


def sh(*args, env=None, cwd=None):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env={**os.environ, **(env or {})}, cwd=cwd)


def drive(args, answers, env=None):
    """Ejecuta el script en un pseudoterminal y teclea las respuestas cuando aparece cada prompt (como lo haría la usuaria)."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("bash", ["bash", str(SCRIPT), *args], {**os.environ, "LANG": "en_US.UTF-8", **(env or {})})
    out, i = b"", 0
    prompts = (b"frase de paso", b"Rep", b"Frase de paso")
    seen = 0
    while True:
        try:
            d = os.read(fd, 4096)
        except OSError:
            break
        if not d:
            break
        out += d
        n = sum(out.count(p) for p in prompts)
        while seen < n and i < len(answers):
            os.write(fd, answers[i].encode() + b"\n"); i += 1; seen += 1
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace")


@pytest.fixture
def mat(tmp_path):
    d = tmp_path / "src"; d.mkdir(mode=0o700)
    key, crt = d / "k.pem", d / "c.crt"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt), "-subj", "/CN=ficticio", "-days", "2"], check=True, capture_output=True)
    os.chmod(key, 0o600)
    return tmp_path, key, crt


def test_check_ok_and_detects_bad_permissions_and_wrong_certificate(mat):
    tmp, key, crt = mat
    r = sh("check", "--src", str(key), "--cert", str(crt))
    assert r.returncode == 0 and "corresponde al certificado" in r.stdout and "BEGIN" not in r.stdout + r.stderr
    other = tmp / "otro.crt"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(tmp / "o.key"), "-out", str(other), "-subj", "/CN=otro", "-days", "2"], check=True, capture_output=True)
    assert sh("check", "--src", str(key), "--cert", str(other)).returncode == 1  # certificado inesperado
    os.chmod(key, 0o644)
    assert sh("check", "--src", str(key), "--cert", str(crt)).returncode == 1  # permisos inseguros


def test_copy_is_identical_private_and_never_overwrites(mat):
    tmp, key, crt = mat
    dest = tmp / "custodia"
    r = sh("copy", "--src", str(key), "--dest-dir", str(dest))
    assert r.returncode == 0 and "BEGIN" not in r.stdout + r.stderr
    t = dest / "recovery-private.pem"
    assert t.read_bytes() == key.read_bytes() and (t.stat().st_mode & 0o777) == 0o600 and (dest.stat().st_mode & 0o777) == 0o700
    assert sh("copy", "--src", str(key), "--dest-dir", str(dest)).returncode == 1  # no sobrescribe
    assert sh("copy", "--src", str(key), "--dest-dir", str(ROOT / "work" / "x-custodia")).returncode == 1  # dentro del repositorio: rechazado
    assert not (ROOT / "work" / "x-custodia").exists()


def test_protect_requires_matching_long_phrase_and_creates_an_encrypted_copy(mat):
    tmp, key, crt = mat
    dest = tmp / "custodia"
    rc, out = drive(["protect", "--src", str(key), "--dest-dir", str(dest)], ["corta", "corta", "corta", "corta", "corta", "corta"])
    assert rc == 1 and not (dest / "recovery-private.protected.pem").exists()
    rc, out = drive(["protect", "--src", str(key), "--dest-dir", str(dest)], [PHRASE, PHRASE])
    assert rc == 0 and PHRASE not in out
    p = dest / "recovery-private.protected.pem"
    assert "BEGIN ENCRYPTED PRIVATE KEY" in p.read_text() and (p.stat().st_mode & 0o777) == 0o600
    # la copia protegida abre con la frase y es la misma clave
    good = subprocess.run(["openssl", "pkey", "-in", str(p), "-pubout", "-passin", "stdin"], input=PHRASE + "\n", capture_output=True, text=True)
    plain = subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout"], capture_output=True, text=True)
    assert good.returncode == 0 and good.stdout == plain.stdout
    rc, _ = drive(["protect", "--src", str(key), "--dest-dir", str(dest)], [PHRASE, PHRASE])
    assert rc == 1  # no sobrescribe


def test_verify_decrypts_a_real_style_backup_with_the_protected_copy_and_rejects_a_wrong_phrase(mat):
    tmp, key, crt = mat
    dest = tmp / "custodia"
    assert drive(["protect", "--src", str(key), "--dest-dir", str(dest)], [PHRASE, PHRASE])[0] == 0
    prot = dest / "recovery-private.protected.pem"
    inp = tmp / "in"; inp.mkdir()
    dump = b"PGDMP" + os.urandom(2000)
    cms = subprocess.run(["openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-outform", "DER", str(crt)], input=dump, capture_output=True, check=True).stdout
    (inp / f"{STEM}.cms").write_bytes(cms)
    man = {"name": STEM, "env": "aws-academy", "oci_cms_bytes": len(cms), "oci_cms_sha256": hashlib.sha256(cms).hexdigest(), "plaintext_dump_bytes": len(dump), "plaintext_dump_sha256": hashlib.sha256(dump).hexdigest()}
    (inp / f"{STEM}.manifest.json").write_text(json.dumps(man))
    sk, spub = tmp / "s.key", tmp / "s.pub"
    subprocess.run(["openssl", "ecparam", "-genkey", "-name", "prime256v1", "-noout", "-out", str(sk)], check=True, capture_output=True)
    subprocess.run(["openssl", "ec", "-in", str(sk), "-pubout", "-out", str(spub)], check=True, capture_output=True)
    subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(sk), "-out", str(inp / f"{STEM}.manifest.json.sig"), str(inp / f"{STEM}.manifest.json")], check=True)
    env = {"NEXO_SIGNER_PUB": str(spub)}
    rc, out = drive(["verify", "--key", str(prot), "--from-dir", str(inp)], [PHRASE], env)
    assert rc == 0 and "prueba de descifrado completada" in out and PHRASE not in out
    rc, out = drive(["verify", "--key", str(prot), "--from-dir", str(inp)], ["frase-equivocada-123"], env)
    assert rc == 1 and "No se pudo abrir la clave privada" in out and "prueba de descifrado completada" not in out
    assert not [p for p in Path("/tmp").glob("nexo-restore.*")]  # sin restos temporales
