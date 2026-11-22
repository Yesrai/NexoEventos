"""ejecutar-t1.sh con un PROBE SIMULADO (script Python local, sin OCI): modo plan sin autorización, abortos, verdicto PASS/FAIL y comprobación del inventario previo."""
import json, os, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ops/ejecutar-t1.sh"
FRASE = "AUTORIZO T1 EN OCI: oci_par_probe.py, bucket nexoeventos-recovery, perfil DEFAULT, 3 PAR temporales"
from .test_evidence_t1 import GOOD

STUB = '''
import json, os, sys
mode = os.environ.get("STUB_MODE", "ok"); n = os.environ.get("STUB_COUNT", "../.count")
cnt = int(open(n).read()) if os.path.exists(n) else 0
if "--plan-only" in sys.argv:
    open(n, "w").write(str(cnt + 1))
    objs = 21 if not (mode == "inventario_cambia" and cnt >= 1) else 22
    ready = not (mode == "no_listo" or (mode == "residuos" and cnt >= 1))
    print(json.dumps({"objetos_vigentes": objs, "bytes_vigentes": 471979, "par_activos_en_el_bucket": 0 if ready else 2, "resultado": "LISTO" if ready else "NO LISTO"})); sys.exit(0 if ready else 2)
good = json.loads(os.environ["STUB_GOOD"]); 
if mode == "viola": good["lease_race"]["rondas_con_mas_de_un_ganador"] = 1; good["lease_race"]["rondas_aprobadas"] = 19
print(json.dumps(good)); sys.exit(0)
'''


def run(tmp_path, mode="ok", auth=True):
    stub = tmp_path / "stub_probe.py"; stub.write_text(STUB); cnt = tmp_path / "count"
    env = {**os.environ, "NEXO_PROBE_PY": sys.executable, "NEXO_PROBE": str(stub), "NEXO_OPS_PY": sys.executable, "NEXO_EVIDENCE_ROOT": str(tmp_path / "ev"), "NEXO_T1_WORKDIR": str(tmp_path / "w"),
           "STUB_MODE": mode, "STUB_GOOD": json.dumps(GOOD), "STUB_COUNT": str(cnt), "PYTHONPATH": str(ROOT), "OPS_CENTER_STATE_DIR": str(tmp_path / "ops")}
    args = ["bash", str(SCRIPT)] + (["--autorizo", FRASE] if auth else [])
    return subprocess.run(args, capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)


def test_sin_autorizacion_solo_lee_y_muestra_la_frase(tmp_path):
    r = run(tmp_path, auth=False); assert r.returncode == 0 and FRASE in r.stdout and "MODO PLAN" in r.stdout and not (tmp_path / "ev").exists()


def test_frase_incorrecta_no_ejecuta(tmp_path):
    stub = tmp_path / "s.py"; stub.write_text(STUB)
    env = {**os.environ, "NEXO_PROBE_PY": sys.executable, "NEXO_PROBE": str(stub), "NEXO_EVIDENCE_ROOT": str(tmp_path / "ev"), "STUB_COUNT": str(tmp_path / "c")}
    r = subprocess.run(["bash", str(SCRIPT), "--autorizo", "si"], capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
    assert "MODO PLAN" in r.stdout and not (tmp_path / "ev").exists()


def test_ejecucion_correcta_da_pass(tmp_path):
    r = run(tmp_path); assert r.returncode == 0, r.stdout + r.stderr; assert "veredicto T1: PASS" in r.stdout and "manifiesto íntegro" in r.stdout
    d = next((tmp_path / "ev").iterdir()); res = json.loads((d / "resultado.json").read_text()); assert res["veredicto"] == "PASS" and {"inicio_probe", "fin_probe"} <= set(res["marcas"])


def test_lectura_previa_no_lista_aborta_sin_ejecutar_el_probe(tmp_path):
    r = run(tmp_path, "no_listo"); assert r.returncode == 2 and "ABORTA" in r.stdout
    d = next((tmp_path / "ev").iterdir()); assert not (d / "probe-salida.json").exists() and json.loads((d / "resultado.json").read_text())["veredicto"] in ("PARCIAL", "FAIL")


def test_violacion_de_exclusividad_da_fail_y_codigo_distinto_de_cero(tmp_path):
    r = run(tmp_path, "viola"); assert r.returncode == 1 and "veredicto T1: FAIL" in r.stdout


def test_inventario_alterado_o_residuos_tras_el_probe_no_pasan(tmp_path):
    for mode in ("inventario_cambia", "residuos"):
        t = tmp_path / mode; t.mkdir(); r = run(t, mode); assert r.returncode == 1 and "veredicto T1: FAIL" in r.stdout, (mode, r.stdout)
