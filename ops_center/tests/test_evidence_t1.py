import json

from ops_center import evidence_t1 as T1
from ops_center.evidence import EvidenceRun
from .test_integration_cli import run_cli

GOOD = {"tests": {"par_create_if_none_match": 200, "par_recreate_if_none_match": 412, "par_if_match_vigente": 200, "par_if_match_obsoleto": 412, "par_contenido_intacto_tras_412": True},
        "contendientes": {"n": 8, "rondas_ejecutadas": 20, "siempre_exactamente_uno": True}, "skew_reloj_s": 0.8,
        "lease_race": {"rondas_aprobadas": 20, "rondas_con_mas_de_un_ganador": 0, "rondas_con_validos_simultaneos": 0, "inconclusos": 0, "rondas_sin_ganador": 0},
        "latencias_put_exitosos": {"n": 60, "p50_s": 0.2, "p95_s": 0.9, "max_s": 1.1}, "par_activos_tras_revocar": 0, "estado_url_tras_revocar": {"lease": 404, "attest": 404, "race": 404},
        "versiones_restantes_en_prefijo": 0, "limpio": True, "inventario_previo_intacto": True}


def finish(tmp_path, probe):
    r = EvidenceRun.start(tmp_path, "T1", "t", json.loads(open(__import__("os").path.join(__import__("os").path.dirname(T1.__file__), "criterios", "T1.json")).read())["criteria"])
    p = tmp_path / "probe.json"; p.write_text(json.dumps(probe)); T1.apply(r, p); return r.finish()


def test_probe_completo_y_sano_da_pass(tmp_path):
    res = finish(tmp_path, GOOD); assert res["veredicto"] == "PASS", [c for c in res["criterios"] if c["resultado"] != "CUMPLE"]


def test_lo_no_medido_es_parcial_nunca_pass(tmp_path):
    p = json.loads(json.dumps(GOOD)); del p["lease_race"]; del p["latencias_put_exitosos"]
    res = finish(tmp_path, p); assert res["veredicto"] == "PARCIAL" and {c["id"] for c in res["criterios"] if c["resultado"] == "SIN_MEDIR"} >= {"lease_adquisicion_rondas_exclusivas", "p95_put_exitoso_s"}


def test_violacion_de_exclusividad_es_fail(tmp_path):
    p = json.loads(json.dumps(GOOD)); p["lease_race"]["rondas_con_mas_de_un_ganador"] = 1; p["lease_race"]["rondas_aprobadas"] = 19
    assert finish(tmp_path, p)["veredicto"] == "FAIL"


def test_latencia_alta_reloj_desfasado_y_residuos_son_fail(tmp_path):
    for k, v in (("latencias_put_exitosos", {"p95_s": 3.1}), ("skew_reloj_s", 9.0), ("limpio", False)):
        p = json.loads(json.dumps(GOOD)); p[k] = v; assert finish(tmp_path, p)["veredicto"] == "FAIL", k


def test_ejecucion_interrumpida_o_url_aun_activa_no_pasa(tmp_path):
    p = json.loads(json.dumps(GOOD)); p["interrumpido"] = "KeyboardInterrupt"; assert finish(tmp_path, p)["veredicto"] == "FAIL"
    p = json.loads(json.dumps(GOOD)); p["estado_url_tras_revocar"]["race"] = 200; assert finish(tmp_path, p)["veredicto"] == "FAIL"


def test_cli_evidence_t1(tmp_path):
    env = {"OPS_CENTER_STATE_DIR": str(tmp_path / "ops")}
    code, out = run_cli(["evidence-start", "T1", "--root", str(tmp_path / "ev")], env); run = out.strip()
    pf = tmp_path / "p.json"; pf.write_text(json.dumps(GOOD))
    assert run_cli(["evidence-t1", run, "--probe", str(pf)], env)[0] == 0 and run_cli(["evidence-finish", run], env)[1].strip() == "PASS"


def test_inventario_previo_alterado_es_fail(tmp_path):
    p = json.loads(json.dumps(GOOD)); p["inventario_previo_intacto"] = False; assert finish(tmp_path, p)["veredicto"] == "FAIL"
    p = json.loads(json.dumps(GOOD)); del p["inventario_previo_intacto"]; assert finish(tmp_path, p)["veredicto"] == "PARCIAL"
