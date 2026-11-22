"""Integración en entorno DESECHABLE: directorio temporal, servidor uvicorn real solo en 127.0.0.1 (puerto efímero), sin nube, sin base de datos."""
import io
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import uvicorn

from ops_center import cli
from ops_center.app import create_app
from ops_center.settings import Settings


def run_cli(args, env):
    buf = io.StringIO(); code = cli.main(args, env=env, out=buf); return code, buf.getvalue()


@pytest.fixture
def live(tmp_path):
    sd = tmp_path / "ops"; env = {"OPS_CENTER_STATE_DIR": str(sd), "OPS_CENTER_DEADLINE": "2099-01-01T00:00:00Z"}
    code, out = run_cli(["init-identities", "--dir", str(sd)], env); assert code == 0
    toks = dict(re.findall(r"^\s+([\w-]+): (\S+)$", out, re.M))
    assert oct(os.stat(sd / "identities.json").st_mode & 0o777) == "0o600" and "token_sha256" in (sd / "identities.json").read_text() and toks["ti-solicitante"] not in (sd / "identities.json").read_text()
    s = Settings.from_env(env)
    with socket.socket() as sk: sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(100):
        if srv.started: break
        time.sleep(0.05)
    yield {"base": f"http://127.0.0.1:{port}", "toks": toks, "env": env, "settings": s}
    srv.should_exit = True; th.join(5)


def call(live, who, method, path, body=None):
    req = urllib.request.Request(live["base"] + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + live["toks"][who], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_flujo_completo_por_http_real_con_auditoria_y_ejecucion_denegada(live, tmp_path):
    assert call(live, "ti-lectura", "GET", "/api/ops/overview")[0] == 200
    st, r = call(live, "ti-solicitante", "POST", "/api/ops/recovery-requests", {"tipo": "failover_aws_a_oci", "reason": "Solicitud de prueba de failover real controlado"})
    assert st == 201 and r["state"] == "RECHAZADA_VALIDACION"          # sin evidencias T1–T4 ni configuración: bloqueado
    assert call(live, "propietaria-aprobador", "POST", f"/api/ops/recovery-requests/{r['id']}/approve", {})[0] == 409
    code, out = run_cli(["check", "failover_aws_a_oci"], live["env"]); assert code == 1 and "BLOQUEA B06_T1" in out and "BLOQUEA B11_adaptadores_reales_cableados" in out
    code, out = run_cli(["evidence-start", "T1", "--root", str(tmp_path / "ev")], live["env"]); assert code == 0; run = out.strip()
    for c in json.loads((Path(cli.__file__).parent / "criterios" / "T1.json").read_text())["criteria"]:
        v = "true" if c["kind"] == "bool" else str(c["threshold"])      # valores en el límite: cumplen (min ≥, max ≤)
        assert run_cli(["evidence-value", run, c["id"], v], live["env"])[0] == 0
    assert run_cli(["evidence-finish", run], live["env"])[0] == 0
    rep = Path(run) / "resultado.json"
    assert run_cli(["record-evidence", "T1", "--report", str(rep), "--result", "PASS"], live["env"])[0] == 0
    code, out = run_cli(["check", "failover_aws_a_oci"], live["env"]); assert "PASA    B06_T1" in out and "BLOQUEA B06_T2" in out
    code, out = run_cli(["execute", r["id"]], live["env"]); assert code == 3 and "DENEGADO" in out
    assert run_cli(["kill-switch", "on"], live["env"])[0] == 0
    st, r2 = call(live, "ti-solicitante", "POST", "/api/ops/recovery-requests", {"tipo": "restaurar_respaldo_en_oci", "reason": "Restaurar el respaldo en la VM de OCI de pruebas"})
    assert r2["state"] == "RECHAZADA_VALIDACION" and any(b["id"] == "B01_kill_switch" and not b["ok"] for b in r2["validation"]["barriers"])
    assert run_cli(["kill-switch", "off"], live["env"])[0] == 0
    st, a = call(live, "ti-lectura", "GET", "/api/ops/audit")
    ev = [e["event"] for e in a["entradas"]]
    assert a["verificacion"]["ok"] and {"solicitada", "rechazada_validacion", "evidencia_registrada", "ejecucion_denegada", "kill_switch_on", "kill_switch_off"} <= set(ev)
    assert run_cli(["verify-audit"], live["env"])[0] == 0


def test_manipular_la_auditoria_se_detecta(live):
    call(live, "ti-solicitante", "POST", "/api/ops/recovery-requests", {"tipo": "restaurar_respaldo_en_oci", "reason": "Restaurar el respaldo en la VM de OCI de pruebas"})
    p = live["settings"].state_dir / "audit.jsonl"; lines = p.read_text().splitlines(); e = json.loads(lines[0]); e["actor"] = "falso"; lines[0] = json.dumps(e); p.write_text("\n".join(lines) + "\n")
    assert run_cli(["verify-audit"], live["env"])[0] == 1 and call(live, "ti-lectura", "GET", "/api/ops/audit")[1]["verificacion"]["ok"] is False


def test_init_identities_no_sobrescribe(live):
    code, out = run_cli(["init-identities", "--dir", str(live["settings"].state_dir)], live["env"]); assert code == 2 and "no se sobrescribe" in out
