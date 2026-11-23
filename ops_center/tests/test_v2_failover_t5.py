"""T5 (2.º intento) — correcciones locales con regresión: tipos de fallo (controlado vs abrupto), marcas UTC absolutas y evidencia de relojes. Sin nube."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import t5_relojes as RL  # noqa: E402

spec = importlib.util.spec_from_file_location("v2ft", ROOT / "scripts/cloud/v2-failover-test.py"); FT = importlib.util.module_from_spec(spec); spec.loader.exec_module(FT)


def test_events_utc_convierte_marcas_relativas_a_utc_con_ms():
    ev = {"stop_issued_at": 28.8, "alb_marked_unhealthy_at": 53.7, "both_healthy_again_at": None, "otro": 1}
    u = FT.events_utc(ev, 1795400000.250)
    assert u["stop_issued_at"] == FT.iso_ms(1795400000.250 + 28.8) and u["alb_marked_unhealthy_at"] == FT.iso_ms(1795400000.250 + 53.7)
    assert "both_healthy_again_at" not in u and "otro" not in u and u["stop_issued_at"].endswith("Z") and len(u["stop_issued_at"]) == 24


def test_el_fallo_por_defecto_es_la_detencion_controlada_y_el_abrupto_exige_reemplazo():
    src = (ROOT / "scripts/cloud/v2-failover-test.py").read_text()
    assert 'default="stop"' in src and FT.FAULTS == ("stop", "instance") and "exige --allow-replacement" in src


def test_inject_fault_usa_la_orden_correcta_en_cada_tipo(monkeypatch):
    calls = []
    class FakeM:
        @staticmethod
        def ssm_output(v, cmd): calls.append(("ssm", v, cmd)); return ""
        @staticmethod
        def aws(*a): calls.append(("aws", a)); return {}
    monkeypatch.setattr(FT, "M", FakeM)
    FT.inject_fault("stop", "i-1"); FT.inject_fault("instance", "i-2")
    assert calls[0] == ("ssm", "i-1", "systemctl stop nexoeventos-api") and calls[1] == ("aws", ("ec2", "stop-instances", "--instance-ids", "i-2"))
    with pytest.raises(ValueError): FT.inject_fault("otro", "i-3")


def test_el_resultado_conserva_el_denominador_y_no_excluye_errores():
    src = (ROOT / "scripts/cloud/v2-failover-test.py").read_text()
    assert 'requests_log.append' in src and '"availability_pct": round(100 * len(ok_lat) / max(1, len(requests_log)), 2)' in src      # todas las solicitudes cuentan; los 502/timeouts/-1 son fallos
    assert "except httpx.HTTPError:" in src and "code = -1" in src


def test_formulas_ntp_y_cristian():
    r = RL.offset_from(100.0, 100.6, 100.7, 101.0)          # el cliente va 0,15 s detrás del servidor? t0=100,t1=100.6,t2=100.7,t3=101.0
    assert r["rtt_s"] == pytest.approx(0.9) and r["offset_s"] == pytest.approx(-0.15)
    c = RL.cristian(10.0, 10.5, 11.0); assert c["offset_s"] == pytest.approx(0.0) and c["error_max_s"] == pytest.approx(0.5)
    c2 = RL.cristian(10.0, 12.1, 10.2); assert c2["offset_s"] == pytest.approx(2.0) and c2["rtt_s"] == pytest.approx(0.2)


def test_relojes_fallan_si_el_desfase_supera_el_maximo(tmp_path, monkeypatch):
    monkeypatch.setattr(RL, "sntp_offset", lambda s, **k: {"offset_s": 0.02, "rtt_s": 0.03})
    out = tmp_path / "r.json"; assert RL.main(["--out", str(out)]) == 0 and json.loads(out.read_text())["ok"]
    monkeypatch.setattr(RL, "sntp_offset", lambda s, **k: {"offset_s": 3.5, "rtt_s": 0.03}); assert RL.main(["--out", str(out)]) == 1
    monkeypatch.setattr(RL, "sntp_offset", lambda s, **k: (_ for _ in ()).throw(OSError("sin red"))); assert RL.main(["--out", str(out)]) == 1 and json.loads(out.read_text())["mac_vs_ntp"]["error"] == "OSError"


# ---- variante C: la prueba y el orquestador ya no suponen «2 instancias» ----
import os
import subprocess


def chain(tmp, scenario, n=None, ops=None):
    from datetime import datetime, timedelta, timezone
    na = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%MZ"); cu = (datetime.now(timezone.utc) + timedelta(minutes=170)).strftime("%Y-%m-%dT%H:%MZ")
    env = {**os.environ, "NEXO_ALLOW_CLOUD_CHANGES": "YES", "NEXO_OPS_DIR": str(ops or tmp / "ops"), "AWS_BIN": "/usr/bin/false", "AWS_PROFILE": "x", **({"NEXO_EXPECTED_TARGETS": str(n)} if n else {})}
    return subprocess.run(["bash", str(ROOT / "scripts/v2-ops/rds-window.sh"), "chain", "--minutes", "90", "--scenario", scenario, "--confirm", "ENCENDER RDS Y APLICAR V2", "--not-after", na, "--creds-until", cu],
                          capture_output=True, text=True, env=env, timeout=60)


def test_el_orquestador_exige_el_numero_de_destinos_coherente_con_el_plan_revisado(tmp_path):
    for sc, n in (("t5c", None), ("t5c", 2), ("t5c", 3), ("t5b", None), ("t5b", 6), ("t5c", 99), ("t5c", "x")):
        r = chain(tmp_path, sc, n); assert r.returncode == 2, (sc, n, r.stdout, r.stderr)
    assert "exige NEXO_EXPECTED_TARGETS=6" in chain(tmp_path, "t5c", 2).stderr


def test_los_escenarios_t5_exigen_una_limpieza_verificada_antes_de_encender(tmp_path):
    ops = tmp_path / "ops"; ops.mkdir()
    for sc, n in (("t5b", 3), ("t5c", 6)):
        r = chain(tmp_path, sc, n, ops); assert r.returncode == 1 and "PARADA_VERIFICADA" in (r.stdout + r.stderr), (sc, r.stdout, r.stderr)        # sin estado verificado: BLOQUEADO antes de tocar AWS


def test_el_generador_usa_el_numero_de_instancias_en_precondicion_aborto_y_recuperacion():
    s = (ROOT / "scripts/cloud/v2-failover-test.py").read_text()
    assert "len(health0) == args.instances" in s and "len(asg_state) != args.instances" in s and 'len(last["alb"]) == args.instances' in s and '"expected_instances": args.instances' in s
    assert "ap.add_argument(\"--instances\", type=int, default=2" in s and "len(health0) == 2" not in s and 'len(last["alb"]) == 2' not in s
    # la metodología del tráfico NO cambió: mismo ritmo por defecto, mismas rutas al azar y mismo denominador
    assert 'ap.add_argument("--rate", type=float, default=5.0)' in s and 'rng.choice(["/api/events", "/healthz"])' in s and "time.sleep(25)" in s and "time.sleep(15)" in s


def test_previas_parametriza_el_numero_de_instancias_y_no_modifica_nada():
    s = (ROOT / "scripts/ops/t5_previas.py").read_text()
    assert "--instances" in s and "NINST" in s and "len(th) == NINST" in s and 'MinSize"] == NINST' in s
    for prohibido in ("terminate", "stop-instances", "create-", "delete-", "modify-", "update-auto-scaling", "put-", "apply"): assert prohibido not in s        # solo lecturas y GET al ALB
