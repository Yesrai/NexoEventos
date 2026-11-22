"""T4 — compilador de evidencias: PASS solo con las 18 mediciones cumplidas; una ausente o fallida impide el PASS; el cálculo del colector exige ciclos reales continuos."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import ejecutar_t4 as T4  # noqa: E402

FMT = "%Y-%m-%dT%H:%M:%SZ"
NOMBRES = list(T4.MAP.values())


def medidas(tmp, **over):
    d = tmp / "m"; d.mkdir()
    base = {n: {"ok": True, "utc": "2026-11-23T10:00:00Z"} for n in NOMBRES}
    base["colector"] = {"ok": True, "tres_nubes_con_origen": True}; base["costos"] = {"usd": 0.6}
    base["correo"] = {"ok": True, "confirmado_por": "propietaria", "asunto": "Fired: alerta", "hora_recepcion_utc": "2026-11-23T10:05:00Z", "utc": "2026-11-23T10:06:00Z"}
    base.update(over)
    for n, c in base.items():
        if c is not None: (d / f"{n}.json").write_text(json.dumps(c))
    return d


def veredicto(tmp):
    return json.loads((next((tmp / "ev").iterdir()) / "resultado.json").read_text())


def go(tmp, **over):
    d = medidas(tmp, **over); return T4.main(["evidencia", "--medidas", str(d), "--evidence-root", str(tmp / "ev")])


def test_todo_cumplido_es_pass(tmp_path):
    assert go(tmp_path) == 0; r = veredicto(tmp_path); assert r["veredicto"] == "PASS" and len(r["criterios"]) == 18


@pytest.mark.parametrize("nombre", NOMBRES)
def test_una_medicion_fallida_impide_el_pass(tmp_path, nombre):
    assert go(tmp_path, **{nombre: {"ok": False}}) == 1 and veredicto(tmp_path)["veredicto"] != "PASS"


@pytest.mark.parametrize("nombre", NOMBRES + ["colector", "costos"])
def test_una_medicion_ausente_impide_el_pass(tmp_path, nombre):
    assert go(tmp_path, **{nombre: None}) == 1 and veredicto(tmp_path)["veredicto"] != "PASS"


def test_costo_sobre_el_umbral_o_tres_nubes_incompleto_fallan(tmp_path):
    assert go(tmp_path, costos={"usd": 5.0}) == 1
    t2 = tmp_path / "b"; t2.mkdir(); assert go(t2, colector={"ok": True, "tres_nubes_con_origen": False}) == 1


def hist(tmp, n=12, paso=60, aws="ERROR", oci="ADVERTENCIA", sondas=True, hueco_en=None):
    t = datetime(2026, 11, 23, 10, 0, 0); lines = []
    for i in range(n):
        if hueco_en == i: t += timedelta(seconds=400)
        s = [{"path": "/livez", "code": 0, "ms": 5, "error": "URLError"}] if sondas else []
        lines.append(json.dumps({"t": t.strftime(FMT), "aws": aws, "oci": oci, "azure": "OK", "sondas": {"aws": s, "oci": s}})); t += timedelta(seconds=paso)
    p = tmp / "h.jsonl"; p.write_text("\n".join(lines) + "\n"); return p


def colector(tmp, p, snap=None):
    out = tmp / "c.json"; args = ["colector", "--history", str(p), "--desde", "2026-11-23T09:00:00Z", "--hasta", "2026-11-23T11:00:00Z", "--out", str(out)]
    if snap: args += ["--snapshot", str(snap)]
    rc = T4.main(args); return rc, json.loads(out.read_text())


def test_colector_ok_con_ciclos_continuos_y_oci_en_espera(tmp_path):
    snap = tmp_path / "s.json"; snap.write_text(json.dumps({"observed_at": "2026-11-23T10:11:00Z", "clouds": {"aws": {"estado": "ERROR", "origen": "cloud_verificado"}, "oci": {"estado": "ADVERTENCIA", "origen": "cloud_verificado"}, "azure": {"estado": "OK", "origen": "local"}}}))
    rc, r = colector(tmp_path, hist(tmp_path), snap); assert rc == 0 and r["ok"] and r["ciclos"] == 12 and r["tres_nubes_con_origen"] and r["hueco_max_s"] == 60


@pytest.mark.parametrize("kw", [{"n": 5}, {"paso": 300}, {"hueco_en": 6}, {"oci": "OK"}, {"sondas": False}])
def test_colector_falla_con_pocos_ciclos_huecos_oci_ok_o_sin_sondas(tmp_path, kw):
    rc, r = colector(tmp_path, hist(tmp_path, **kw)); assert rc == 1 and not r["ok"]


def test_tres_nubes_exige_origen_y_hora(tmp_path):
    snap = tmp_path / "s.json"; snap.write_text(json.dumps({"observed_at": "2026-11-23T10:11:00Z", "clouds": {"aws": {"estado": "No verificado", "origen": "sin_datos"}, "oci": {"estado": "OK", "origen": "cloud_verificado"}, "azure": {"estado": "OK", "origen": "local"}}}))
    assert colector(tmp_path, hist(tmp_path), snap)[1]["tres_nubes_con_origen"] is False


def test_correo_sin_confirmacion_humana_completa_no_cuenta(tmp_path):
    d = medidas(tmp_path, correo={"ok": True, "confirmado_por": "", "asunto": "x", "hora_recepcion_utc": "2026-11-23T10:00:00Z"})
    assert T4.main(["evidencia", "--medidas", str(d), "--evidence-root", str(tmp_path / "ev")]) == 1
    assert T4.main(["correo", "--out", str(tmp_path / "c.json")]) == 1 and json.loads((tmp_path / "c.json").read_text())["ok"] is False
    assert T4.main(["correo", "--confirmado-por", "propietaria", "--asunto", "Fired: alerta-nexo-sonda", "--hora-recepcion-utc", "2026-11-23T10:05:00Z", "--out", str(tmp_path / "c2.json")]) == 0


def test_alerta_real_exige_problema_del_host_de_prueba_y_publicacion_posterior(tmp_path):
    pr = tmp_path / "p.json"; log = tmp_path / "l.log"; t = int(datetime(2026, 11, 23, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    pr.write_text(json.dumps([{"name": "NexoEventos no disponible: /healthz falla en sonda-t4.invalid", "clock": str(t)}]))
    log.write_text(json.dumps({"utc": "2026-11-23T10:01:30Z", "accion": "publicada"}) + "\n")
    out = tmp_path / "a.json"; assert T4.main(["alerta", "--problemas", str(pr), "--log", str(log), "--out", str(out)]) == 0 and json.loads(out.read_text())["t_publicada_utc"] == "2026-11-23T10:01:30Z"
    log.write_text(json.dumps({"utc": "2026-11-23T09:00:00Z", "accion": "publicada"}) + "\n")                  # publicación ANTERIOR al problema no vale
    assert T4.main(["alerta", "--problemas", str(pr), "--log", str(log), "--out", str(out)]) == 1
    pr.write_text("[]"); assert T4.main(["alerta", "--problemas", str(pr), "--log", str(log), "--out", str(out)]) == 1


def test_costos_estima_y_el_umbral_lo_aplica_la_evidencia(tmp_path):
    out = tmp_path / "c.json"; assert T4.main(["costos", "--horas", "3", "--snapshot-gb-usados", "5", "--snapshot-dias", "10", "--out", str(out)]) == 0
    assert abs(json.loads(out.read_text())["usd"] - (3 * 0.108 + 5 * 0.05 * 10 / 30)) < 1e-3
