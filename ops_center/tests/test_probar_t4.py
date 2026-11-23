"""T4 — comprobaciones contra la VM (probar_t4_azure.py) ejecutadas aquí contra el servicio REAL del centro y el testigo REAL (procesos locales): lo que se medirá en Azure ya está validado en local."""
import base64
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from ops_center.app import create_app
from ops_center.tests.conftest import TOKENS

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts/ops/probar_t4_azure.py"
sys.path.insert(0, str(ROOT / "scripts/multicloud/tests"))


def free_port():
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def ops(settings):
    p = free_port(); srv = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=p, log_level="error")); t = threading.Thread(target=srv.run, daemon=True); t.start()
    for _ in range(100):
        try: __import__("socket").create_connection(("127.0.0.1", p), 0.2).close(); break
        except OSError: time.sleep(0.05)
    yield f"http://127.0.0.1:{p}"; srv.should_exit = True; t.join(5)


def run(args, env):
    return subprocess.run([sys.executable, str(PROBE), *args], capture_output=True, text=True, env={**os.environ, **env}, cwd=str(ROOT))


def test_panel_con_aws_caido_real_pasa_roles_denegaciones_auditoria_y_bloqueo(ops, settings, tmp_path):
    from ops_center import collector as C
    C.write_snapshot(settings, C.collect(settings, {"aws": {"base": "https://aws.invalid"}, "oci": {"base": "https://oci.invalid", "modo": "alcanzabilidad"}}, free_gb=50))      # AWS NO responde de verdad
    out = tmp_path / "m"
    p = run(["panel", "--base", ops, "--allow-http-localhost", "--out", str(out)], {"T4_TOKEN_VIEWER": TOKENS["viewer"], "T4_TOKEN_REQUESTER": TOKENS["requester"], "T4_TOKEN_APPROVER": TOKENS["approver"]})
    d = {n: json.loads((out / f"{n}.json").read_text()) for n in ("panel_sin_aws", "auditoria", "bloqueo")}
    assert p.returncode == 0, (p.stdout, p.stderr, [r for r in d["auditoria"]["pruebas"] if not r["ok"]])
    assert d["panel_sin_aws"]["ok"] and d["panel_sin_aws"]["aws_estado"] == "ERROR" and d["auditoria"]["ok"] and d["bloqueo"]["ok"]
    assert oct((out / "auditoria.json").stat().st_mode)[-3:] == "600"


def test_panel_no_declara_sin_aws_si_no_hay_sondas_reales_de_aws(ops, settings, tmp_path):
    out = tmp_path / "m"        # sin instantánea: AWS «No verificado», no ERROR
    run(["panel", "--base", ops, "--allow-http-localhost", "--out", str(out)], {"T4_TOKEN_VIEWER": TOKENS["viewer"], "T4_TOKEN_REQUESTER": TOKENS["requester"], "T4_TOKEN_APPROVER": TOKENS["approver"]})
    assert json.loads((out / "panel_sin_aws.json").read_text())["ok"] is False


def test_panel_con_token_de_requester_cambiado_falla_las_pruebas_de_rol(ops, tmp_path):
    out = tmp_path / "m"; p = run(["panel", "--base", ops, "--allow-http-localhost", "--out", str(out)], {"T4_TOKEN_VIEWER": TOKENS["viewer"], "T4_TOKEN_REQUESTER": TOKENS["viewer"], "T4_TOKEN_APPROVER": TOKENS["approver"]})
    assert p.returncode == 1 and json.loads((out / "auditoria.json").read_text())["ok"] is False             # un «requester» que en realidad es viewer no puede solicitar


def test_la_sonda_rechaza_http_remoto_y_exige_token(tmp_path):
    assert run(["panel", "--base", "http://example.com", "--out", str(tmp_path)], {}).returncode != 0
    p = run(["panel", "--base", "https://127.0.0.1:1", "--out", str(tmp_path)], {"T4_TOKEN_VIEWER": "", "T4_TOKEN_REQUESTER": "", "T4_TOKEN_APPROVER": ""}); assert p.returncode != 0


# ---------------- testigo real como proceso ----------------
def witness_proc(tmp, port):
    d = tmp / "w"; d.mkdir()
    pr = subprocess.run([sys.executable, str(ROOT / "deploy/azure/preparar-testigo.py"), "--dir", str(d / "etc")], capture_output=True, text=True); assert pr.returncode == 0, pr.stderr
    toks = dict(l.strip().split(": ", 1) for l in pr.stdout.splitlines() if l.startswith("  t4-"))
    launch = ("import sys,os,time;sys.path.insert(0,r'%s/backend');sys.path.insert(0,r'%s/scripts/multicloud/witness');import witness_service as WS;"
              "w=WS.build_from_env();srv=WS.serve(w,host='127.0.0.1',port=int(os.environ['P']),invokers=WS.invokers_from_env());print('LISTO',flush=True);time.sleep(600)") % (ROOT, ROOT)
    env = {**os.environ, "P": str(port), "WITNESS_STORE": f"file:{d/'store.jsonl'}", "WITNESS_SIGNER": f"local-ecdsa:{d/'signer.pem'}", "WITNESS_ALLOW_LOCAL_SIGNER": "1",
           "WITNESS_REPORTERS_FILE": str(d / "etc/reporters.json"), "WITNESS_INVOKER_TOKENS_FILE": str(d / "etc/invokers.json")}
    pop = subprocess.Popen([sys.executable, "-c", launch], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(100):
        try: __import__("socket").create_connection(("127.0.0.1", port), 0.2).close(); break
        except OSError: time.sleep(0.1)
    sys.path.insert(0, str(ROOT / "backend")); from app.failover.witness import LocalEcdsaFileSigner
    der = base64.b64encode(LocalEcdsaFileSigner(str(d / "signer.pem")).public_der()).decode(); (d / "pub.der.b64").write_text(der)
    return pop, toks, d


def restart(pop, d, port):
    pop.kill(); pop.wait(5)
    launch = ("import sys,os,time;sys.path.insert(0,r'%s/backend');sys.path.insert(0,r'%s/scripts/multicloud/witness');import witness_service as WS;"
              "w=WS.build_from_env();srv=WS.serve(w,host='127.0.0.1',port=int(os.environ['P']),invokers=WS.invokers_from_env());print('LISTO',flush=True);time.sleep(600)") % (ROOT, ROOT)
    env = {**os.environ, "P": str(port), "WITNESS_STORE": f"file:{d/'store.jsonl'}", "WITNESS_SIGNER": f"local-ecdsa:{d/'signer.pem'}", "WITNESS_ALLOW_LOCAL_SIGNER": "1",
           "WITNESS_REPORTERS_FILE": str(d / "etc/reporters.json"), "WITNESS_INVOKER_TOKENS_FILE": str(d / "etc/invokers.json")}
    p2 = subprocess.Popen([sys.executable, "-c", launch], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(100):
        try: __import__("socket").create_connection(("127.0.0.1", port), 0.2).close(); break
        except OSError: time.sleep(0.1)
    return p2


def test_testigo_real_auth_roles_firma_sin_inicializar_y_persistencia_tras_reinicio(tmp_path):
    port = free_port(); pop, toks, d = witness_proc(tmp_path, port); procs = [pop]
    try:
        out = tmp_path / "m"; env = {"T4_TOKEN_ATESTADOR": toks["t4-atestador"], "T4_TOKEN_LECTOR": toks["t4-lector"]}
        base = ["testigo", "--base", f"http://127.0.0.1:{port}", "--allow-http-localhost", "--out", str(out), "--witness-pub-der", str(d / "pub.der.b64")]
        p = run(base + ["--fase", "pre", "--estado", str(tmp_path / "pre.json")], env)
        r = json.loads((out / "testigo_auth.json").read_text()); assert p.returncode == 0, [x for x in r["pruebas"] if not x["ok"]]; assert r["ok"] and len(r["pruebas"]) == 10
        p2 = restart(pop, d, port); procs.append(p2)                                  # kill + arranque con el MISMO almacén y las mismas claves
        (tmp_path / "pytest-vm.json").write_text(json.dumps({"ok": True, "passed": 63}))
        p = run(base + ["--fase", "post", "--estado", str(tmp_path / "pre.json"), "--pytest-vm", str(tmp_path / "pytest-vm.json")], env)
        per = json.loads((out / "testigo_persistencia.json").read_text()); assert p.returncode == 0 and per["ok"] and per["estado_igual_tras_reinicio"]
        (tmp_path / "pytest-vm.json").write_text(json.dumps({"ok": False}))                       # sin las pruebas de la VM en verde no hay persistencia demostrada
        run(base + ["--fase", "post", "--estado", str(tmp_path / "pre.json"), "--pytest-vm", str(tmp_path / "pytest-vm.json")], env); assert json.loads((out / "testigo_persistencia.json").read_text())["ok"] is False
    finally:
        for q in procs:
            if q.poll() is None: q.kill()


def test_testigo_con_tokens_equivocados_falla_y_no_hay_firma_sin_clave_publica(tmp_path):
    port = free_port(); pop, toks, d = witness_proc(tmp_path, port)
    try:
        out = tmp_path / "m"
        p = run(["testigo", "--base", f"http://127.0.0.1:{port}", "--allow-http-localhost", "--out", str(out)], {"T4_TOKEN_ATESTADOR": toks["t4-lector"], "T4_TOKEN_LECTOR": toks["t4-atestador"]})
        assert p.returncode == 1 and json.loads((out / "testigo_auth.json").read_text())["ok"] is False
        p = run(["testigo", "--base", f"http://127.0.0.1:{port}", "--allow-http-localhost", "--out", str(out)], {"T4_TOKEN_ATESTADOR": toks["t4-atestador"], "T4_TOKEN_LECTOR": toks["t4-lector"]})
        assert p.returncode == 1 and any("clave pública" in x["prueba"] and not x["ok"] for x in json.loads((out / "testigo_auth.json").read_text())["pruebas"])      # sin clave anclada no se acepta la firma
    finally: pop.kill()


def test_preparar_testigo_no_sobrescribe_y_no_guarda_tokens_en_claro(tmp_path):
    d = tmp_path / "e"; a = subprocess.run([sys.executable, str(ROOT / "deploy/azure/preparar-testigo.py"), "--dir", str(d)], capture_output=True, text=True); assert a.returncode == 0
    toks = [l.split(": ")[1] for l in a.stdout.splitlines() if l.startswith("  t4-")]; raw = (d / "invokers.json").read_text() + (d / "reporters.json").read_text()
    assert all(t not in raw for t in toks) and oct((d / "invokers.json").stat().st_mode)[-3:] == "600" and oct((d / "reporters.json").stat().st_mode)[-3:] == "600"
    b = subprocess.run([sys.executable, str(ROOT / "deploy/azure/preparar-testigo.py"), "--dir", str(d)], capture_output=True, text=True); assert b.returncode == 2
