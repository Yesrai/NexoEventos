"""Regresión del 19-nov: `ERROR: cannot execute GRANT in a read-only transaction`. El instalador activaba default_transaction_read_only ANTES de los GRANT (y una reanudación heredaba el ajuste de
un intento fallido). db-permissions.sh concede primero, activa la solo lectura después, es idempotente y comprueba en sesiones nuevas que el rol de la aplicación NO puede modificar nada."""
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/multicloud/oci-drill/db-permissions.sh"
PGBIN = next((Path(p) for p in ("/opt/homebrew/opt/postgresql@18/bin", "/usr/local/opt/postgresql@18/bin") if (Path(p) / "postgres").exists()), None)
pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")


@pytest.fixture
def cluster(tmp_path):
    t = tmp_path; os.chmod(t, 0o700)
    sock = Path("/tmp") / f"dbp{os.getpid()}-{abs(hash(str(t))) % 10**6}"; sock.mkdir(mode=0o700)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "PGHOST": str(sock), "PGPORT": str(port), "PGUSER": "postgres", "LC_ALL": "en_US.UTF-8"}
    subprocess.run([str(PGBIN / "initdb"), "-D", str(t / "pg"), "-U", "postgres", "-E", "UTF8", "--locale=C", "-A", "trust"], env=env, check=True, capture_output=True)
    assert subprocess.run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-o", f"-c listen_addresses= -c unix_socket_directories={sock} -c port={port} -c fsync=off", "-l", str(t / "log"), "-w", "start"], env=env, capture_output=True).returncode == 0
    psql = lambda *a, **k: subprocess.run([str(PGBIN / "psql"), "-v", "ON_ERROR_STOP=1", "-qAt", *a], env=env, capture_output=True, text=True, **k)
    psql("-d", "postgres", input="CREATE ROLE nexoeventos_app LOGIN; CREATE DATABASE nexoeventos;")
    psql("-d", "nexoeventos", input="CREATE TABLE users(id int primary key, name text); INSERT INTO users VALUES (1,'a'),(2,'b'); CREATE TABLE seq_t(id serial primary key, v int);")
    yield dict(env=env, psql=psql, cmd=f"{PGBIN}/psql")
    subprocess.run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=env, capture_output=True)
    shutil.rmtree(sock, ignore_errors=True)


def run(c, mode):
    return subprocess.run(["bash", str(SCRIPT), mode], env={**c["env"], "PSQL": c["cmd"]}, capture_output=True, text=True)


def test_readonly_concede_primero_y_el_rol_no_puede_modificar(cluster):
    r = run(cluster, "readonly")
    assert r.returncode == 0, r.stderr
    assert "NO puede INSERT/UPDATE/DELETE/TRUNCATE/CREATE" in r.stdout
    app = lambda sql: cluster["psql"]("-d", "nexoeventos", "-c", "SET ROLE nexoeventos_app", "-c", "SET default_transaction_read_only = off", "-c", sql)
    assert app("select count(*) from users").stdout.strip().endswith("2")                       # LEE
    for sql in ("INSERT INTO users VALUES (3,'c')", "UPDATE users SET name='x'", "DELETE FROM users", "TRUNCATE users", "CREATE TABLE z(i int)", "SELECT nextval('seq_t_id_seq')"):
        assert app(sql).returncode != 0, sql                                                   # no puede modificar ni siquiera con el modo de sesión desactivado
    assert cluster["psql"]("-d", "nexoeventos", "-c", "SHOW default_transaction_read_only").stdout.strip() == "on"   # sesión nueva en solo lectura
    assert cluster["psql"]("-d", "nexoeventos", "-c", "select count(*) from users").stdout.strip() == "2"            # datos intactos


def test_reanudacion_con_el_ajuste_ya_activo_de_un_intento_fallido_no_repite_el_error(cluster):
    """El estado real tras el fallo: la base ya estaba en solo lectura (ajuste anterior a los GRANT). Con el orden antiguo, el GRANT falla; ahora el script limpia y repite."""
    cluster["psql"]("-d", "postgres", "-c", "ALTER DATABASE nexoeventos SET default_transaction_read_only = on", "-c", "ALTER ROLE nexoeventos_app SET default_transaction_read_only = on")
    old_order = cluster["psql"]("-d", "nexoeventos", "-c", "GRANT USAGE ON SCHEMA public TO nexoeventos_app")
    assert old_order.returncode != 0 and "read-only transaction" in old_order.stderr             # reproduce EXACTAMENTE el defecto
    r = run(cluster, "readonly")
    assert r.returncode == 0, r.stderr
    assert run(cluster, "readonly").returncode == 0                                              # idempotente


def test_readwrite_sigue_disponible_para_el_modo_normal(cluster):
    assert run(cluster, "readwrite").returncode == 0
    assert cluster["psql"]("-d", "nexoeventos", "-c", "SET ROLE nexoeventos_app", "-c", "INSERT INTO users VALUES (9,'z')").returncode == 0


def test_el_instalador_ya_no_activa_la_solo_lectura_antes_de_los_grant():
    inst = (ROOT / "scripts/multicloud/oci-drill/install-app.sh").read_text()
    assert "default_transaction_read_only" not in inst and "db-permissions.sh" in inst        # un único lugar y con el orden correcto
    sh = (SCRIPT).read_text()
    assert sh.index("GRANT USAGE ON SCHEMA") < sh.index("ALTER DATABASE \\\"$DB\\\" SET default_transaction_read_only")
    assert "RESET default_transaction_read_only" in sh and sh.index("RESET default_transaction_read_only") < sh.index("GRANT USAGE ON SCHEMA")
