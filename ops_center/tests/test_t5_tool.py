"""T5 — compilador de evidencias: PASS solo con 9 mediciones reales cumplidas; cada desviación o ausencia impide el PASS; la sustitución exige que el ASG (no la restauración manual) reponga la capacidad."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import ejecutar_t5 as T5  # noqa: E402

FMT = "%Y-%m-%dT%H:%M:%SZ"


def resultado(**ev):
    e = {"victim": "aa11bb", "other": "cc22dd", "allow_replacement": True, "abort_reason": None, "detection_after_stop_s": 22.6, "capacity_restored_after_stop_s": 180.0}
    e.update(ev)
    return {"events": e, "final": {"alb": {"cc22dd": "healthy", "ee33ff": "healthy"}, "asg": [["InService", "Healthy"]] * 2, "asg_activities_new": ["Launching a new EC2 instance: i-0abc", "Terminating EC2 instance: i-0aa11bb"]}}


def solicitudes(n=400, malos=2):
    return [{"t": i, "path": "/healthz" if i % 2 else "/api/events", "status": 502 if i < malos * 2 and i % 2 else 200} for i in range(n)]


def medidas(tmp, res=None, reqs=None, **over):
    d = tmp / "m"; d.mkdir()
    files = {"resultado": res or resultado(), "solicitudes": reqs or solicitudes(), "zonas": {"ok": True}, "datos": {"ok": True}, "azure": {"ok": True}, "limpieza": {"ok": True}, "costos": {"usd": 0.5}}
    files.update(over)
    for n, c in files.items():
        if c is not None: (d / f"{n}.json").write_text(json.dumps(c))
    return d


def go(tmp, **kw):
    d = medidas(tmp, **kw); rc = T5.main(["evidencia", "--medidas", str(d), "--evidence-root", str(tmp / "ev")])
    return rc, json.loads((next((tmp / "ev").iterdir()) / "resultado.json").read_text())


def test_todo_cumplido_es_pass_con_9_criterios(tmp_path):
    rc, r = go(tmp_path); assert rc == 0 and r["veredicto"] == "PASS" and len(r["criterios"]) == 9


@pytest.mark.parametrize("nombre", ["zonas", "datos", "azure", "limpieza", "costos"])
def test_ausente_o_fallida_no_es_pass(tmp_path, nombre):
    assert go(tmp_path, **{nombre: None})[0] == 1
    t2 = tmp_path / "b"; t2.mkdir(); assert go(t2, **{nombre: {"ok": False, "usd": 9}})[0] == 1


@pytest.mark.parametrize("ev", [{"detection_after_stop_s": 31.0}, {"detection_after_stop_s": None}, {"capacity_restored_after_stop_s": 301.0}, {"capacity_restored_after_stop_s": None}, {"abort_reason": "ALB sin destinos sanos"}, {"allow_replacement": False}])
def test_desviaciones_de_tiempos_o_aborto_no_son_pass(tmp_path, ev):
    assert go(tmp_path, res=resultado(**ev))[0] == 1


def test_sin_sustitucion_real_no_hay_pass_aunque_vuelvan_a_estar_sanos(tmp_path):
    res = resultado(); res["final"]["alb"] = {"aa11bb": "healthy", "cc22dd": "healthy"}                # la víctima sigue ahí: restauración manual, no sustitución
    rc, r = go(tmp_path, res=res); assert rc == 1 and any(c["id"] == "ec2_reemplazada_por_asg" and c["resultado"] != "CUMPLE" for c in r["criterios"])
    t2 = tmp_path / "b"; t2.mkdir(); res = resultado(); res["final"]["asg_activities_new"] = ["Terminating EC2 instance"]       # sin actividad de lanzamiento
    assert go(t2, res=res)[0] == 1


def test_disponibilidad_bajo_99_o_sin_solicitudes_no_es_pass(tmp_path):
    assert go(tmp_path, reqs=solicitudes(100, malos=20))[0] == 1
    t2 = tmp_path / "b"; t2.mkdir(); assert go(t2, solicitudes=None, reqs=[{"t": 0, "path": "/api/events", "status": 200}])[0] == 1          # sin sondeos de salud no se mide


def test_derive_calcula_valores_exactos():
    v = T5.derive(resultado(), solicitudes(400, 2)); assert v["deteccion_s"] == 22.6 and v["sustitucion_sana_s"] == 180.0 and v["ec2_reemplazada_por_asg"] is True and 98.0 < v["disponibilidad_livez_pct"] <= 100


def hist(tmp, n=8, paso=60, hueco_en=None, sondas=True):
    t = datetime(2026, 11, 24, 10, 0, 0); L = []
    for i in range(n):
        if hueco_en == i: t += timedelta(seconds=400)
        L.append(json.dumps({"t": t.strftime(FMT), "aws": "OK" if i != 3 else "ADVERTENCIA", "oci": "ADVERTENCIA", "azure": "OK", "sondas": {"aws": [{"path": "/livez", "code": 200 if i != 3 else 502, "ms": 30}] if sondas else []}})); t += timedelta(seconds=paso)
    p = tmp / "h.jsonl"; p.write_text("\n".join(L) + "\n"); return p


def azure(tmp, p, *extra):
    out = tmp / "az.json"; rc = T5.main(["azure", "--history", str(p), "--desde", "2026-11-24T09:00:00Z", "--hasta", "2026-11-24T11:00:00Z", "--out", str(out), *extra]); return rc, json.loads(out.read_text())


def fast(tmp, falla_desde=None, falla_hasta=None, paso=5.0, n=200, extra_fallo=None, t0=datetime(2026, 11, 24, 10, 0, 0)):
    """Muestras de 5 s con ms; fallan las del intervalo [falla_desde, falla_hasta) (segundos desde t0)."""
    L = []
    for i in range(n):
        t = t0 + timedelta(seconds=i * paso); off = i * paso
        bad = (falla_desde is not None and falla_desde <= off < falla_hasta) or (extra_fallo is not None and abs(off - extra_fallo) < 1)
        L.append(json.dumps({"t": t.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (t.microsecond // 1000), "code": 502 if bad else 200, "ms": 40}))
    p = tmp / "fast.jsonl"; p.write_text("\n".join(L) + "\n"); return p


INC = ("--incidente-desde", "2026-11-24T10:06:40Z", "--incidente-hasta", "2026-11-24T10:07:02Z")


def test_azure_sin_sonda_rapida_no_es_valido_aunque_el_recolector_este_bien(tmp_path):
    rc, r = azure(tmp_path, hist(tmp_path)); assert rc == 1 and r["ok"] is False and r["ok_recolector"] is True and "falta la sonda rápida" in r["motivo"]


def test_azure_con_sonda_rapida_captura_el_incidente_corto(tmp_path):
    rc, r = azure(tmp_path, hist(tmp_path), "--fast", str(fast(tmp_path, 400, 422)), *INC)         # 22 s de fallo a partir de +400 s (= 10:06:40)
    assert rc == 0 and r["ok"] and r["rapida"]["incidente_capturado"] and r["rapida"]["fallos"] == 5 and r["rapida"]["fallos_inexplicados"] == 0 and r["resolucion_max_s"] == 5.0
    assert r["rapida"]["primer_fallo"].endswith(".000Z") and r["rapida"]["muestras_antes_del_incidente_s"] >= 300


def test_azure_falla_si_no_captura_el_incidente_si_hay_fallos_inexplicados_o_poca_resolucion(tmp_path):
    casos = {"no captura": fast(tmp_path, None, None), "fallo inexplicado": fast(tmp_path, 400, 422, extra_fallo=100)}
    for nombre, f in casos.items():
        t = tmp_path / nombre.replace(" ", "_"); t.mkdir(); assert azure(t, hist(t), "--fast", str(f), *INC)[0] == 1, nombre
    t = tmp_path / "lenta"; t.mkdir(); assert azure(t, hist(t), "--fast", str(fast(t, 400, 422, paso=20.0, n=60)), *INC)[0] == 1          # muestreo de 20 s: no es «5–10 s»
    t = tmp_path / "sin_base"; t.mkdir(); assert azure(t, hist(t), "--fast", str(fast(t, 60, 82, n=100)), "--incidente-desde", "2026-11-24T10:01:00Z", "--incidente-hasta", "2026-11-24T10:01:22Z")[0] == 1   # < 5 min de línea base


def test_azure_recolector_con_huecos_o_pocos_ciclos_sigue_siendo_invalido(tmp_path):
    for kw in ({"n": 3}, {"hueco_en": 4}, {"sondas": False}):
        t2 = tmp_path / str(kw); t2.mkdir(); assert azure(t2, hist(t2, **kw), "--fast", str(fast(t2, 400, 422)), *INC)[0] == 1


def test_derive_con_seis_instancias_exige_seis_sanas_y_la_victima_ausente():
    r = resultado(expected_instances=6); r["final"]["alb"] = {f"i{k}": "healthy" for k in range(6)}
    assert T5.derive(r, solicitudes())["ec2_reemplazada_por_asg"] is True
    r["final"]["alb"] = {f"i{k}": "healthy" for k in range(5)}; assert T5.derive(r, solicitudes())["ec2_reemplazada_por_asg"] is False        # solo 5 de 6
    r["final"]["alb"] = {f"i{k}": "healthy" for k in range(5)} | {"aa11bb": "healthy"}; assert T5.derive(r, solicitudes())["ec2_reemplazada_por_asg"] is False      # la víctima sigue ahí
    r = resultado(); assert T5.derive(r, solicitudes())["ec2_reemplazada_por_asg"] is True       # sin el campo se asume 2, como en el 1.er intento


def test_fast_analysis_cuenta_solicitudes_fallidas_de_las_rafagas(tmp_path):
    L = []
    for i in range(120):
        t = datetime(2026, 11, 24, 10, 0, 0) + timedelta(seconds=i * 5); bad = 80 <= i <= 82
        L.append(json.dumps({"t": t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "code": 502 if bad else 200, "ms": 40, "burst": 6, "fallos": 1 if bad else 0}))
    p = tmp_path / "f.jsonl"; p.write_text("\n".join(L) + "\n")
    fa = T5.fast_analysis(p, "2026-11-24T09:00:00Z", "2026-11-24T11:00:00Z", "2026-11-24T10:06:35Z", "2026-11-24T10:06:50Z")
    assert fa["fallos"] == 3 and fa["solicitudes_fallidas"] == 3 and fa["solicitudes_por_muestra"] == 6 and fa["incidente_capturado"] is True
