"""Orquestador `oci-drill/run-from-mac.sh` en modo C-04, SIN nubes: `oci`, `ssh` y `scp` son simuladores y la «VM» es un PostgreSQL 18 desechable local (socket Unix en un directorio 0700).
Material 100 % ficticio (claves/certificados desechables). Cubre el camino feliz con tiempos reales por etapa y los fallos que deben abortar de forma segura."""
import hashlib
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts/multicloud/oci-drill/run-from-mac.sh"
FPSQL = ROOT / "scripts/multicloud/fingerprint.sql"
PGBIN = next((Path(p) for p in ("/opt/homebrew/opt/postgresql@18/bin", "/usr/local/opt/postgresql@18/bin") if (Path(p) / "postgres").exists()), None)
pytestmark = pytest.mark.skipif(PGBIN is None or shutil.which("openssl") is None, reason="requiere PostgreSQL 18 local (Homebrew) para la «VM» desechable")
STEM = "nexoeventos-rds-20261119T055432Z"
OBJ = "backups/c04-20261119/"


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def fingerprint(env, port, db):
    r = run([str(PGBIN / "psql"), "-d", db, "-At", "-f", str(FPSQL)], env=env)
    assert r.returncode == 0, r.stderr
    return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    t = Path(tmp_path_factory.mktemp("rfm", numbered=True)); os.chmod(t, 0o700)
    sock = Path("/tmp") / f"rfm{os.getpid()}"; sock.mkdir(mode=0o700, exist_ok=True)
    port = socket.socket(); port.bind(("127.0.0.1", 0)); p = port.getsockname()[1]; port.close()
    env = {**os.environ, "PGHOST": str(sock), "PGPORT": str(p), "PGUSER": "postgres", "LC_ALL": "en_US.UTF-8"}
    run([str(PGBIN / "initdb"), "-D", str(t / "pg"), "-U", "postgres", "-E", "UTF8", "--locale=C", "-A", "trust"], env=env, check=True)
    assert run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-o", f"-c listen_addresses= -c unix_socket_directories={sock} -c port={p} -c fsync=off", "-l", str(t / "pg.log"), "-w", "start"], env=env).returncode == 0
    run([str(PGBIN / "psql"), "-qd", "postgres", "-c", "create database app"], env=env, check=True)
    run([str(PGBIN / "psql"), "-q", "-d", "app", "-v", "ON_ERROR_STOP=1", "-c", """
        create table alembic_version(version_num text); insert into alembic_version values('0008');
        create table users(id int); insert into users select generate_series(1,26);
        create table events(id int, capacity int, reserved_count int); insert into events select g,100,g%4 from generate_series(1,35) g;
        create table reservations(id uuid default gen_random_uuid()); insert into reservations select from generate_series(1,136);
        create table tickets(id int); insert into tickets select generate_series(1,136);
        create table operator_event_assignments(id int); insert into operator_event_assignments select generate_series(1,2);
        create table access_logs(id int); insert into access_logs select generate_series(1,9);"""], env=env, check=True)
    fp = fingerprint(env, p, "app")
    dump = run([str(PGBIN / "pg_dump"), "-Fc", "--no-owner", "--no-acl", "-d", "app"], env=env, check=True) if False else subprocess.run([str(PGBIN / "pg_dump"), "-Fc", "--no-owner", "--no-acl", "-d", "app"], capture_output=True, env=env, check=True).stdout
    def cert(name):
        k, c = t / f"{name}.key", t / f"{name}.crt"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(k), "-out", str(c), "-subj", f"/CN={name}", "-days", "2"], check=True, capture_output=True)
        os.chmod(k, 0o600)
        return k, c, hashlib.sha256(subprocess.run(["openssl", "x509", "-in", str(c), "-outform", "DER"], capture_output=True, check=True).stdout).hexdigest()
    ka, ca, fa = cert("a"); kb, cb, fb = cert("b")
    cms = subprocess.run(["openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-outform", "DER", str(ca)], input=dump, capture_output=True, check=True).stdout
    sk, spub = t / "s.key", t / "s.pub"
    subprocess.run(["openssl", "ecparam", "-genkey", "-name", "prime256v1", "-noout", "-out", str(sk)], check=True, capture_output=True)
    subprocess.run(["openssl", "ec", "-in", str(sk), "-pubout", "-out", str(spub)], check=True, capture_output=True)
    man = {"name": STEM, "env": "aws-academy", "oci_cms_bytes": len(cms), "oci_cms_sha256": hashlib.sha256(cms).hexdigest(), "plaintext_dump_bytes": len(dump),
           "plaintext_dump_sha256": hashlib.sha256(dump).hexdigest(), "fingerprint_before": fp, "fingerprint_after": fp, "recipient_cert_sha256": fa}
    bucket = t / "bucket"; bucket.mkdir()
    def publish(m=man, c=cms, sign=True):
        (bucket / f"{STEM}.cms").write_bytes(c); (bucket / f"{STEM}.manifest.json").write_text(json.dumps(m))
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(sk), "-out", str(bucket / f"{STEM}.manifest.json.sig"), str(bucket / f"{STEM}.manifest.json")], check=True)
    publish()
    shim = t / "shim"; shim.mkdir()
    (shim / "oci").write_text('#!/usr/bin/env bash\nname="";file=""; a=("$@")\nfor i in "${!a[@]}"; do [[ "${a[$i]}" == "--name" ]] && name="${a[$((i+1))]}"; [[ "${a[$i]}" == "--file" ]] && file="${a[$((i+1))]}"; done\n'
                              '[[ -e "$SHIM_NO_OCI" ]] && { echo "oci: servicio no disponible" >&2; exit 1; }\necho "$name" >> "$SHIM_LOG"; cp "$SHIM_BUCKET/$(basename "$name")" "$file"\n')
    (shim / "scp").write_text('#!/usr/bin/env bash\nexit 0\n')
    (shim / "ssh").write_text(f'''#!/usr/bin/env bash
cmd="${{@: -1}}"
case "$cmd" in
  *"--check"*) echo "LISTO: PostgreSQL simulado (desechable)" ;;
  *"exec bash /var/lib/pgsql/drill-tools/remote-restore.sh "[0-9a-f]*)
    plain="$(sed -E 's/.*remote-restore.sh ([0-9a-f]{{64}}).*/\\1/' <<<"$cmd")"; f="$SHIM_TMP/dump.$$"; cat >"$f"
    [[ "$(shasum -a 256 "$f" | cut -d' ' -f1)" == "$plain" ]] || {{ echo "FALLÓ: SHA-256 del volcado distinto del manifiesto (bytes recibidos: $(wc -c <"$f" | tr -d ' '); esperado $plain)" >&2; rm -f "$f"; exit 3; }}
    [[ -e "$SHIM_FAIL_RESTORE" ]] && {{ rm -f "$f"; echo "FALLÓ: pg_restore simulado" >&2; exit 5; }}
    {PGBIN}/psql -qd postgres -c "DROP DATABASE IF EXISTS drill" -c "CREATE DATABASE drill" >/dev/null
    {PGBIN}/pg_restore -d drill --no-owner --no-acl --exit-on-error <"$f" || {{ rm -f "$f"; exit 5; }}
    {PGBIN}/psql -d drill -At -f {FPSQL} | sort; rm -f "$f" ;;
  *install-postgres*) echo "PostgreSQL 18 (simulado)" ;;
esac
''')
    for f in shim.iterdir(): os.chmod(f, 0o755)
    rpms = t / "rpms"; rpms.mkdir(); (rpms / "postgresql18-prueba.rpm").write_text("x")
    sums = t / "rpm.sha256"; sums.write_text(hashlib.sha256(b"x").hexdigest() + "  postgresql18-prueba.rpm\n")
    (t / "sshkey").write_text("x"); os.chmod(t / "sshkey", 0o600)
    yield dict(t=t, env=env, a=(ka, ca, fa), b=(kb, cb, fb), spub=spub, shim=shim, bucket=bucket, rpms=rpms, sums=sums, publish=publish, man=man, cms=cms, fp=fp)
    run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=env)
    shutil.rmtree(sock, ignore_errors=True)


def orchestrate(w, *extra, key=None, cert=None, sha=None, status=None, no_oci=False, fail_restore=False, bundle=STEM, tag="x"):
    out = w["t"] / f"out-{tag}"; log = w["t"] / f"log-{tag}"; log.write_text("")
    for f in ("no-oci", "fail-restore"):
        (w["t"] / f).unlink(missing_ok=True)
    if no_oci: (w["t"] / "no-oci").write_text("1")
    if fail_restore: (w["t"] / "fail-restore").write_text("1")
    env = {**w["env"], "PATH": f"{w['shim']}:{os.environ['PATH']}", "SHIM_LOG": str(log), "SHIM_BUCKET": str(w["bucket"]), "SHIM_TMP": str(w["t"]), "SHIM_NO_OCI": str(w["t"] / "no-oci"),
           "SHIM_FAIL_RESTORE": str(w["t"] / "fail-restore"), "RPM_CHECKSUMS": str(w["sums"]), "OCI_NS": "nsprueba", "LPORT": "2222", "SSH_KEY": str(w["t"] / "sshkey"), "RPMS": str(w["rpms"]),
           "OUT_BASE": str(out), "RECOVERY_ORIGIN": "simulado"}
    k, c, f = w["a"]
    args = ["bash", str(RUNNER), "--kind", "c04", "--bundle", bundle, "--key", str(key or k), "--cert", str(cert or c), "--cert-sha256", sha or f, "--signer-pub", str(w["spub"])]
    if status: args += ["--status-dir", str(status)]
    r = subprocess.run([*args, *extra], capture_output=True, text=True, env=env)
    return r, out, log


def test_camino_feliz_c04_con_tiempos_por_etapa_y_registro_para_el_panel(world):
    status = world["t"] / "panel"
    r, out, log = orchestrate(world, status=status, tag="ok")
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    assert "huella idéntica" in r.stdout and "firma, SHA-256 e identidad del certificado verificados" in r.stdout
    assert set(open(log).read().split()) == {OBJ + STEM + ".cms", OBJ + STEM + ".manifest.json", OBJ + STEM + ".manifest.json.sig"}      # solo el respaldo elegido, bajo el prefijo C-04
    run_dir = next(out.glob("run-*"))
    et = json.loads((run_dir / "etapas.json").read_text())
    assert et["resultado"] == "OK" and list(et["etapas"]) == ["descarga", "verificacion", "instalacion", "descifrado_restauracion", "comprobacion"] and et["total_s"] > 0
    panel = json.loads((status / "recovery-run.json").read_text())
    assert panel["resultado"] == "OK" and panel["origen"] == "simulado" and panel["respaldo"] == STEM and set(panel["etapas"]) == set(et["etapas"])
    assert (status / "recovery-run.json").stat().st_mode & 0o777 == 0o600
    assert "PRIVATE" not in r.stdout + r.stderr


def test_certificado_con_huella_distinta_se_rechaza_antes_de_usar_red(world):
    r, out, log = orchestrate(world, sha="0" * 64, tag="sha")
    assert r.returncode == 10 and "huella SHA-256 esperada" in r.stderr and open(log).read() == ""


def test_clave_equivocada_para_el_certificado_se_rechaza_antes_de_usar_red(world):
    r, out, log = orchestrate(world, key=world["b"][0], tag="key")
    assert r.returncode == 10 and "NO corresponde al certificado" in r.stderr and open(log).read() == ""


def test_respaldo_cifrado_para_otro_certificado_fijado_se_rechaza_antes_de_descifrar(world):
    kb, cb, fb = world["b"]
    r, out, log = orchestrate(world, key=kb, cert=cb, sha=fb, tag="dest")
    assert r.returncode == 10 and "destinatario distinto" in r.stderr
    assert "restaurad" not in r.stdout


def test_firma_invalida_o_manifiesto_alterado_no_restaura(world):
    sig = world["bucket"] / f"{STEM}.manifest.json.sig"; good = sig.read_bytes()
    try:
        sig.write_bytes(good[:-3] + b"xyz")
        r, *_ = orchestrate(world, tag="sig")
        assert r.returncode == 9 and "firma del manifiesto NO es válida" in r.stderr
    finally:
        sig.write_bytes(good)


def test_respaldo_corrupto_o_incompleto_se_rechaza_por_sha256(world):
    cms = world["bucket"] / f"{STEM}.cms"; good = cms.read_bytes()
    try:
        for bad in (good[:-1] + bytes([good[-1] ^ 1]), good[: len(good) // 2]):
            cms.write_bytes(bad)
            r, *_ = orchestrate(world, tag="corrupto")
            assert r.returncode != 0 and "huella idéntica" not in r.stdout and "volcado descifrado" not in r.stdout
    finally:
        cms.write_bytes(good)


def test_manifiesto_que_declara_otro_certificado_se_rechaza(world):
    man = dict(world["man"], recipient_cert_sha256="1" * 64)
    world["publish"](m=man)
    try:
        r, *_ = orchestrate(world, tag="manifest-cert")
        assert r.returncode == 10 and "otro certificado" in r.stderr
    finally:
        world["publish"]()


def test_error_durante_la_restauracion_registra_fallo_con_la_etapa(world):
    status = world["t"] / "panel-fail"
    r, out, log = orchestrate(world, status=status, fail_restore=True, tag="fail")
    assert r.returncode == 8 and "FALLÓ la restauración remota" in r.stderr
    panel = json.loads((status / "recovery-run.json").read_text())
    assert panel["resultado"] == "FALLO" and panel["etapa_fallida"] == "descifrado_restauracion" and "comprobacion" not in panel["etapas"]


def test_oci_no_disponible_aborta_en_la_descarga_y_lo_registra(world):
    status = world["t"] / "panel-oci"
    r, out, log = orchestrate(world, status=status, no_oci=True, tag="oci")
    assert r.returncode != 0
    panel = json.loads((status / "recovery-run.json").read_text())
    assert panel["resultado"] == "FALLO" and panel["etapa_fallida"] == "descarga"
    assert not list((out).glob("run-*/huella-restaurada.txt"))        # no se restauró nada


def test_modo_heredado_sigue_funcionando_con_el_mismo_orquestador(world):
    """Compatibilidad: sin --kind c04 el orquestador trabaja como antes (backups/<ID>.oci.cms, línea base explícita, sin firma)."""
    legacy = "nexoeventos-rds-20260101T000000Z"; b = world["bucket"]
    shutil.copy(b / f"{STEM}.cms", b / f"{legacy}.oci.cms")
    man = dict(world["man"], name=legacy); (b / f"{legacy}.manifest.json").write_text(json.dumps(man))
    base = world["t"] / "linea-base.json"; base.write_text(json.dumps({"baselines": {"k": {"fingerprint": world["fp"]}}}))
    out = world["t"] / "out-legacy"; log = world["t"] / "log-legacy"; log.write_text("")
    env = {**world["env"], "PATH": f"{world['shim']}:{os.environ['PATH']}", "SHIM_LOG": str(log), "SHIM_BUCKET": str(b), "SHIM_TMP": str(world["t"]), "SHIM_NO_OCI": str(world["t"] / "no-oci"),
           "SHIM_FAIL_RESTORE": str(world["t"] / "fail-restore"), "RPM_CHECKSUMS": str(world["sums"]), "OCI_NS": "n", "LPORT": "2222", "SSH_KEY": str(world["t"] / "sshkey"),
           "RPMS": str(world["rpms"]), "OUT_BASE": str(out), "BUNDLE": legacy, "BASELINE_KEY": "k", "BASELINE_FILE": str(base), "RECOVERY_KEY": str(world["a"][0])}
    for f in ("no-oci", "fail-restore"):
        (world["t"] / f).unlink(missing_ok=True)
    r = subprocess.run(["bash", str(RUNNER)], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "huella idéntica" in r.stdout, r.stdout[-500:] + r.stderr[-500:]
    assert set(open(log).read().split()) == {f"backups/{legacy}.oci.cms", f"backups/{legacy}.manifest.json"}
