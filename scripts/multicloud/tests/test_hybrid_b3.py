import json, os, shutil, subprocess, sys, time
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/multicloud/hybrid"))
from test_pg_fence_hardening import PGBIN, run, start_cluster  # noqa: E402
import hybrid_b3 as B3  # noqa: E402
from app.failover.pg_fence import catalog_snapshot  # noqa: E402
from pg_standby import PsycopgExecutor  # noqa: E402

pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")
PW = "contraseña-secreta-NUNCA-visible-1234"; ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def cl(tmp_path_factory):
    ctx, t, sock = start_cluster(tmp_path_factory, "b3")
    ctx["psql"]("postgres", f"ALTER ROLE master_like PASSWORD '{PW}'; GRANT pg_signal_backend TO master_like")
    yield ctx
    run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


def ejecutar(cl, tmp_path, mode="run", deadline=None, secret_ok=True):
    shim = tmp_path / "bin"; shim.mkdir(exist_ok=True)
    (shim / "aws").write_text("#!/bin/sh\n" + (f"echo '{json.dumps({'username': 'master_like', 'password': PW})}'\n" if secret_ok else "exit 1\n")); (shim / "aws").chmod(0o755)
    script = tmp_path / "remoto.py"; script.write_text(B3.build_remote(endpoint=cl["sock"], business="hard", secret_id="arn:ficticio"))
    env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}", "NEXO_B3_HOST": cl["sock"], "NEXO_B3_PORT": str(cl["port"]), "NEXO_B3_SSLMODE": "disable", "NEXO_B3_MODE": mode, "TMPDIR": str(tmp_path),
           "NEXO_B3_DEADLINE_EPOCH": str(deadline or time.time() + 3600)}
    return subprocess.run([str(ROOT / "backend/.venv/bin/python"), str(script)], capture_output=True, text=True, env=env, timeout=240)


def estado(cl):
    ex = PsycopgExecutor(host=cl["sock"], port=cl["port"], dbname="hard", user="postgres"); pg = PsycopgExecutor(host=cl["sock"], port=cl["port"], dbname="postgres", user="postgres")
    return {"dbs": sorted(r[0] for r in pg("SELECT datname FROM pg_database")), "roles": sorted(r[0] for r in pg("SELECT rolname FROM pg_roles")), "negocio": catalog_snapshot(ex, roles=()),
            "datos": ex("SELECT count(*), coalesce(sum(length(v)),0) FROM reservas")[0]}


def test_b3_completo_en_local_hard_fence_cerrojo_reversion_y_negocio_intacto(cl, tmp_path):
    antes = estado(cl); r = ejecutar(cl, tmp_path); assert r.returncode == 0, r.stderr
    assert PW not in r.stdout + r.stderr
    o = B3.parse(r.stdout); p = o["pasos"]
    assert o["ok"] and "error" not in o, o
    assert p["precheck_ddl_en_lab"]["ok_to_install"] and p["instalado_y_atestado"]["ok"] and p["escritura_previa_aceptada"]["ok"]
    assert p["sesiones_de_prueba"]["sesiones_de_la_aplicacion_lab"] >= 3
    assert p["hard_fence"]["prueba_ok"] and p["hard_fence"]["prueba"]["app_sessions_left"] == 0
    t = p["tras_el_vallado"]
    assert "terminat" in t["sesion_abierta_commit"] or "OperationalError" in t["sesion_abierta_commit"] or "closed" in t["sesion_abierta_commit"].lower()
    assert t["commit_estancado"] != "COMMIT_COMPLETADO" and t["sesiones_restantes"] == 0
    assert "s1-abierta" not in t["filas_en_lab"] and "s2-estancada" not in t["filas_en_lab"] and t["filas_en_lab"].get("base-ficticia") == 1      # solo sobrevive la escritura previa al vallado
    assert p["escritura_posterior_al_vallado"]["resultado"] == "NEXO_FENCE"
    c = p["cerrojo_persistente"]; assert c["guardian_misma_sesion"] == "CERROJADA" and c["guardian_conexion_nueva"] == "CERROJADA" and c["latch_en_base"] is True
    assert p["failback_manual"] == {"frase_incorrecta": "rechazada", "failback_manual_con_frase": "ok"}
    assert o["reversion"]["huella_lab_identica_a_la_previa"] is True and o["reversion"]["borrado"] is True and o["listas_iguales_a_las_iniciales"] is True and o["lab_existe"] is False
    assert o["negocio_huella_identica"] is True and o["efimero_eliminado"] is True
    assert estado(cl) == antes                                                                        # bases, roles, catálogo y datos del «negocio» idénticos
    assert not [x for x in tmp_path.iterdir() if x.name.startswith("nexo-b3-")]


def test_fallo_a_mitad_revierte_y_el_plazo_corto_detiene_antes_de_cambiar_nada(cl, tmp_path):
    antes = estado(cl)
    r = ejecutar(cl, tmp_path, deadline=time.time() + 100)                                           # no hay tiempo: «plazo insuficiente» antes de crear nada
    o = B3.parse(r.stdout); assert not o["ok"] and "plazo insuficiente" in o["error"] and estado(cl) == antes
    r = ejecutar(cl, tmp_path, secret_ok=False); o = B3.parse(r.stdout); assert not o["ok"] and estado(cl) == antes and PW not in r.stdout
    # limpieza manual de un laboratorio a medias
    pgx = PsycopgExecutor(host=cl["sock"], port=cl["port"], dbname="postgres", user="master_like"); pgx("CREATE ROLE nexo_lab_app LOGIN"); pgx("CREATE DATABASE nexo_fence_lab")      # creados por el administrador (como en la RDS real)
    o = B3.parse(ejecutar(cl, tmp_path, mode="cleanup").stdout); assert o["ok"] and estado(cl) == antes


def test_main_rechaza_sin_frase_y_con_poco_plazo():
    assert B3.main(["run", "--instance-id", "i", "--secret-id", "s", "--endpoint", "h"]) == 3
    os.environ["NEXO_ALLOW_CLOUD_CHANGES"] = "YES"
    try: assert B3.main(["run", "--instance-id", "i", "--secret-id", "s", "--endpoint", "h", "--confirm", B3.CONFIRM, "--deadline-epoch", str(time.time() + 300)]) == 3
    finally: os.environ.pop("NEXO_ALLOW_CLOUD_CHANGES")
