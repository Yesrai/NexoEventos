import hashlib, json, os, stat, subprocess, sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/multicloud/hybrid"))
import shutil
from test_pg_fence_hardening import PGBIN, run, start_cluster  # noqa: E402
import hybrid_b2 as B2  # noqa: E402
from app.failover.pg_fence import catalog_snapshot  # noqa: E402
from pg_standby import PsycopgExecutor  # noqa: E402

pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")
PW = "contraseña-secreta-NUNCA-visible-1234"
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def cl(tmp_path_factory):
    ctx, t, sock = start_cluster(tmp_path_factory, "b2")
    ctx["psql"]("postgres", f"ALTER ROLE master_like PASSWORD '{PW}'")
    yield ctx
    run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


def ejecutar_remoto(cl, tmp_path, secret_ok=True):
    shim = tmp_path / "bin"; shim.mkdir(exist_ok=True)
    (shim / "aws").write_text("#!/bin/sh\n" + (f"echo '{json.dumps({'username': 'master_like', 'password': PW})}'\n" if secret_ok else "exit 1\n")); (shim / "aws").chmod(0o755)
    script = tmp_path / "remoto.py"; script.write_text(B2.build_remote(endpoint=cl["sock"], dbname="hard", secret_id="arn:ficticio"))
    env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}", "NEXO_B2_HOST": cl["sock"], "NEXO_B2_PORT": str(cl["port"]), "NEXO_B2_SSLMODE": "disable", "TMPDIR": str(tmp_path)}
    return subprocess.run([str(ROOT / "backend/.venv/bin/python"), str(script)], capture_output=True, text=True, env=env)


def test_el_script_remoto_lee_solo_no_filtra_la_contrasena_y_elimina_el_archivo_efimero(cl, tmp_path):
    ex = PsycopgExecutor(host=cl["sock"], port=cl["port"], dbname="hard", user="postgres")
    antes = (catalog_snapshot(ex, roles=("nexo_fence_keeper", "nexoeventos_app")), ex("SELECT count(*), coalesce(sum(length(v)),0) FROM reservas")[0], ex("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal")[0])
    r = ejecutar_remoto(cl, tmp_path); assert r.returncode == 0, r.stderr
    assert PW not in r.stdout and PW not in r.stderr                                          # la contraseña nunca sale
    out = B2.parse_output(r.stdout)
    assert out["ok"] and out["transaction_read_only"] == "on" and out["archivo_permisos"] == "0o600" and out["efimero_eliminado"] is True
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("nexo-b2-")]               # el directorio efímero ya no existe
    h = out["hechos"]; assert h["read_only"] and h["member_rds_superuser"] and h["max_prepared_transactions"] == 0 and "can_signal_backends" in h and "track_commit_timestamp" in h
    v = B2.readonly_verdict(h); assert v["ok_to_install"] is None and any("B3" in w for w in v["warnings"])
    despues = (catalog_snapshot(ex, roles=("nexo_fence_keeper", "nexoeventos_app")), ex("SELECT count(*), coalesce(sum(length(v)),0) FROM reservas")[0], ex("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal")[0])
    assert antes == despues                                                                    # ni catálogo, ni datos, ni triggers cambiaron


def test_fallo_del_secreto_no_deja_archivos_ni_datos_en_el_mensaje(cl, tmp_path):
    r = ejecutar_remoto(cl, tmp_path, secret_ok=False); out = B2.parse_output(r.stdout)
    assert out["ok"] is False and out["error"] == "RuntimeError" and out["efimero_eliminado"] is True and PW not in r.stdout + r.stderr
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("nexo-b2-")]


def test_el_script_no_contiene_ddl_ni_dml_ni_secretos_y_el_cliente_exige_las_dos_llaves(tmp_path):
    src = B2.build_remote(endpoint="h", dbname="d", secret_id="s")
    for prohibido in ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ", "GRANT ", "REVOKE ", "pg_terminate_backend", "pg_cancel_backend", "SET session_replication_role"): assert prohibido not in src, prohibido
    assert "BEGIN TRANSACTION READ ONLY" in src and "print(" in src and "password" not in src.split("print(")[-1]
    assert B2.main(["run", "--instance-id", "i-1", "--secret-id", "s", "--endpoint", "h"]) == 3
    assert B2.main(["run", "--instance-id", "i-1", "--confirm", "no"]) == 3
