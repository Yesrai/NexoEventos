"""T5 — sonda rápida: muestras de 5 s con marca UTC en ms, TLS verificado, fallos registrados (nunca omitidos), sin deriva y sin http remoto."""
import json
import os
from pathlib import Path

import pytest

from ops_center import collector as C, fastprobe as FP
from ops_center.tests.test_collector import server  # noqa: F401  (fixture: HTTPS local con certificado fijado)


def test_muestra_con_ms_y_tls_fijado(server, tmp_path):
    s = FP.sample(server["base"], "/livez", cafile=server["cafile"]); assert s["code"] == 200 and s["t"].endswith("Z") and len(s["t"]) == 24 and "." in s["t"]


def test_run_escribe_una_linea_por_muestra_0600_y_registra_los_fallos(server, tmp_path):
    out = tmp_path / "s" / "fast.jsonl"; ticks = []
    def sleeper(x): ticks.append(x)
    server["routes"]["/livez"] = (200, b"{}")
    n = FP.run(out, server["base"], cafile=server["cafile"], interval=1, timeout=0.5, duration=0.0001, sleep=sleeper); assert n == 1
    rows = [json.loads(l) for l in out.read_text().splitlines()]; assert len(rows) == 1 and rows[0]["code"] == 200 and oct(out.stat().st_mode)[-3:] == "600"
    server["routes"]["/livez"] = (502, b"{}"); FP.run(out, server["base"], cafile=server["cafile"], interval=1, timeout=0.5, duration=0.0001, sleep=sleeper)
    rows = [json.loads(l) for l in out.read_text().splitlines()]; assert [r["code"] for r in rows] == [200, 502] and rows[1]["error"] == "HTTP 502"


def test_sin_certificado_fijado_la_muestra_falla_y_se_registra(server, tmp_path):
    s = FP.sample(server["base"], "/livez"); assert s["code"] == 0 and s["error"]


def test_verify_as_y_no_http_remoto(server):
    base_ip = server["base"].replace("localhost", "127.0.0.1")
    assert FP.sample(base_ip, "/livez", cafile=server["cafile"], verify_as="localhost")["code"] == 200
    assert FP.sample("http://example.com", "/livez")["error"] == "solo https"


def test_programacion_sin_deriva_y_resincronizacion():
    reloj = {"t": 1000.0}; esperas = []
    def clock(): return reloj["t"]
    def sleeper(x): esperas.append(round(x, 3)); reloj["t"] += x
    def fetch(base, path, **k):
        reloj["t"] += 0.4; return {"path": path, "code": 200, "ms": 400}      # cada sonda tarda 0,4 s
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        n = FP.run(Path(d) / "f.jsonl", "https://x", interval=5, timeout=3, duration=21, fetch=fetch, sleep=sleeper, clock=clock)
    assert n == 5 and all(abs(e - 4.6) < 0.01 for e in esperas[:3])           # espera = intervalo − duración: no se acumula deriva


def test_parametros_invalidos(tmp_path):
    for kw in ({"interval": 0.5}, {"interval": 11}, {"interval": 5, "timeout": 5}):
        with pytest.raises(ValueError): FP.run(tmp_path / "f", "https://x", **kw)


def test_cli_fastprobe_con_destinos(server, tmp_path):
    from ops_center.cli import main
    import io
    t = tmp_path / "t.json"; t.write_text(json.dumps({"aws": {"base": server["base"].replace("localhost", "127.0.0.1"), "verify_as": "localhost", "cafile": server["cafile"]}})); out = io.StringIO()
    rc = main(["fastprobe", "--targets", str(t), "--duration", "0.001", "--interval", "2", "--timeout", "1", "--out", str(tmp_path / "f.jsonl")], env={"OPS_CENTER_STATE_DIR": str(tmp_path / "st"), "OPS_CENTER_IDENTITIES_FILE": str(tmp_path / "x.json")}, out=out)
    assert rc == 0 and json.loads(out.getvalue())["muestras"] == 1 and json.loads((tmp_path / "f.jsonl").read_text().splitlines()[0])["code"] == 200
    t.write_text(json.dumps({"aws": {}})); assert main(["fastprobe", "--targets", str(t)], env={"OPS_CENTER_STATE_DIR": str(tmp_path / "st")}, out=io.StringIO()) == 2


def test_la_unidad_no_se_habilita_de_forma_permanente():
    root = Path(__file__).resolve().parents[2]; u = (root / "deploy/ops-center/ops-fastprobe.service").read_text(); i = (root / "deploy/azure/instalar-t4-en-vm.sh").read_text()
    assert "[Install]" not in u and "--interval 5" in u and "ProtectSystem=strict" in u and "ops-fastprobe.service" in i and "enable --now ops-fastprobe" not in i


def test_rafaga_una_muestra_son_k_solicitudes_simultaneas_y_cuenta_los_fallos():
    import threading
    visto = []; lock = threading.Lock()
    def fetch(base, path, **k):
        with lock: visto.append(len(visto)); n = len(visto)
        return {"path": path, "code": 502 if n == 3 else 200, "ms": 10 * n, "error": "HTTP 502"} if n == 3 else {"path": path, "code": 200, "ms": 10 * n}
    s = FP.sample("https://x", "/livez", fetch=fetch, burst=6)
    assert s["burst"] == 6 and s["fallos"] == 1 and s["code"] == 502 and s["codes"] == [200, 200, 200, 200, 200, 502] and s["ms"] == 60 and s["error"] == "HTTP 502" and len(visto) == 6
    ok = FP.sample("https://x", "/livez", fetch=lambda b, p, **k: {"path": p, "code": 200, "ms": 5}, burst=3); assert ok["code"] == 200 and ok["fallos"] == 0
    assert "burst" not in FP.sample("https://x", "/livez", fetch=lambda b, p, **k: {"path": p, "code": 200, "ms": 5})            # sin ráfaga, formato idéntico al anterior


def test_rafaga_invalida_y_unidad_con_rafaga_igual_al_numero_de_instancias(tmp_path):
    for b in (0, 11):
        with pytest.raises(ValueError): FP.run(tmp_path / "f", "https://x", burst=b)
    u = (Path(__file__).resolve().parents[2] / "deploy/ops-center/ops-fastprobe.service").read_text(); assert "--burst 6" in u


def test_la_probabilidad_de_capturar_un_incidente_sube_con_la_rafaga():
    """Cálculo, no medición: con N=6 y ≈ 2 muestras dentro de un incidente de ≈ 10 s, 1 solicitud/muestra captura ≈ 31 %; una ráfaga de 6, ≈ 89 %."""
    p1 = 1 - (1 - 1 / 6) ** 2; p6 = 1 - (1 - (1 - (5 / 6) ** 6)) ** 2
    assert round(p1, 2) == 0.31 and round(p6, 2) == 0.89
