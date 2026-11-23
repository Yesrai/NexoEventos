"""Recuperación de la APLICACIÓN en modo C-04, SIN nubes: `oci`, `ssh` y `scp` son simuladores; la «VM» es un PostgreSQL 18 local desechable (socket Unix, directorio 0700) y, para la prueba final,
el BACKEND REAL (uvicorn) arranca sobre la base restaurada con las claves de aplicación entregadas por el flujo. Todo el material (claves, certificados, secretos) es ficticio.
Se ejecutan por reanudación las etapas download→(build…app1 omitidas)→data→secrets (START_AT/STOP_BEFORE), que son las que usan la clave privada y los secretos."""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts/multicloud/oci-drill/app-recovery.sh"
EXPORT = ROOT / "scripts/multicloud/oci-drill/app-secrets-export.sh"
INSTALL_SECRETS = ROOT / "scripts/multicloud/oci-drill/install-app-secrets.sh"
FPSQL = ROOT / "scripts/multicloud/fingerprint.sql"
PGBIN = next((Path(p) for p in ("/opt/homebrew/opt/postgresql@18/bin", "/usr/local/opt/postgresql@18/bin") if (Path(p) / "postgres").exists()), None)
UVICORN = ROOT / "backend/.venv/bin/uvicorn"
pytestmark = pytest.mark.skipif(PGBIN is None or not UVICORN.exists() or shutil.which("openssl") is None, reason="requiere PostgreSQL 18 local y backend/.venv")
STEM = "nexoeventos-rds-20261119T055432Z"
ORIG = {"TICKET_ENCRYPTION_KEY": "ORIGINAL-ticket-key-ficticia-0123456789abcdef=", "SECURITY_HASH_KEY": "ORIGINAL-hash-key-ficticia-0123456789abcdef"}


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    t = Path(tmp_path_factory.mktemp("apprec", numbered=True)); os.chmod(t, 0o700)
    sock = Path("/tmp") / f"apr{os.getpid()}"; sock.mkdir(mode=0o700, exist_ok=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "PGHOST": str(sock), "PGPORT": str(port), "PGUSER": "postgres", "LC_ALL": "en_US.UTF-8"}
    run([str(PGBIN / "initdb"), "-D", str(t / "pg"), "-U", "postgres", "-E", "UTF8", "--locale=C", "-A", "trust"], env=env, check=True)
    assert run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-o", f"-c listen_addresses= -c unix_socket_directories={sock} -c port={port} -c fsync=off", "-l", str(t / "pg.log"), "-w", "start"], env=env).returncode == 0
    psql = lambda *a, **k: run([str(PGBIN / "psql"), "-q", "-v", "ON_ERROR_STOP=1", *a], env=env, **k)
    assert psql("-d", "postgres", input="""CREATE ROLE nexoeventos_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
        CREATE ROLE nexoeventos_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT; CREATE DATABASE app OWNER nexoeventos_owner;
        REVOKE ALL ON DATABASE app FROM PUBLIC; GRANT CONNECT ON DATABASE app TO nexoeventos_app;""").returncode == 0
    url = f"postgresql+psycopg://postgres@/app?host={sock}&port={port}"
    assert run([str(ROOT / "backend/.venv/bin/alembic"), "upgrade", "head"], cwd=ROOT / "backend", env={**os.environ, "MIGRATION_DATABASE_URL": url}).returncode == 0
    assert run([str(ROOT / "backend/.venv/bin/python"), str(ROOT / "scripts/seed-demo-catalog.py"), "--database-url", url]).returncode == 0
    fpr = run([str(PGBIN / "psql"), "-d", "app", "-At", "-f", str(FPSQL)], env=env)
    fp = dict(l.split("=", 1) for l in fpr.stdout.splitlines() if "=" in l)
    dump = subprocess.run([str(PGBIN / "pg_dump"), "-Fc", "--no-owner", "--no-acl", "-d", "app"], capture_output=True, env=env, check=True).stdout

    def cert(name):
        k, c = t / f"{name}.key", t / f"{name}.crt"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(k), "-out", str(c), "-subj", f"/CN={name}", "-days", "2"], check=True, capture_output=True)
        os.chmod(k, 0o600)
        return k, c, hashlib.sha256(subprocess.run(["openssl", "x509", "-in", str(c), "-outform", "DER"], capture_output=True, check=True).stdout).hexdigest()
    ka, ca, fa = cert("a"); kb, cb, fb = cert("b")
    sk, spub = t / "s.key", t / "s.pub"
    subprocess.run(["openssl", "ecparam", "-genkey", "-name", "prime256v1", "-noout", "-out", str(sk)], check=True, capture_output=True)
    subprocess.run(["openssl", "ec", "-in", str(sk), "-pubout", "-out", str(spub)], check=True, capture_output=True)
    bucket = t / "bucket"; bucket.mkdir()

    def sign(f):
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(sk), "-out", f"{f}.sig", str(f)], check=True)

    cms = subprocess.run(["openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-outform", "DER", str(ca)], input=dump, capture_output=True, check=True).stdout
    (bucket / f"{STEM}.cms").write_bytes(cms)
    man = {"name": STEM, "env": "aws-academy", "oci_cms_bytes": len(cms), "oci_cms_sha256": hashlib.sha256(cms).hexdigest(), "plaintext_dump_bytes": len(dump),
           "plaintext_dump_sha256": hashlib.sha256(dump).hexdigest(), "fingerprint_before": fp, "fingerprint_after": fp, "recipient_cert_sha256": fa}
    (bucket / f"{STEM}.manifest.json").write_text(json.dumps(man)); sign(bucket / f"{STEM}.manifest.json")

    def export_secrets(values, cert_path=ca, pin=fa, name_dir="sec"):
        """Usa el exportador REAL (modo c04) con la fuente stdin y secretos ficticios."""
        d = t / name_dir; shutil.rmtree(d, ignore_errors=True); d.mkdir()
        r = subprocess.run(["bash", str(EXPORT), "--kind", "c04", "--source", "stdin", "--cert", str(cert_path), "--cert-sha256", pin, "--sign-key", str(sk), "--out", str(d)],
                           input="".join(f"{k}={v}\n" for k, v in values.items()), capture_output=True, text=True, cwd=t)
        return r, d
    r, d = export_secrets(ORIG)
    assert r.returncode == 0, r.stderr
    secstem = next(d.glob("app-secrets-*.cms")).name[:-4]
    for suf in (".cms", ".manifest.json", ".manifest.json.sig"):
        shutil.copy(d / f"{secstem}{suf}", bucket / f"{secstem}{suf}")
    shim = t / "shim"; shim.mkdir()
    (shim / "oci").write_text('#!/usr/bin/env bash\nname="";file=""; a=("$@")\nfor i in "${!a[@]}"; do [[ "${a[$i]}" == "--name" ]] && name="${a[$((i+1))]}"; [[ "${a[$i]}" == "--file" ]] && file="${a[$((i+1))]}"; done\n'
                              '[[ -e "$SHIM_NO_OCI" ]] && { echo "oci: servicio no disponible" >&2; exit 1; }\necho "$name" >> "$SHIM_LOG"; cp "$SHIM_BUCKET/$(basename "$name")" "$file"\n')
    (shim / "scp").write_text('#!/usr/bin/env bash\necho "scp: $*" >> "$SHIM_LOG"\n')
    (shim / "ssh").write_text(f'''#!/usr/bin/env bash
cmd="${{@: -1}}"; echo "ssh: $*" >> "$SHIM_LOG"
case "$cmd" in
  *"--check"*) echo "LISTO: PostgreSQL simulado (desechable)" ;;
  *"exec bash /var/lib/pgsql/drill-tools/remote-restore.sh "[0-9a-f]*)
    plain="$(sed -E 's/.*remote-restore.sh ([0-9a-f]{{64}}).*/\\1/' <<<"$cmd")"; f="$SHIM_TMP/dump.$$"; cat >"$f"
    [[ "$(shasum -a 256 "$f" | cut -d' ' -f1)" == "$plain" ]] || {{ echo "FALLÓ: SHA-256 del volcado distinto del manifiesto" >&2; rm -f "$f"; exit 3; }}
    {PGBIN}/psql -qd postgres -c "DROP DATABASE IF EXISTS nexoeventos" -c "CREATE DATABASE nexoeventos" >/dev/null
    {PGBIN}/pg_restore -d nexoeventos --no-owner --no-acl --exit-on-error <"$f" || {{ rm -f "$f"; exit 5; }}
    {PGBIN}/psql -d nexoeventos -At -f {FPSQL} | sort; rm -f "$f" ;;
  *install-app-secrets*) NEXO_SECRETS_DIR="$SHIM_SECRETS" bash {INSTALL_SECRETS} ;;
esac
''')
    for f in shim.iterdir(): os.chmod(f, 0o755)
    rpms = t / "rpms"; rpms.mkdir(); (rpms / "postgresql18-prueba.rpm").write_text("x")
    sums = t / "rpm.sha256"; sums.write_text(hashlib.sha256(b"x").hexdigest() + "  postgresql18-prueba.rpm\n")
    (t / "sshkey").write_text("x"); os.chmod(t / "sshkey", 0o600)
    yield dict(t=t, env=env, sock=sock, port=port, a=(ka, ca, fa), b=(kb, cb, fb), spub=spub, shim=shim, bucket=bucket, rpms=rpms, sums=sums, secstem=secstem, export=export_secrets, sign=sign, psql=psql)
    run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=env)
    shutil.rmtree(sock, ignore_errors=True)


def recover(w, *, tag, secstem=None, key=None, cert=None, sha=None, no_oci=False, status=None, resume_from="download", stop_before="build"):
    out = w["t"] / f"out-{tag}"; log = w["t"] / f"log-{tag}"; log.write_text("")
    secrets_dir = w["t"] / f"secrets-{tag}"; shutil.rmtree(secrets_dir, ignore_errors=True)
    (w["t"] / "no-oci").unlink(missing_ok=True)
    if no_oci: (w["t"] / "no-oci").write_text("1")
    env = {**w["env"], "PATH": f"{w['shim']}:{os.environ['PATH']}", "SHIM_LOG": str(log), "SHIM_BUCKET": str(w["bucket"]), "SHIM_TMP": str(w["t"]), "SHIM_NO_OCI": str(w["t"] / "no-oci"),
           "SHIM_SECRETS": str(secrets_dir), "RPM_CHECKSUMS": str(w["sums"]), "OCI_NS": "n", "LPORT": "2222", "HPORT": "8443", "SSH_KEY": str(w["t"] / "sshkey"), "RPMS": str(w["rpms"]),
           "OUT_DIR": str(out), "RECOVERY_ORIGIN": "simulado"}
    k, c, f = w["a"]
    base = ["bash", str(RUNNER), "--kind", "c04", "--bundle", STEM, "--secbundle", secstem or w["secstem"], "--key", str(key or k), "--cert", str(cert or c), "--cert-sha256", sha or f, "--signer-pub", str(w["spub"])]
    if status: base += ["--status-dir", str(status)]
    results = []
    for start, stop in (("download", "build"), ("data", "app2")):
        r = subprocess.run(base, capture_output=True, text=True, env={**env, "START_AT": start, "STOP_BEFORE": stop})
        results.append(r)
        if r.returncode != 0: break
    return results, out, log, secrets_dir


def test_recuperacion_c04_verifica_restaura_y_entrega_las_claves_originales(world):
    status = world["t"] / "panel"
    rs, out, log, secrets_dir = recover(world, tag="ok", status=status)
    assert all(r.returncode == 0 for r in rs), "\n".join(r.stdout[-600:] + r.stderr[-600:] for r in rs)
    txt = "".join(r.stdout for r in rs)
    assert "huella idéntica" in txt and "claves de aplicación = originales" in txt
    assert set(open(log).read().split()) >= {f"backups/c04-20261119/{STEM}.cms", f"secrets/c04-20261119/{world['secstem']}.cms"}
    # la clave privada no sale de la Mac: ni su ruta ni su contenido aparecen en lo enviado por ssh/scp (los simuladores registran los argumentos)
    keyfile = world["a"][0]; sent = open(log).read()
    assert str(keyfile) not in sent and "PRIVATE KEY" not in sent + txt
    env_file = secrets_dir / "secrets.env"
    assert env_file.stat().st_mode & 0o777 == 0o600 and set(l.split("=")[0] for l in env_file.read_text().splitlines()) == set(ORIG)
    assert all(ORIG[k] not in txt for k in ORIG)                     # los valores no se imprimen
    et = json.loads((out / "etapas.json").read_text())
    assert et["resultado"] == "OK" and {"descarga", "datos", "secretos"} <= set(et["etapas"])
    panel = json.loads((status / "recovery-run.json").read_text())
    assert panel["resultado"] == "OK" and panel["origen"] == "simulado" and "datos" in panel["etapas"]


def test_claves_de_aplicacion_distintas_de_las_originales_se_detectan_y_no_se_continua(world):
    """El paquete es válido y está firmado, pero sus valores no son los del manifiesto original (p. ej. valores nuevos generados): código 11, nada arranca."""
    r, d = world["export"]({"TICKET_ENCRYPTION_KEY": "NUEVA-ticket-key-ficticia-9999999999999999=", "SECURITY_HASH_KEY": "NUEVA-hash-key-ficticia-9999999999999999"}, name_dir="sec-nuevas")
    assert r.returncode == 0
    new = next(d.glob("app-secrets-*.cms")).name[:-4]
    good_man = json.loads((world["bucket"] / f"{world['secstem']}.manifest.json").read_text())
    man = json.loads((d / f"{new}.manifest.json").read_text()); man["secret_sha256"] = good_man["secret_sha256"]       # el manifiesto declara las ORIGINALES, el cifrado trae otras
    (d / f"{new}.manifest.json").write_text(json.dumps(man)); world["sign"](d / f"{new}.manifest.json")
    for suf in (".cms", ".manifest.json", ".manifest.json.sig"):
        shutil.copy(d / f"{new}{suf}", world["bucket"] / f"{new}{suf}")
    rs, out, log, secrets_dir = recover(world, tag="nuevas", secstem=new)
    assert rs[-1].returncode == 11 and "NO son las originales" in rs[-1].stderr


def test_paquete_de_claves_para_otro_certificado_firma_invalida_o_sin_huellas_se_rechazan(world):
    kb, cb, fb = world["b"]
    r, d = world["export"](ORIG, cert_path=cb, pin=fb, name_dir="sec-b")
    other = next(d.glob("app-secrets-*.cms")).name[:-4]
    for suf in (".cms", ".manifest.json", ".manifest.json.sig"):
        shutil.copy(d / f"{other}{suf}", world["bucket"] / f"{other}{suf}")
    rs, *_ = recover(world, tag="otro-cert", secstem=other)
    assert rs[-1].returncode == 10 and "destinatario distinto" in rs[-1].stderr
    sig = world["bucket"] / f"{world['secstem']}.manifest.json.sig"; good = sig.read_bytes()
    try:
        sig.write_bytes(good[:-3] + b"xyz")
        rs, *_ = recover(world, tag="firma")
        assert rs[-1].returncode == 9 and "firma del manifiesto NO es válida" in rs[-1].stderr
    finally:
        sig.write_bytes(good)


def test_clave_o_certificado_equivocados_y_oci_caido_abortan_con_estado_real(world):
    status = world["t"] / "panel-x"
    rs, out, log, _ = recover(world, tag="cert", sha="0" * 64)
    assert rs[-1].returncode == 10 and open(log).read() == ""                                    # antes de usar red
    rs, out, log, _ = recover(world, tag="clave", key=world["b"][0])
    assert rs[-1].returncode == 10 and open(log).read() == ""
    rs, out, log, _ = recover(world, tag="oci", no_oci=True, status=status)
    assert rs[-1].returncode != 0
    panel = json.loads((status / "recovery-run.json").read_text())
    assert panel["resultado"] == "FALLO" and panel["etapa_fallida"] == "descarga"


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""
    except OSError:
        return None, ""


def test_la_aplicacion_real_arranca_sobre_los_datos_restaurados_con_las_claves_entregadas(world):
    """Tras `data`+`secrets` (prueba anterior), levanta el BACKEND REAL (uvicorn) sobre la base `nexoeventos` restaurada, con el rol y permisos de la etapa 2 y las claves ORIGINALES
    entregadas por el flujo. /health = liveness (sin BD), /ready = readiness (con PostgreSQL), y el catálogo responde; al caer la BD, /ready pasa a 503 y /health sigue en 200."""
    rs, out, log, secrets_dir = recover(world, tag="app")
    assert all(r.returncode == 0 for r in rs)
    assert world["psql"]("-d", "nexoeventos", input="""GRANT CONNECT ON DATABASE nexoeventos TO nexoeventos_app; GRANT USAGE ON SCHEMA public TO nexoeventos_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexoeventos_app; GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO nexoeventos_app;""").returncode == 0
    sec = dict(l.split("=", 1) for l in (secrets_dir / "secrets.env").read_text().splitlines())
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "APP_ENV": "production", "DATABASE_URL": f"postgresql+psycopg://nexoeventos_app@/nexoeventos?host={world['sock']}&port={world['port']}", "FRONTEND_ORIGINS": "https://localhost:8443",
           "SESSION_COOKIE_SECURE": "true", **sec}
    proc = subprocess.Popen([str(UVICORN), "app.main:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT / "backend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            if _get(base + "/health")[0] == 200: break
            time.sleep(0.5)
        assert _get(base + "/health")[0] == 200
        code, body = _get(base + "/ready"); assert code == 200 and json.loads(body)["status"] == "ready"
        code, body = _get(base + "/api/events"); assert code == 200 and len(json.loads(body)) > 0
        # la BD cae: readiness 503 (no recibir tráfico), liveness 200 (no reemplazar la instancia por una caída de BD)
        run([str(PGBIN / "pg_ctl"), "-D", str(world["t"] / "pg"), "-m", "immediate", "stop"], env=world["env"])
        assert _get(base + "/ready")[0] == 503 and _get(base + "/health")[0] == 200
    finally:
        proc.terminate(); proc.wait(timeout=10)
        run([str(PGBIN / "pg_ctl"), "-D", str(world["t"] / "pg"), "-o", f"-c listen_addresses= -c unix_socket_directories={world['sock']} -c port={world['port']} -c fsync=off", "-l", str(world["t"] / "pg.log"), "-w", "start"], env=world["env"])


def test_nginx_expone_livez_y_ready():
    t = (ROOT / "deploy/nginx/nexoeventos.conf.template").read_text()
    assert "location = /livez" in t and "proxy_pass http://127.0.0.1:8000/health;" in t and "location = /ready" in t and "proxy_pass http://127.0.0.1:8000/ready;" in t
    smoke = (ROOT / "scripts/multicloud/oci-drill/app-smoke.py").read_text()
    assert '"/livez"' in smoke and '"/ready"' in smoke


def test_exportador_de_claves_rechaza_certificado_inesperado_y_exige_firma(world):
    ka, ca, fa = world["a"]
    r, _ = world["export"](ORIG, pin="f" * 64, name_dir="sec-pin")
    assert r.returncode == 10 and "huella SHA-256 esperada" in r.stderr
    d = world["t"] / "sec-nosign"; d.mkdir(exist_ok=True)
    r = subprocess.run(["bash", str(EXPORT), "--kind", "c04", "--source", "stdin", "--cert", str(ca), "--cert-sha256", fa, "--out", str(d)], input="x=1\n", capture_output=True, text=True, cwd=world["t"])
    assert r.returncode == 2 and "--sign-key" in r.stderr
    r, d2 = world["export"]({"TICKET_ENCRYPTION_KEY": "solo-una"}, name_dir="sec-falta")
    assert r.returncode != 0 and "Faltan claves" in r.stderr                 # los errores del filtro siguen visibles
    man = json.loads(next((world["t"] / "sec").glob("*.manifest.json")).read_text())
    assert set(man["secret_sha256"]) == {"TICKET_ENCRYPTION_KEY", "SECURITY_HASH_KEY"} and all(v not in json.dumps(man) for v in ORIG.values())   # huellas, nunca valores


def test_firma_diferida_por_digest_produce_una_firma_valida_con_la_clave_publica_fijada(world):
    """Flujo sin EC2 para los secretos: el exportador cifra y arma el manifiesto SIN firmar; luego solo el SHA-256 del manifiesto se firma con la clave de firma (aquí una ficticia en modo local)."""
    ka, ca, fa = world["a"]; d = world["t"] / "sec-defer"; shutil.rmtree(d, ignore_errors=True); d.mkdir()
    r = subprocess.run(["bash", str(EXPORT), "--kind", "c04", "--source", "stdin", "--cert", str(ca), "--cert-sha256", fa, "--defer-sign", "--out", str(d)],
                       input="".join(f"{k}={v}\n" for k, v in ORIG.items()), capture_output=True, text=True, cwd=world["t"])
    assert r.returncode == 0 and "SIN firmar" in r.stderr, r.stderr
    man = next(d.glob("*.manifest.json")); assert not Path(str(man) + ".sig").exists()
    sign = ROOT / "scripts/multicloud/oci-drill/sign-manifest-remote.sh"
    ok = subprocess.run(["bash", str(sign), "--manifest", str(man), "--signer-pub", str(world["spub"])], capture_output=True, text=True, env={**os.environ, "NEXO_LOCAL_SIGN_KEY": str(world["t"] / "s.key")})
    assert ok.returncode == 0 and Path(str(man) + ".sig").stat().st_mode & 0o777 == 0o600, ok.stderr
    assert subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(world["spub"]), "-signature", str(man) + ".sig", str(man)], capture_output=True).returncode == 0
    # una clave de firma distinta de la fijada NO deja ninguna firma
    other = world["t"] / "otra-firma.key"; subprocess.run(["openssl", "ecparam", "-genkey", "-name", "prime256v1", "-noout", "-out", str(other)], check=True, capture_output=True)
    Path(str(man) + ".sig").unlink()
    bad = subprocess.run(["bash", str(sign), "--manifest", str(man), "--signer-pub", str(world["spub"])], capture_output=True, text=True, env={**os.environ, "NEXO_LOCAL_SIGN_KEY": str(other)})
    assert bad.returncode == 5 and not Path(str(man) + ".sig").exists()


def test_modo_solo_lectura_nginx_y_base_en_el_instalador():
    inst = (ROOT / "scripts/multicloud/oci-drill/install-app.sh").read_text()
    assert "db-permissions.sh" in inst and "RECOVERY_READONLY" in inst
    # la transformación REAL de la plantilla (el script de Python embebido) añade limit_except dentro de /api/ solo en solo lectura
    code = inst.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    tpl = ROOT / "deploy/nginx/nexoeventos.conf.template"
    out = {m: subprocess.run(["python3", "-c", code, str(tpl)], capture_output=True, text=True, env={**os.environ, "RECOVERY_READONLY": m}).stdout for m in ("0", "1")}
    assert "limit_except" not in out["0"]
    api = out["1"].split("location /api/ {", 1)[1].split("}", 2)
    assert "limit_except GET HEAD OPTIONS { deny all; }" in out["1"] and out["1"].index("limit_except") < out["1"].index("proxy_pass http://127.0.0.1:8000;")
    assert "location = /livez" in out["1"] and "location = /ready" in out["1"]


def test_aws_debe_estar_en_reposo_para_recuperar_en_oci(world):
    shim = world["t"] / "shim-aws"; shim.mkdir(exist_ok=True)
    def aws(ec2, rds, rc=0):
        (shim / "aws").write_text(f'#!/usr/bin/env bash\n[[ {rc} -ne 0 ]] && exit {rc}\ncase "$*" in *describe-instances*) echo "{ec2}";; *describe-db-instances*) echo "{rds}";; esac\n'); os.chmod(shim / "aws", 0o755)
    lib = ROOT / "scripts/multicloud/oci-drill/lib-recovery.sh"
    def go():
        return subprocess.run(["bash", "-c", f'fail() {{ echo "FALLÓ: $1" >&2; exit "${{2:-1}}"; }}; source {lib}; aws_writers_quiet prueba'], capture_output=True, text=True,
                              env={**os.environ, "PATH": f"{shim}:{os.environ['PATH']}", "REQUIRE_AWS_STOPPED": "1"})
    aws("stopped", "stopped"); assert go().returncode == 0
    for ec2, rds, rc in (("running", "stopped", 0), ("stopped", "available", 0), ("stopped", "starting", 0), ("", "stopped", 0), ("stopped", "stopped", 255)):
        aws(ec2, rds, rc); r = go(); assert r.returncode == 13 and "NO está en reposo" in r.stderr, (ec2, rds, rc)


def test_t0_de_recuperacion_completa_incluye_el_aprovisionamiento(world):
    t0 = time.time() - 300.0          # el `apply` empezó 5 min antes de que arrancara el orquestador
    out = world["t"] / "out-t0"; shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
    lib = ROOT / "scripts/multicloud/oci-drill/lib-recovery.sh"
    r = subprocess.run(["bash", "-c", f'fail() {{ echo "$1" >&2; exit 2; }}; HERE={ROOT}/scripts/multicloud; OUT={out}; BUNDLE=x; source {lib}; stages_init; stage_begin descarga; stage_end'],
                       capture_output=True, text=True, env={**os.environ, "RECOVERY_T0": f"{t0:.3f}", "RECOVERY_ORIGIN": "simulado"})
    assert r.returncode == 0, r.stderr
    et = json.loads((out / "etapas.json").read_text())
    assert 299 <= et["etapas"]["aprovisionamiento"] <= 330 and et["total_s"] >= 300 and et["resultado"] == "OK"
    bad = subprocess.run(["bash", "-c", f'fail() {{ echo "$1" >&2; exit 2; }}; OUT={out}-2; mkdir -p $OUT; HERE=x; BUNDLE=x; source {lib}; stages_init'], capture_output=True, text=True, env={**os.environ, "RECOVERY_T0": "ayer"})
    assert bad.returncode == 2 and "epoch" in bad.stderr
