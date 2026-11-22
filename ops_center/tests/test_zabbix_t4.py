"""T4 — alta aditiva en Zabbix: no modifica lo existente, nace deshabilitado para T5/T6, la sonda de prueba se crea y se retira, sin --apply solo lee."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("z4", ROOT / "scripts/observability/zabbix_t4_additive.py"); Z4 = importlib.util.module_from_spec(spec); spec.loader.exec_module(Z4)


class Fake:
    def __init__(self, url, insecure_tls=False, hosts=None): self.calls = []; Fake.state = getattr(Fake, "state", {})
    def login(self, u, p): pass
    def call(self, m, p=None, auth=True):
        self.calls.append((m, p)); S = Fake.state
        if m == "host.get": return [S["hosts"][n] for n in (p.get("filter", {}).get("host") or []) if n in S["hosts"]]
        if m == "template.get": return [{"templateid": "9"}] if S.get("template", True) else []
        if m == "hostgroup.get": return [{"groupid": "5"}]
        if m == "host.create": S["hosts"][p["host"]] = {"hostid": str(len(S["hosts"]) + 100), "host": p["host"], "status": str(p["status"]), "macros": p["macros"]}; return {"hostids": ["1"]}
        if m == "host.update": S["hosts"].get([k for k, v in S["hosts"].items() if v["hostid"] == p["hostid"]][0]).update(status=str(p["status"]), macros=p["macros"]); return {}
        if m == "host.delete": [S["hosts"].pop(k) for k in [k for k, v in S["hosts"].items() if v["hostid"] == p[0]]]; return {}
        raise AssertionError(m)


def run(tmp, *args, hosts=None, template=True):
    Fake.state = {"hosts": dict(hosts or {}), "template": template}; pw = tmp / "pw"; pw.write_text("x")
    import io, contextlib
    b = io.StringIO()
    with contextlib.redirect_stdout(b): rc = Z4.main(["--url", "https://x", "--admin-password-file", str(pw), *args], zabbix_cls=Fake)
    return rc, b.getvalue()


def test_sin_apply_solo_lee(tmp_path):
    rc, out = run(tmp_path); assert rc == 0 and "plan (lectura)" in out and not any(m.endswith((".create", ".update", ".delete")) for m, _ in [] ) and "creado" not in out
    assert Fake.state["hosts"] == {}


def test_alta_crea_v2_y_oci_deshabilitados_y_la_sonda_de_prueba_habilitada(tmp_path):
    rc, out = run(tmp_path, "--apply"); H = Fake.state["hosts"]
    assert rc == 0 and H["aws-nexoeventos-v2"]["status"] == "1" and H["oci-nexoeventos-recovery"]["status"] == "1" and H["t4-sonda-prueba"]["status"] == "0"
    assert H["t4-sonda-prueba"]["macros"][0]["value"].endswith(".invalid")


def test_no_modifica_hosts_existentes(tmp_path):
    ex = {"aws-nexoeventos-v2": {"hostid": "7", "host": "aws-nexoeventos-v2", "status": "0", "macros": [{"macro": "{$NEXO.HOST}", "value": "ya-configurado.example"}]}}
    rc, out = run(tmp_path, "--apply", hosts=ex); assert Fake.state["hosts"]["aws-nexoeventos-v2"]["macros"][0]["value"] == "ya-configurado.example" and "ya existe: no se modifica" in out


def test_enable_solo_cambia_ese_host_y_valida_el_dns(tmp_path):
    run(tmp_path, "--apply"); st = Fake.state["hosts"]
    pw = tmp_path / "pw"; import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        assert Z4.main(["--url", "https://x", "--admin-password-file", str(pw), "--apply", "--enable", "aws", "--host", "alb-1.us-east-1.elb.amazonaws.com"], zabbix_cls=Fake) == 0
    assert st["aws-nexoeventos-v2"]["status"] == "0" and st["aws-nexoeventos-v2"]["macros"][0]["value"].startswith("alb-1") and st["oci-nexoeventos-recovery"]["status"] == "1"
    import pytest
    with pytest.raises(SystemExit): Z4.main(["--url", "https://x", "--admin-password-file", str(pw), "--enable", "oci", "--host", "x;rm -rf"], zabbix_cls=Fake)


def test_retirada_elimina_solo_la_sonda_de_prueba(tmp_path):
    run(tmp_path, "--apply"); pw = tmp_path / "pw"; import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()): assert Z4.main(["--url", "https://x", "--admin-password-file", str(pw), "--apply", "--remove-test"], zabbix_cls=Fake) == 0
    assert set(Fake.state["hosts"]) == {"aws-nexoeventos-v2", "oci-nexoeventos-recovery"}


def test_sin_plantilla_no_crea_nada(tmp_path):
    import pytest
    with pytest.raises(SystemExit): run(tmp_path, "--apply", template=False)
    assert Fake.state["hosts"] == {}


def test_el_script_no_usa_metodos_destructivos_sobre_plantillas_ni_usuarios():
    s = (ROOT / "scripts/observability/zabbix_t4_additive.py").read_text()
    for prohibido in ("template.create", "template.update", "template.delete", "user.", "usergroup", "mediatype", "action.", "configuration.import", "token."): assert prohibido not in s


def test_control_positivo_se_crea_y_la_retirada_lo_elimina_junto_con_la_sonda_de_prueba(tmp_path):
    import contextlib, io
    run(tmp_path, "--apply"); pw = tmp_path / "pw"
    with contextlib.redirect_stdout(io.StringIO()): assert Z4.main(["--url", "https://x", "--admin-password-file", str(pw), "--apply", "--control", "objectstorage.sa-saopaulo-1.oraclecloud.com"], zabbix_cls=Fake) == 0
    assert Fake.state["hosts"]["t4-control-positivo"]["macros"][0]["value"] == "objectstorage.sa-saopaulo-1.oraclecloud.com" and Fake.state["hosts"]["t4-control-positivo"]["status"] == "0"
    with contextlib.redirect_stdout(io.StringIO()): assert Z4.main(["--url", "https://x", "--admin-password-file", str(pw), "--apply", "--remove-test"], zabbix_cls=Fake) == 0
    assert set(Fake.state["hosts"]) == {"aws-nexoeventos-v2", "oci-nexoeventos-recovery"}
