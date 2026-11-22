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


def azure(tmp, p):
    out = tmp / "az.json"; rc = T5.main(["azure", "--history", str(p), "--desde", "2026-11-24T09:00:00Z", "--hasta", "2026-11-24T11:00:00Z", "--out", str(out)]); return rc, json.loads(out.read_text())


def test_azure_registra_la_caida_parcial_y_exige_continuidad(tmp_path):
    rc, r = azure(tmp_path, hist(tmp_path)); assert rc == 0 and r["estados_aws"] == {"OK": 7, "ADVERTENCIA": 1} and r["ciclos"] == 8
    for kw in ({"n": 3}, {"hueco_en": 4}, {"sondas": False}):
        t2 = tmp_path / str(kw); t2.mkdir(); assert azure(t2, hist(t2, **kw))[0] == 1
