"""Dry-run de preparación para WRITE_GATE_MODE=enforce: solo lectura, falla cerrado, no cambia el modo. Usa archivos temporales y un servidor HTTP falso; no toca la base de pruebas ni nada real."""
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from app.failover.enforce_readiness import check_enforce_readiness, check_loss_behavior
from app.failover.lease import init_lease
from app.failover.store import FileStore
from app.main import create_app
from tests.test_par_http_gate import H, SECRET, Srv

ROOT = Path(__file__).resolve().parents[2]
CLEAN = lambda: {"bloquea": False, "visibilidad": "completa", "hallazgos": []}


@pytest.fixture(scope="module")
def app():
    return create_app()


def file_env(tmp_path, init=True):
    import tempfile
    tmp_path = Path(tempfile.mkdtemp(dir=tmp_path))                              # un directorio nuevo por entorno
    p = tmp_path / "lease.json"
    if init:
        s = FileStore(p); s.verified = True; init_lease(s)
    return {"WRITE_GATE_MODE": "off", "WRITE_GATE_STORE": "file", "WRITE_GATE_FILE_PATH": str(p), "APP_ENV": "development"}


def states(rep): return {k: v["estado"] for k, v in rep["comprobaciones"].items()}


def test_entorno_listo_con_detector_limpio_es_seguro_para_activar(tmp_path, app):
    env = file_env(tmp_path); lease_file = Path(env["WRITE_GATE_FILE_PATH"])
    before = lease_file.read_bytes()
    rep = check_enforce_readiness(env, app=app, external_check=CLEAN)
    assert rep["veredicto"] == "SEGURO_PARA_ACTIVAR", rep
    assert rep["modo_cambiado"] is False and env["WRITE_GATE_MODE"] == "off"
    assert lease_file.read_bytes() == before                                     # el lease no se tocó
    assert all(rep["comprobaciones"]["perdida_de_lease"]["pruebas"].values())
    assert "off" in rep["comprobaciones"]["modo_actual"]["detalle"]


def test_sin_detector_de_escritores_externos_no_se_declara_seguro(tmp_path, app):
    rep = check_enforce_readiness(file_env(tmp_path), app=app)
    assert rep["veredicto"] == "NO_VERIFICADO" and states(rep)["escritores_externos"] == "NO_VERIFICADO"


def test_hallazgos_que_bloquean_o_visibilidad_parcial_o_fallo_del_detector(tmp_path, app):
    env = file_env(tmp_path)
    assert check_enforce_readiness(env, app=app, external_check=lambda: {"bloquea": True, "visibilidad": "completa", "hallazgos": [{"severity": "BLOQUEA", "kind": "migracion_o_ddl_en_curso", "role": "owner"}]})["veredicto"] == "NO_SEGURO"
    assert check_enforce_readiness(env, app=app, external_check=lambda: {"bloquea": False, "visibilidad": "parcial", "hallazgos": []})["veredicto"] == "NO_VERIFICADO"
    def boom(): raise RuntimeError("detalle sensible")
    rep = check_enforce_readiness(env, app=app, external_check=boom)
    assert rep["veredicto"] == "NO_VERIFICADO" and "sensible" not in json.dumps(rep)


def test_lease_no_inicializado_ilegible_o_con_titular(tmp_path, app):
    assert check_enforce_readiness(file_env(tmp_path, init=False), app=app, external_check=CLEAN)["veredicto"] == "NO_SEGURO"
    env = file_env(tmp_path)
    Path(env["WRITE_GATE_FILE_PATH"]).write_text("basura")                       # archivo corrupto: no debe lanzar, debe bloquear
    rep = check_enforce_readiness(env, app=app, external_check=CLEAN)
    assert rep["veredicto"] == "NO_SEGURO"
    env2 = file_env(tmp_path)                                                    # titular activo: advertencia, no bloqueo
    from app.failover.lease import LeaseClient, LeaseConfig
    s = FileStore(env2["WRITE_GATE_FILE_PATH"]); s.verified = True
    assert LeaseClient(s, LeaseConfig(), "otro-nodo").acquire().ok
    rep = check_enforce_readiness(env2, app=app, external_check=CLEAN)
    assert states(rep)["estado_lease"] == "ADVERTENCIA" and rep["veredicto"] == "SEGURO_PARA_ACTIVAR"


def test_configuracion_invalida_o_incompleta_bloquea(tmp_path, app):
    for env in ({}, {"WRITE_GATE_STORE": "otro"}, {"WRITE_GATE_STORE": "file"}, {"WRITE_GATE_STORE": "par-http"}, {"WRITE_GATE_STORE": "oci-cli"},
                {**file_env(tmp_path), "WRITE_GATE_TTL_S": "5", "WRITE_GATE_MARGIN_S": "4"}, {**file_env(tmp_path), "WRITE_GATE_ROLE": "otro"}, {**file_env(tmp_path), "APP_ENV": "production"}):
        rep = check_enforce_readiness(env, app=app, external_check=CLEAN)
        assert rep["veredicto"] == "NO_SEGURO" and states(rep)["configuracion"] == "BLOQUEA", env


def test_almacen_inalcanzable_bloquea(tmp_path, app):
    env = {"WRITE_GATE_STORE": "par-http", "WRITE_GATE_PAR_URL_FILE": str(tmp_path / "u"), "WRITE_GATE_ALLOW_HTTP_LOCALHOST": "1", "APP_ENV": "development"}
    (tmp_path / "u").write_text("http://127.0.0.1:9/p/x/n/ns/b/bk/o/"); os.chmod(tmp_path / "u", 0o600)
    rep = check_enforce_readiness(env, app=app, external_check=CLEAN)
    assert rep["veredicto"] == "NO_SEGURO" and states(rep)["almacen_conectividad"] == "BLOQUEA" and states(rep)["almacen_semantica"] == "NO_VERIFICADO"


@pytest.fixture
def par(tmp_path):
    s = ThreadingHTTPServer(("127.0.0.1", 0), H); s.s = Srv()
    threading.Thread(target=s.serve_forever, daemon=True).start()
    u = tmp_path / "par.url"; u.write_text(f"http://127.0.0.1:{s.server_port}/p/{SECRET}/n/ns/b/bk/o/"); os.chmod(u, 0o600)
    yield s, {"WRITE_GATE_STORE": "par-http", "WRITE_GATE_PAR_URL_FILE": str(u), "WRITE_GATE_ALLOW_HTTP_LOCALHOST": "1", "APP_ENV": "development"}
    s.shutdown(); s.server_close()


def test_par_http_por_defecto_es_solo_lectura_y_deja_la_semantica_sin_verificar(par, app):
    s, env = par
    from app.failover.store import ParHttpStore
    rep = check_enforce_readiness(env, app=app, external_check=CLEAN)
    assert s.s.puts == 0                                                               # NO escribió nada en el almacén
    assert states(rep)["almacen_semantica"] == "NO_VERIFICADO" and states(rep)["estado_lease"] == "BLOQUEA"      # y el lease no está inicializado
    assert rep["veredicto"] == "NO_SEGURO"


def test_autoprueba_opt_in_detecta_un_servicio_que_ignora_las_condiciones(par, app):
    s, env = par
    from app.failover.store import ParHttpStore
    st = ParHttpStore(Path(env["WRITE_GATE_PAR_URL_FILE"]), object_name="writer-lease.json", allow_http_localhost=True); st.verified = True; init_lease(st)
    rep = check_enforce_readiness(env, app=app, external_check=CLEAN, selftest_writes=True)
    assert states(rep)["almacen_semantica"] == "OK" and rep["veredicto"] == "SEGURO_PARA_ACTIVAR"
    s.s.enforce = False
    rep = check_enforce_readiness(env, app=app, external_check=CLEAN, selftest_writes=True)
    assert states(rep)["almacen_semantica"] == "BLOQUEA" and rep["veredicto"] == "NO_SEGURO"


def test_comportamiento_ante_perdida_del_lease_y_reversion_y_activacion_fallida(tmp_path, app):
    sim = check_loss_behavior()
    assert all(sim.values()), sim
    rep = check_enforce_readiness(file_env(tmp_path), app=app, external_check=CLEAN)["comprobaciones"]
    assert rep["reversion"]["estado"] == "OK" and any("write-gate" in p for p in rep["reversion"]["pasos"])
    assert rep["activacion_fallida"]["estado"] == "OK" and "solo lectura" in rep["activacion_fallida"]["detalle"]
    assert rep["rutas"]["estado"] == "OK" and rep["rutas"]["login_y_registro_requieren_lease"] is True


def test_no_modifica_el_entorno_ni_el_modo(tmp_path, app, monkeypatch):
    monkeypatch.delenv("WRITE_GATE_MODE", raising=False)
    before = dict(os.environ)
    check_enforce_readiness(file_env(tmp_path), app=app, external_check=CLEAN)
    assert dict(os.environ) == before and "WRITE_GATE_MODE" not in os.environ


def test_cli_codigos_de_salida_y_sin_activar_la_compuerta(tmp_path):
    fe = file_env(tmp_path); lease_file = Path(fe["WRITE_GATE_FILE_PATH"])
    env = {**os.environ, **fe, "WRITE_GATE_MODE": "enforce"}                                # aunque el entorno diga enforce, el CLI construye la app SIN compuerta
    r = subprocess.run([sys.executable, str(ROOT / "scripts/multicloud/enforce-dryrun.py")], capture_output=True, text=True, env=env, cwd=ROOT / "backend", timeout=120)
    out = json.loads(r.stdout)
    assert r.returncode == 2 and out["veredicto"] == "NO_VERIFICADO" and out["modo_cambiado"] is False        # sin detector → no verificado
    from app.failover.lease import Record
    st = FileStore(lease_file); assert Record.load(st.read().data).holder is None                           # el lease sigue libre: no se adquirió
    bad = subprocess.run([sys.executable, str(ROOT / "scripts/multicloud/enforce-dryrun.py"), "--monitor-url-file", str(tmp_path / "no-existe")], capture_output=True, text=True, env=env, cwd=ROOT / "backend")
    assert bad.returncode == 2 and "0600" in bad.stderr
