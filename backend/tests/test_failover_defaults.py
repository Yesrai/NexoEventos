"""Garantías de «cero cambios por defecto» de B-10…B-13: nada de producción activa la compuerta ni el failover, y ningún mecanismo opera sin configuración explícita."""
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.failover.gate import build_gate_from_env
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ["deploy", "ansible", "infra", ".github", "scripts/v2", "scripts/v2-ops", "scripts/cloud", "scripts/rehearsal", "docs/operacion"]
SCAN_FILES = ["backend/.env.example", "backend/Dockerfile", "docker-compose.yml"]
TEXT_SUFFIXES = {".sh", ".py", ".yml", ".yaml", ".tf", ".tfvars", ".tftpl", ".service", ".timer", ".conf", ".template", ".example", ".md", ".json", ".j2", ".env", ""}
FORBIDDEN = re.compile(r"WRITE_GATE_[A-Z_]+|failover/orchestrator|dns_switch\.py|NEXO_ALLOW_FAILOVER_EXECUTE|NEXO_ALLOW_DNS_CHANGE")


def test_ningun_despliegue_ni_configuracion_activa_la_compuerta_ni_el_failover():
    hits = []
    paths = [ROOT / f for f in SCAN_FILES if (ROOT / f).exists()]
    for d in SCAN_DIRS:
        base = ROOT / d
        if base.exists():
            paths += [p for p in base.rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES and ".terraform" not in p.parts and "node_modules" not in p.parts]
    for p in paths:
        try:
            text = p.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for m in FORBIDDEN.finditer(text):
            hits.append(f"{p.relative_to(ROOT)}: {m.group(0)}")
    assert not hits, "una configuración de despliegue referencia la compuerta/failover: " + "; ".join(hits[:5])


def test_sin_variables_la_compuerta_esta_apagada_y_no_hay_ruta_ni_estado(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("WRITE_GATE_"):
            monkeypatch.delenv(k)
    assert build_gate_from_env() is None
    app = create_app()
    assert not hasattr(app.state, "write_gate")
    assert TestClient(app).get("/write-gate").status_code == 404
    assert not any(getattr(r, "path", "") == "/write-gate" for r in app.routes)


def test_modo_off_explicito_equivale_a_apagado(monkeypatch):
    monkeypatch.setenv("WRITE_GATE_MODE", "off")
    assert build_gate_from_env() is None


def test_valor_invalido_de_modo_impide_arrancar_en_lugar_de_degradar_en_silencio(monkeypatch):
    monkeypatch.setenv("WRITE_GATE_MODE", "ENFORCED")
    with pytest.raises(RuntimeError):
        create_app()


def test_el_modulo_de_failover_no_inicia_hilos_ni_red_al_importarse():
    code = ("import threading, socket, sys\n"
            "n0 = threading.active_count()\n"
            "orig = socket.socket.connect\n"
            "def boom(*a, **k): raise SystemExit('conexion de red durante la importacion')\n"
            "socket.socket.connect = boom\n"
            "import app.failover.store, app.failover.lease, app.failover.gate\n"
            "assert threading.active_count() == n0, 'se inició un hilo al importar'\n"
            "print('OK')\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT / "backend")
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


def test_el_orquestador_y_el_cambio_de_dns_se_niegan_sin_autorizacion_explicita():
    orch = ROOT / "scripts/multicloud/failover/orchestrator.py"
    env = {"PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(orch), "run", "--confirm", "EJECUTAR FAILOVER REAL"], capture_output=True, text=True, env=env)
    assert r.returncode == 2
    r = subprocess.run([sys.executable, str(ROOT / "scripts/multicloud/dns_switch.py"), "apply", "--config", "/no/existe.json", "--domain", "x", "--target", "oci", "--confirm", "x"], capture_output=True, text=True, env=env)
    assert r.returncode == 2
