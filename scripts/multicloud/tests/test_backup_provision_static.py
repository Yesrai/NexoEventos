"""Comprobaciones estáticas del script que se ejecutará en la EC2 (no se ejecuta aquí): no debe imprimir secretos, usar `set -x` ni dejar contraseñas en la línea de órdenes."""
import re
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[3] / "deploy/backup/provision-backup-role.sh").read_text()
SQL = (Path(__file__).resolve().parents[3] / "deploy/backup/backup-role.sql").read_text()


def test_script_never_prints_or_traces_secrets() -> None:
    assert "set -x" not in SCRIPT and "xtrace" not in SCRIPT
    secrets = ("PGPASSWORD", "BACKUP_PW", "NEXO_BACKUP_PASSWORD", "master.json", "DATABASE_URL")
    for line in SCRIPT.splitlines():
        for segment in re.split(r";|&&|\|\|", line):
            if re.match(r"\s*(echo|printf)\b", segment) and not re.search(r">\s*[\"$/]", segment):  # echo/printf a la salida estándar (no redirigido a un archivo)
                for var in secrets:
                    assert not re.search(r"\$\{?%s\b" % var, segment), f"imprime {var}: {segment.strip()[:80]}"
    assert not re.search(r"\bcat\b[^\n]*(master\.json|backup\.env|ENVF)", SCRIPT)


def test_script_uses_verify_full_least_privilege_and_does_not_overwrite() -> None:
    assert "sslmode=verify-full" in SCRIPT and "install -m 0600" in SCRIPT and "chmod 0600" in SCRIPT
    assert "ya existe (no se sobrescribe)" in SCRIPT and "shred -u" in SCRIPT
    assert "--password" not in SCRIPT and "-W " not in SCRIPT  # sin contraseñas en argumentos


def test_sql_grants_only_read_all_data_and_never_superuser_or_write() -> None:
    body = re.sub(r"--[^\n]*", "", SQL)
    assert "pg_read_all_data" in body and "NOSUPERUSER" in body and "NOCREATEROLE" in body and "NOCREATEDB" in body
    assert not re.search(r"GRANT\s+(ALL|INSERT|UPDATE|DELETE|TRUNCATE|CREATE)\b", body, re.I)
    assert "default_transaction_read_only = on" in body and "CONNECTION LIMIT 2" in body


def test_script_modes_are_read_only_except_apply_and_never_recreate_the_role() -> None:
    assert all(f"{m})" in SCRIPT for m in ("check", "apply", "verify"))
    assert "el rol nexoeventos_backup ya existe (no se recrea ni se cambia su contraseña)" in SCRIPT
    assert "instantánea del catálogo antes/después" in SCRIPT
    verify_block = SCRIPT.split("verify)")[1]
    assert not re.search(r"\b(DROP|GRANT|ALTER ROLE|CREATE ROLE)\b", verify_block.replace("deny", "").split("create role c04_intruso")[0], re.I)


def test_env_file_with_ampersands_is_read_without_sourcing(tmp_path) -> None:
    """Regresión real (19-nov): `. backup.env` cortaba la URL en el «&». Los scripts leen la línea con sed y no hacen `source`."""
    import subprocess

    runner = (Path(__file__).resolve().parents[3] / "deploy/backup/c04-run-cycle.sh").read_text()
    assert ". \"$ENVF\"" not in SCRIPT and ". \"$ENVF\"" not in runner
    env = tmp_path / "backup.env"
    env.write_text("DATABASE_URL=postgresql://u:p@h:5432/db?sslmode=verify-full&sslrootcert=/x/ca.pem\n")
    out = subprocess.run(["bash", "-c", "ENVF=%s; DATABASE_URL=\"$(sed -n 's/^DATABASE_URL=//p' \"$ENVF\")\"; printf %%s \"$DATABASE_URL\"" % env], capture_output=True, text=True).stdout
    assert out.endswith("&sslrootcert=/x/ca.pem") and "sslmode=verify-full" in out


def test_par_probe_never_prints_the_url_and_uses_if_none_match() -> None:
    probe = (Path(__file__).resolve().parents[3] / "deploy/backup/c04-par-probe.py").read_text()
    assert 'add_header("If-None-Match", "*")' in probe and "412" in probe
    for line in probe.splitlines():
        if line.strip().startswith(("print(", "return print(")):
            assert not re.search(r"\b(url|base)\b", line.replace("name", "")), line


def _profile(tmp_path, fingerprint="auto", extra=None):
    """Perfil de respaldo ficticio con un certificado desechable y su huella (o la que se indique)."""
    import hashlib
    import json
    import subprocess

    crt = tmp_path / "dest.crt"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(tmp_path / "dest.key"), "-out", str(crt), "-subj", "/CN=ficticio", "-days", "2"], check=True, capture_output=True)
    der = subprocess.run(["openssl", "x509", "-in", str(crt), "-outform", "DER"], capture_output=True, check=True).stdout
    cfg = tmp_path / "perfil.json"
    cfg.write_text(json.dumps({"cert": str(crt), "cert_sha256": hashlib.sha256(der).hexdigest() if fingerprint == "auto" else fingerprint, **(extra or {})}))
    return cfg


def test_par_check_script_validates_without_printing_the_file(tmp_path) -> None:
    """c04-par-check.sh nunca imprime el contenido del archivo (ni parcial) y detecta prefijos/buckets/permisos incorrectos."""
    import os
    import subprocess

    script = Path(__file__).resolve().parents[3] / "deploy/backup/c04-par-check.sh"
    good = "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/TOKEN-INVENTADO-SOLO-PRUEBAS/n/espacio/b/nexoeventos-recovery/o/backups/c04-20261119/"
    f = tmp_path / "par.url"
    f.write_text(good)
    os.chmod(f, 0o600)
    # `stat -c` de GNU no existe en macOS: se sustituye por una envoltura en el PATH solo para esta prueba
    bindir = tmp_path / "bin"; bindir.mkdir()
    (bindir / "stat").write_text('#!/bin/sh\nprintf "600 root:root"\n'); os.chmod(bindir / "stat", 0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "NEXO_C04_CONFIG": str(_profile(tmp_path))}
    ok = subprocess.run(["bash", str(script), str(f)], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "TOKEN-INVENTADO" not in ok.stdout + ok.stderr and "objectstorage" not in ok.stdout.replace("región", "")
    f.write_text(good.replace("c04-20261119/", "backups/otro/").replace("o/backups/backups", "o/backups"))
    bad = subprocess.run(["bash", str(script), str(f)], capture_output=True, text=True, env=env)
    assert bad.returncode == 1 and "FALLÓ" in bad.stdout and "TOKEN-INVENTADO" not in bad.stdout + bad.stderr
    f.write_text(good.replace("nexoeventos-recovery", "otro-bucket"))
    assert subprocess.run(["bash", str(script), str(f)], capture_output=True, text=True, env=env).returncode == 1


def test_par_check_accepts_url_ending_at_o_only_if_config_prefix_is_inside_authorized_prefix(tmp_path) -> None:
    """Causa del 19-nov: el access-uri real termina en `/o/`. Se acepta SOLO si el «object_prefix» de backup.json hace que los nombres caigan dentro de backups/c04-20261119/."""
    import json
    import os
    import subprocess

    script = Path(__file__).resolve().parents[3] / "deploy/backup/c04-par-check.sh"
    url = "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/TOKEN-INVENTADO-SOLO-PRUEBAS/n/espacio/b/nexoeventos-recovery/o/"
    f = tmp_path / "par.url"; f.write_text(url); os.chmod(f, 0o600)
    bindir = tmp_path / "bin"; bindir.mkdir()
    (bindir / "stat").write_text('#!/bin/sh\nprintf "600 root:root"\n'); os.chmod(bindir / "stat", 0o755)
    cfg = _profile(tmp_path)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "NEXO_C04_CONFIG": str(cfg)}

    def run(prefix):
        cfg.write_text(json.dumps({**json.loads(cfg.read_text()), "object_prefix": prefix}))
        return subprocess.run(["bash", str(script), str(f)], capture_output=True, text=True, env=env)

    good = run("backups/c04-20261119/")
    assert good.returncode == 0 and "termina en /o/" in good.stdout and "TOKEN-INVENTADO" not in good.stdout + good.stderr
    for malo in ("", "backups/otro/", "backups/c04-20261119/x/", "backups/c04-20261119"):
        r = run(malo)
        assert r.returncode == 1 and "FUERA del alcance" in r.stdout, malo


def test_par_check_rejects_certificate_with_unexpected_fingerprint(tmp_path) -> None:
    """Identidad explícita del certificado: la huella fijada en el perfil debe coincidir con el certificado; si falta o difiere, el control falla."""
    import os
    import subprocess

    script = Path(__file__).resolve().parents[3] / "deploy/backup/c04-par-check.sh"
    f = tmp_path / "par.url"
    f.write_text("https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/TOKEN-INVENTADO-SOLO-PRUEBAS/n/espacio/b/nexoeventos-recovery/o/backups/c04-20261119/")
    os.chmod(f, 0o600)
    bindir = tmp_path / "bin"; bindir.mkdir()
    (bindir / "stat").write_text('#!/bin/sh\nprintf "600 root:root"\n'); os.chmod(bindir / "stat", 0o755)
    for fp, expected_ok in (("auto", True), ("0" * 64, False), ("", False)):
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "NEXO_C04_CONFIG": str(_profile(tmp_path, fingerprint=fp))}
        r = subprocess.run(["bash", str(script), str(f)], capture_output=True, text=True, env=env)
        assert (r.returncode == 0) == expected_ok, (fp, r.stdout)
        if not expected_ok:
            assert "huella" in r.stdout and "TOKEN-INVENTADO" not in r.stdout + r.stderr
