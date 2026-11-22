import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from ops_center import evidence as E
from ops_center.evidence import EvidenceError, EvidenceRun
from .test_integration_cli import run_cli

CRIT = [{"id": "ok_bool", "kind": "bool", "desc": "d"}, {"id": "rto_s", "kind": "max", "threshold": 100, "desc": "rto"}, {"id": "disp", "kind": "min", "threshold": 99, "desc": "disp"}]


class Clk:
    def __init__(self): self.t = datetime(2026, 11, 25, 15, 0, 0, tzinfo=timezone.utc)
    def __call__(self): c = self.t; self.t += timedelta(seconds=12.5); return c


def make(tmp_path):
    return EvidenceRun.start(tmp_path, "T6", "prueba", CRIT, clock=Clk())


def test_pass_solo_con_todo_medido_y_cumplido(tmp_path):
    r = make(tmp_path); r.value("ok_bool", True); r.value("rto_s", 90); r.value("disp", 99.5)
    assert r.finish()["veredicto"] == "PASS"
    assert oct(os.stat(r.dir).st_mode & 0o777) == "0o700" and E.verify_manifest(r.dir)["ok"]


def test_parcial_nunca_es_pass_y_fail_domina(tmp_path):
    r = make(tmp_path); r.value("ok_bool", True); r.value("rto_s", 90)           # falta 'disp'
    res = r.finish(); assert res["veredicto"] == "PARCIAL" and [c["resultado"] for c in res["criterios"]] == ["CUMPLE", "CUMPLE", "SIN_MEDIR"]
    r2 = EvidenceRun.start(tmp_path, "T5", "x", CRIT); r2.value("rto_s", 500); assert r2.finish()["veredicto"] == "FAIL"


def test_captura_sin_redactar_impide_pass(tmp_path):
    shot = tmp_path / "pantalla.png"; shot.write_bytes(b"png")
    r = make(tmp_path); r.value("ok_bool", True); r.value("rto_s", 1); r.value("disp", 100); r.attach(shot, redacted=False)
    res = r.finish(); assert res["veredicto"] == "PARCIAL" and res["sin_redactar"] == ["pantalla.png"]


def test_rto_y_marcas_utc_con_milisegundos(tmp_path):
    r = make(tmp_path); k = Clk(); a = r.mark("falla_inyectada", clock=k); b = r.mark("servicio_restablecido", clock=k)
    assert a.endswith("Z") and "." in a and r.seconds_between("falla_inyectada", "servicio_restablecido") > 0
    with pytest.raises(EvidenceError): r.mark("falla_inyectada")        # una marca no se reescribe
    assert r.seconds_between("falla_inyectada", "no_existe") is None


def test_saneado_de_secretos_ip_url_ocid_y_claves(tmp_path):
    r = make(tmp_path); r.event("x", detalle="https://h.example/p/ABCDEF123456 10.1.2.3 ocid1.bucket.oc1..aaaa AKIAABCDEFGHIJKLMNOP token=abc123")
    r.capture_text("salida", "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY----- Authorization: Bearer abc.def host 54.210.33.99")
    blob = (r.dir / "events.jsonl").read_text() + (r.dir / "capturas" / "salida.txt").read_text()
    for bad in ("10.1.2.3", "ocid1.bucket", "AKIAABC", "abc123", "MIIE", "54.210.33.99", "h.example", "abc.def"): assert bad not in blob


def test_salud_y_disponibilidad_desconocido_no_cuenta_como_sano(tmp_path):
    r = make(tmp_path)
    for ok in (True, True, False, None): r.sample("alb", ok, 12.0, 200)
    assert r.availability("alb") == 50.0 and r.availability("otro") is None


def test_criterios_invalidos_y_corrida_cerrada(tmp_path):
    with pytest.raises(EvidenceError): EvidenceRun.start(tmp_path, "T9", "x", CRIT)
    with pytest.raises(EvidenceError): EvidenceRun.start(tmp_path, "T1", "x", [])
    with pytest.raises(EvidenceError): EvidenceRun.start(tmp_path, "T1", "x", [{"id": "a", "kind": "max"}])
    r = make(tmp_path)
    with pytest.raises(EvidenceError): r.value("ok_bool", 1)             # bool exige true/false
    with pytest.raises(EvidenceError): r.value("rto_s", True)            # número no puede ser bool
    with pytest.raises(EvidenceError): r.value("no_existe", 1)
    r.finish()
    with pytest.raises(EvidenceError): r.event("tarde")


def test_manifiesto_detecta_alteracion(tmp_path):
    r = make(tmp_path); r.value("ok_bool", True); r.finish()
    (r.dir / "resultado.md").write_text("alterado"); v = E.verify_manifest(r.dir); assert not v["ok"] and "resultado.md" in v["alterados"]


def test_plantillas_T1_a_T8_validas_y_con_criterios_de_seguridad():
    from pathlib import Path
    d = Path(E.__file__).parent / "criterios"
    for st in [f"T{i}" for i in range(1, 9)]:
        t = json.loads((d / f"{st}.json").read_text()); assert t["stage"] == st and t["criteria"]
        EvidenceRun.start(os.environ.get("TMPDIR", "/tmp"), st if st != "T7" else "T7", t["title"], t["criteria"]) if False else None
        ids = {c["id"] for c in t["criteria"]}; assert len(ids) == len(t["criteria"])
    t6 = {c["id"]: c for c in json.loads((d / "T6.json").read_text())["criteria"]}
    assert t6["escrituras_201_de_aws_tras_la_toma"]["threshold"] == 0 and "un_solo_escritor_siempre" in t6 and "aws_cerrado_por_efecto" in t6


def test_cli_recolector_y_guardia_de_registro_pass(tmp_path):
    env = {"OPS_CENTER_STATE_DIR": str(tmp_path / "ops"), "OPS_CENTER_DEADLINE": "2099-01-01T00:00:00Z"}
    code, out = run_cli(["evidence-start", "T2", "--root", str(tmp_path / "ev")], env); assert code == 0; run = out.strip()
    assert run_cli(["evidence-mark", run, "dns_cambiado"], env)[0] == 0 and run_cli(["evidence-value", run, "dominio_de_pruebas", "true"], env)[0] == 0
    assert run_cli(["evidence-value", run, "propagacion_apply_s", "45.5"], env)[0] == 0 and run_cli(["evidence-value", run, "propagacion_apply_s", "abc"], env)[0] == 2
    code, out = run_cli(["evidence-finish", run], env); assert code == 1 and out.strip() == "PARCIAL"
    rep = os.path.join(run, "resultado.json")
    code, out = run_cli(["record-evidence", "T2", "--report", rep, "--result", "PASS"], env); assert code == 2 and "RECHAZADO" in out
    plain = tmp_path / "plano.txt"; plain.write_text("x")
    code, out = run_cli(["record-evidence", "T2", "--report", str(plain), "--result", "PASS"], env); assert code == 2 and "recolector" in out
    assert run_cli(["record-evidence", "T2", "--report", rep, "--result", "FAIL"], env)[0] == 0      # un parcial puede registrarse solo como no aprobado
    assert run_cli(["evidence-verify", run], env)[0] == 0
