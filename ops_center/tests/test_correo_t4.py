"""T4 — correo real vía Azure Monitor (sin SMTP ni secretos): script de Zabbix con IMDS simulado, canal aditivo en Zabbix y lado Azure con `az` simulado."""
import http.server
import importlib.util
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ALERT = ROOT / "deploy/azure/nexo-alert-azure.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


@pytest.fixture
def servers():
    seen = []
    class H(http.server.BaseHTTPRequestHandler):
        def _j(self, code, o): b = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            seen.append(("GET", self.path, dict(self.headers)))
            if "instance" in self.path: return self._j(200, {"compute": {"location": "centralus", "subscriptionId": "sub-1", "resourceGroupName": "rg-x", "name": "vm-x"}})
            return self._j(200, {"access_token": "TOKEN-SECRETO-123"})
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0)); seen.append(("POST", self.path, dict(self.headers), json.loads(self.rfile.read(n)))); self._j(200, {})
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", seen
    srv.shutdown()


def run_alert(tmp, url, *args, extra=None):
    env = {**os.environ, "NEXO_IMDS_URL": url, "NEXO_METRICS_BASE": url, "NEXO_ALLOW_HTTP": "1", "NEXO_ALERT_LOG": str(tmp / "alert.log"), **(extra or {})}
    return subprocess.run(["python3", str(ALERT), *args], capture_output=True, text=True, env=env)


def test_problema_publica_la_metrica_con_identidad_administrada_y_sin_secretos_en_el_log(servers, tmp_path):
    url, seen = servers
    p = run_alert(tmp_path, url, "azure-monitor", "PROBLEMA: sonda falla", "detalle", "t4-sonda-prueba", "1"); assert p.returncode == 0, p.stderr
    post = [s for s in seen if s[0] == "POST"][0]
    assert post[1] == "/subscriptions/sub-1/resourceGroups/rg-x/providers/Microsoft.Compute/virtualMachines/vm-x/metrics" and post[2]["Authorization"] == "Bearer TOKEN-SECRETO-123"
    b = post[3]["data"]["baseData"]; assert b["namespace"] == "NexoEventos" and b["metric"] == "sondas_fallidas" and b["series"][0]["dimValues"][0] == "t4-sonda-prueba" and b["series"][0]["count"] == 1
    assert all(s[2].get("Metadata") == "true" for s in seen if s[0] == "GET")
    log = (tmp_path / "alert.log").read_text(); assert "publicada" in log and "TOKEN-SECRETO" not in log and "TOKEN-SECRETO" not in p.stdout + p.stderr


def test_recuperacion_no_publica_y_solo_registra(servers, tmp_path):
    url, seen = servers; p = run_alert(tmp_path, url, "x", "RESUELTO: sonda", "m", "t4-sonda-prueba", "0")
    assert p.returncode == 0 and not [s for s in seen if s[0] == "POST"] and "sin_publicar" in (tmp_path / "alert.log").read_text()


def test_fallo_de_red_sale_con_error_y_lo_registra(tmp_path):
    p = run_alert(tmp_path, "http://127.0.0.1:1", "x", "PROBLEMA", "m", "h", "1"); assert p.returncode == 1 and "FALLO" in (tmp_path / "alert.log").read_text()


def test_destino_http_sin_permiso_de_pruebas_se_rechaza(servers, tmp_path):
    url, seen = servers; p = run_alert(tmp_path, url, "x", "PROBLEMA", "m", "h", "1", extra={"NEXO_ALLOW_HTTP": "0"}); assert p.returncode == 1 and not [s for s in seen if s[0] == "POST"]


def test_dimensiones_saneadas(servers, tmp_path):
    A = load(ALERT, "alert_mod"); b = A.build_body("h;rm -rf /\n" + "a" * 300, "<script>"); d = b["data"]["baseData"]["series"][0]["dimValues"]
    assert all(len(x) <= 100 for x in d) and ";" not in d[0] and "<" not in d[1]


# ---- Zabbix aditivo ----
Z = load(ROOT / "scripts/observability/zabbix_t4_correo.py", "z4c")


class FakeZ:
    state = {}
    def __init__(self, url, insecure_tls=False): pass
    def login(self, u, p): pass
    def call(self, m, p=None, auth=True):
        S = FakeZ.state; S.setdefault("calls", []).append(m)
        kind = m.split(".")[0]
        if m.endswith(".get"):
            if kind == "hostgroup": return [{"groupid": "1"}, {"groupid": "2"}]
            if kind == "role": return [{"roleid": "1"}]
            f = (p or {}).get("filter") or {}; key = list(f.values())[0][0] if f else None
            return [S[kind][key]] if key in S.get(kind, {}) else []
        if m.endswith(".create"):
            nm = p.get("name") or p.get("username"); S.setdefault(kind, {})[nm] = {"mediatypeid": "m1", "usrgrpid": "g1", "userid": "u1", "actionid": "a1"}; S.setdefault("creados", []).append((kind, p)); return {k: ["1"] for k in ("mediatypeids", "usrgrpids", "userids", "actionids")}
        if m.endswith(".delete"):
            S.setdefault("borrados", []).append(kind); [S[kind].clear()] if kind in S else None; return {}
        raise AssertionError(m)


def zrun(tmp, *args):
    pw = tmp / "pw"; pw.write_text("x"); import contextlib, io
    b = io.StringIO()
    with contextlib.redirect_stdout(b): rc = Z.main(["--url", "https://x", "--admin-password-file", str(pw), *args], zabbix_cls=FakeZ)
    return rc, b.getvalue()


def test_zabbix_plan_no_crea_apply_crea_cuatro_objetos_e_idempotente(tmp_path):
    FakeZ.state = {}; rc, out = zrun(tmp_path); assert "plan" in out and not FakeZ.state.get("creados")
    zrun(tmp_path, "--apply"); k = [c[0] for c in FakeZ.state["creados"]]; assert k == ["mediatype", "usergroup", "user", "action"]
    n = len(FakeZ.state["creados"]); rc, out = zrun(tmp_path, "--apply"); assert len(FakeZ.state["creados"]) == n and "ya existe" in out
    mt = FakeZ.state["creados"][0][1]; assert mt["exec_path"] == "nexo-alert-azure.py" and "{EVENT.VALUE}" in mt["parameters"][4]["value"]
    ug = FakeZ.state["creados"][1][1]; assert ug["gui_access"] == 3 and all(r["permission"] == 2 for r in ug["hostgroup_rights"])        # solo lectura
    usr = FakeZ.state["creados"][2][1]; assert len(usr["passwd"]) == 48 and usr["medias"][0]["sendto"] == ["azure-monitor"]


def test_zabbix_no_toca_lo_existente_y_retirar_borra_solo_lo_propio(tmp_path):
    FakeZ.state = {}; zrun(tmp_path, "--apply"); zrun(tmp_path, "--retirar"); assert FakeZ.state["borrados"] == ["action", "user", "usergroup", "mediatype"]
    s = (ROOT / "scripts/observability/zabbix_t4_correo.py").read_text().split('"""', 2)[2]      # sin el docstring que describe lo que NO se toca
    for prohibido in ("user.update", "action.update", "mediatype.update", "Registro local", '"Admin"], "medias"', "configuration.import", "template."): assert prohibido not in s


# ---- lado Azure con az simulado ----
def fake_az(tmp):
    log = tmp / "az.log"; log.write_text("")
    az = tmp / "az"; az.write_text(f'''#!/usr/bin/env bash
echo "$*" >> "{log}"
case "$*" in
 *"vm show"*"principalId"*) echo "pid-123";;
 *"vm show"*"query id"*) echo "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm";;
 *"role assignment list"*) echo 1;;
 *"alert list"*) echo 0;;
esac
'''); az.chmod(0o755); return az, log


def azrun(tmp, *args):
    az, log = fake_az(tmp) if not (tmp / "az").exists() else (tmp / "az", tmp / "az.log")
    return subprocess.run(["bash", str(ROOT / "scripts/observability/azure-t4-correo.sh"), *args], capture_output=True, text=True, env={**os.environ, "AZ_BIN": str(az)}), log


def test_azure_correo_plan_no_cambia_y_exige_frase(tmp_path):
    for a in (["--rol"], ["--regla"], ["--retirar"], ["--rol", "--aplicar", "otra"]):
        p, log = azrun(tmp_path, *a); assert p.returncode == 0 and "Modo plan" in p.stdout
    t = log.read_text(); assert "role assignment create" not in t and "alert create" not in t and "alert delete" not in t


def test_azure_correo_aplica_rol_acotado_a_la_vm_y_regla_al_grupo_existente(tmp_path):
    p, log = azrun(tmp_path, "--rol", "--aplicar", "CONFIGURAR CORREO T4"); assert p.returncode == 0
    p, log = azrun(tmp_path, "--regla", "--aplicar", "CONFIGURAR CORREO T4"); t = log.read_text()
    assert "--role Monitoring Metrics Publisher --scope /subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm" in t and "--assignee-object-id pid-123" in t
    assert "total NexoEventos.sondas_fallidas > 0" in t and "--action ag-nexoeventos-obs" in t and "--tags t4=temporal" in t and "action-group create" not in t


def test_azure_correo_retirar_revierte_y_check_es_solo_lectura(tmp_path):
    p, log = azrun(tmp_path, "--retirar", "--aplicar", "RETIRAR CORREO T4"); t = log.read_text(); assert "alert delete -n alerta-nexo-sonda" in t and "role assignment delete" in t
    t2 = tmp_path / "solo-check"; t2.mkdir(); p, log = azrun(t2, "--check"); t = log.read_text()
    assert "rol_asignado=1" in p.stdout and not any(w in t for w in (" create", " delete", " update"))
