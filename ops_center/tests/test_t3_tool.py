"""Herramienta de comprobación y evidencia de T3 (ejecutar_t3.py) con archivos sintéticos con la misma forma que la recuperación real del 19-nov (sin nube)."""
import json, socket, subprocess, sys, threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import ejecutar_t3 as T3  # noqa: E402

INV = {"instancias_no_terminadas": 0, "bastions_activos": 0, "vcn": 1, "subredes": 1, "internet_gateways": 0, "nsg": 1, "listas_de_seguridad": 1, "tablas_de_rutas": 1, "par_activos": 0, "objetos": 21, "utc": "x"}


def smoke(ok=True, tls=True, base="https://203.0.113.9", n_writes=5):
    res = [{"prueba": p, "ok": True} for p in ("livez", "ready", "healthz", "frontend", "api events", "detalle")] + [{"prueba": f"escritura rechazada: V{i} /x", "ok": ok} for i in range(n_writes)]
    return {"todo_ok": ok, "base": base, "tls_verificado": tls, "resultados": res}


def smoke_rw(ok=True, funcionales=7, extra_fail=None):
    base = ["livez", "ready", "healthz", "frontend servido", "inicio de sesión de cliente", "cookie de sesión con Secure y HttpOnly", "sesión válida", "catálogo", "detalle", "consulta de reservas",
            "tickets del cliente con QR descifrado (clave original)", "inicio de sesión de operador", "validación de un ticket ya usado → already_used (409)"]
    res = [{"prueba": n, "ok": True} for n in base] + [{"prueba": f"funcional: comprobación {i}", "ok": True} for i in range(funcionales)] + [{"prueba": f"extra {i}", "ok": True} for i in range(2)]
    for r in res:
        if extra_fail and r["prueba"].startswith(extra_fail): r["ok"] = False
    return {"todo_ok": all(r["ok"] for r in res) and ok, "tls_verificado": True, "base": "https://203.0.113.9", "resultados": res}


def build(tmp, **kw):
    d = tmp / "rec"; d.mkdir(); (d / "etapas.json").write_text(json.dumps(kw.get("etapas", {"resultado": "OK", "etapa_fallida": None, "total_s": 1500.0, "etapas": {"aprovisionamiento": 300, "datos": 200, "secretos": 2, "humo": 5}})))
    (d / "smoke.json").write_text(json.dumps(kw.get("smoke", smoke()))); (d / "claves-instaladas.txt").write_text("SHA256 TICKET=ab\n"); (d / "huella-delta.txt").write_text(kw.get("delta", ""))
    rw = tmp / "rw"; rw.mkdir(); (rw / "smoke.json").write_text(json.dumps(kw.get("smoke_rw", smoke_rw()))); (rw / "huella-delta.txt").write_text("access_logs=9 -> 11\n"); (rw / "stage2.txt").write_text("ok")
    files = {"plan.json": kw.get("plan", {"resultado": "LISTO"}), "i0.json": INV, "i1.json": kw.get("inv1", INV), "p.json": kw.get("puertos", {"ok": True}), "m.json": kw.get("mem", {"ok": True}), "m0.json": kw.get("mem0", {"ok": True}), "mi.json": kw.get("mem_i", {"ok": True}),
             "td.json": kw.get("td", {"resultado": "OK plan teardown-public dentro de la lista blanca"}), "vr.json": kw.get("verif", {"ok": True, "no_descifra": True}),
             "mk.json": kw.get("marcas", {"apply_inicio": "2026-11-23T10:00:00.000Z", "apply_fin": "2026-11-23T10:03:10.000Z", "recuperacion_inicio": "2026-11-23T10:05:00.000Z", "recuperacion_fin": "2026-11-23T10:30:00.000Z", "destruccion_inicio": "2026-11-23T10:40:00.000Z", "destruccion_fin": "2026-11-23T10:42:00.000Z"})}
    for n, c in files.items(): (tmp / n).write_text(json.dumps(c))
    return ["evidencia", "--recovery-dir", str(d), "--recovery-dir-rw", str(rw), "--evidence-root", str(tmp / "ev"), "--plan-json", str(tmp / "plan.json"), "--inv-antes", str(tmp / "i0.json"), "--inv-despues", str(tmp / "i1.json"),
            "--puertos", str(tmp / "p.json"), "--memoria", str(tmp / "m.json"), "--memoria-ro", str(tmp / "m0.json"), "--memoria-inicio", str(tmp / "mi.json"), "--teardown-guard", str(tmp / "td.json"), "--verif-respaldo", str(tmp / "vr.json"), "--marcas", str(tmp / "mk.json")]


def verdict(tmp):
    d = next((tmp / "ev").iterdir()); return json.loads((d / "resultado.json").read_text())


def test_todo_en_regla_da_pass(tmp_path):
    assert T3.main(build(tmp_path)) == 0; r = verdict(tmp_path); assert r["veredicto"] == "PASS", [c for c in r["criterios"] if c["resultado"] != "CUMPLE"]


@pytest.mark.parametrize("kw,criterio", [
    ({"smoke": smoke(ok=False)}, "smoke_solo_lectura_todo_ok"), ({"smoke": smoke(tls=False)}, "https_publico_con_certificado_fijado"), ({"smoke": smoke(base="https://localhost:8443")}, "https_publico_con_certificado_fijado"),
    ({"smoke": smoke(n_writes=2)}, "escrituras_rechazadas_403"), ({"delta": "access_logs=9 -> 10\n"}, "ninguna_escritura_huella_final_identica"), ({"puertos": {"ok": False}}, "solo_443_alcanzable_desde_fuera"),
    ({"mem": {"ok": False}}, "memoria_sin_oom"), ({"etapas": {"resultado": "FALLO", "etapa_fallida": "datos", "total_s": 100, "etapas": {}}}, "recuperacion_c04_sin_fallo"),
    ({"etapas": {"resultado": "OK", "etapa_fallida": None, "total_s": 4000.0, "etapas": {"datos": 1, "secretos": 1}}}, "rto_recuperacion_total_s"),
    ({"smoke_rw": smoke_rw(ok=False)}, "fase_escritura_humo_todo_ok"), ({"smoke_rw": smoke_rw(extra_fail="inicio de sesión de operador")}, "login_cliente_y_operador_ok"),
    ({"smoke_rw": smoke_rw(funcionales=6)}, "reservas_funcionales_ok"), ({"smoke_rw": smoke_rw(extra_fail="funcional: comprobación 3")}, "reservas_funcionales_ok"),
    ({"smoke_rw": smoke_rw(extra_fail="validación de un ticket ya usado")}, "qr_con_claves_originales_y_ticket_usado_409"), ({"verif": {"ok": False, "no_descifra": True}}, "respaldo_c04_integro"),
    ({"verif": {"ok": True, "no_descifra": False}}, "respaldo_c04_integro"), ({"mem0": {"ok": False}}, "memoria_sin_oom"), ({"mem_i": {"ok": False}}, "memoria_sin_oom"),
    ({"marcas": {"apply_inicio": "2026-11-23T10:00:00.000Z", "apply_fin": "2026-11-23T10:00:00.000Z", "recuperacion_inicio": "2026-11-23T10:05:00.000Z", "recuperacion_fin": "2026-11-23T10:30:00.000Z", "destruccion_inicio": "2026-11-23T10:40:00.000Z", "destruccion_fin": "2026-11-23T10:42:00.000Z"}}, "tiempos_de_reconstruccion_registrados"),
    ({"inv1": {**INV, "internet_gateways": 1}}, "inventario_final_igual_al_inicial"), ({"inv1": {**INV, "instancias_no_terminadas": 1}}, "recursos_destruidos_y_verificados"),
    ({"td": {"resultado": "PLAN RECHAZADO"}}, "recursos_destruidos_y_verificados"), ({"plan": {"resultado": "NO LISTO"}}, "lectura_previa_lista")])
def test_cada_desviacion_hace_fail(tmp_path, kw, criterio):
    assert T3.main(build(tmp_path, **kw)) == 1; r = verdict(tmp_path); assert r["veredicto"] == "FAIL" and any(c["id"] == criterio and c["resultado"] == "NO_CUMPLE" for c in r["criterios"]), criterio


def test_lo_que_falta_es_parcial_no_pass(tmp_path):
    args = build(tmp_path); i = args.index("--puertos"); del args[i:i + 2]            # sin la prueba de puertos
    assert T3.main(args) == 1; r = verdict(tmp_path); assert r["veredicto"] == "PARCIAL" and any(c["id"] == "solo_443_alcanzable_desde_fuera" and c["resultado"] == "SIN_MEDIR" for c in r["criterios"])


def test_puertos_443_abierto_y_el_resto_cerrado_es_ok_y_uno_abierto_es_fallo(tmp_path, monkeypatch):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(); port = s.getsockname()[1]
    monkeypatch.setattr(T3, "tcp", lambda host, p, timeout=4.0: p == 443)
    assert T3.main(["puertos", "--host", "127.0.0.1", "--out", str(tmp_path / "ok.json")]) == 0 and json.loads((tmp_path / "ok.json").read_text())["ok"] is True
    monkeypatch.setattr(T3, "tcp", lambda host, p, timeout=4.0: p in (443, 5432))                      # la base expuesta
    assert T3.main(["puertos", "--host", "127.0.0.1", "--out", str(tmp_path / "mal.json")]) == 1 and json.loads((tmp_path / "mal.json").read_text())["ok"] is False
    monkeypatch.setattr(T3, "tcp", lambda host, p, timeout=4.0: False)                                 # 443 tampoco responde
    assert T3.main(["puertos", "--host", "127.0.0.1", "--out", str(tmp_path / "x.json")]) == 1; s.close()


def test_tcp_real_distingue_abierto_de_cerrado():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(); p = s.getsockname()[1]
    assert T3.tcp("127.0.0.1", p) is True; s.close(); assert T3.tcp("127.0.0.1", p, timeout=1) is False


def test_memoria_con_oom_sin_swap_o_temporizadores_activos_es_fallo(tmp_path, monkeypatch):
    def fake(out, rc=0): return lambda *a, **k: subprocess.CompletedProcess(a, rc, stdout=out, stderr="")
    base = "mem_total_mb=950 mem_disponible_mb=300\nswap_total_mb=2048 swap_usada_mb=10\noom=0\ntimers_ok=1\nsshd_activo=1\ncloud_init_quiesce=1\n"
    monkeypatch.setattr(subprocess, "run", fake(base)); assert T3.main(["memoria", "--out", str(tmp_path / "a.json")]) == 0
    monkeypatch.setattr(subprocess, "run", fake(base.replace("oom=0", "oom=1"))); assert T3.main(["memoria", "--out", str(tmp_path / "b.json")]) == 1          # el OOM de dnf-makecache de T3
    monkeypatch.setattr(subprocess, "run", fake(base.replace("swap_total_mb=2048", "swap_total_mb=0"))); assert T3.main(["memoria", "--out", str(tmp_path / "c.json")]) == 1
    monkeypatch.setattr(subprocess, "run", fake(base.replace("timers_ok=1", "timers_ok=0"))); assert T3.main(["memoria", "--out", str(tmp_path / "d.json")]) == 1       # temporizador activo = riesgo de OOM
    monkeypatch.setattr(subprocess, "run", fake(base.replace("sshd_activo=1", "sshd_activo=0"))); assert T3.main(["memoria", "--out", str(tmp_path / "e.json")]) == 1  # el quiesce no puede afectar a SSH
    monkeypatch.setattr(subprocess, "run", fake(base.replace("timers_ok=1\n", ""))); assert T3.main(["memoria", "--out", str(tmp_path / "f.json")]) == 1            # no medido = no cumple


def test_sin_medicion_inicial_no_hay_pass(tmp_path):
    args = build(tmp_path); k = args.index("--memoria-inicio"); del args[k:k + 2]
    assert T3.main(args) == 1 and "memoria_sin_oom" in [c["id"] for c in verdict(tmp_path)["criterios"] if c["resultado"] != "CUMPLE"]


def test_quiesce_se_aplica_antes_de_medir_y_se_envia_el_script_por_stdin(tmp_path, monkeypatch):
    calls = []
    def fake(cmd, **k):
        calls.append((cmd, k.get("input"))); out = "" if "bash -s" in cmd[-1] else "mem_total_mb=950 mem_disponible_mb=300\nswap_total_mb=2048 swap_usada_mb=1\noom=0\ntimers_ok=1\nsshd_activo=1\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    assert T3.main(["memoria", "--quiesce", "--out", str(tmp_path / "i.json")]) == 0
    assert "bash -s" in calls[0][0][-1] and "mask" in calls[0][1] and "free -m" in calls[1][0][-1]
    assert json.loads((tmp_path / "i.json").read_text())["quiesce_aplicado"] is True


def test_preflight_local_rechaza_formas_de_pago_y_orígenes_abiertos(tmp_path, monkeypatch):
    monkeypatch.setattr(T3, "ROOT", tmp_path); (tmp_path / "work/terraform-envs").mkdir(parents=True)
    (tmp_path / "work/terraform-envs/oci-t3-create.tfvars").write_text('recovery_shape          = "VM.Standard.E5.Flex"\nallow_trial_paid_shape  = true\nentry_allowed_cidrs = ["0.0.0.0/0"]\n')
    monkeypatch.setattr(T3.Path, "home", classmethod(lambda cls: tmp_path))
    r = T3.preflight_local(); assert r["forma_always_free"][0] is False and r["entrada_sin_0.0.0.0/0"][0] is False


def test_clave_ssh_se_identifica_por_huella_no_por_comentario(tmp_path, monkeypatch):
    monkeypatch.setattr(T3, "ROOT", tmp_path); (tmp_path / "work/terraform-envs").mkdir(parents=True); (tmp_path / "work/terraform-envs/oci-t3-create.tfvars").write_text("x")
    (tmp_path / ".ssh").mkdir(); monkeypatch.setattr(T3.Path, "home", classmethod(lambda cls: tmp_path))
    real = subprocess.run
    def fake(cmd, *a, **k):
        if cmd[0] == "ssh-add": return subprocess.CompletedProcess(cmd, 0, stdout="256 SHA256:AAAAhuellaDeOtraClave nexoeventos-azure (ED25519)\n256 SHA256:BBBBhuellaRecovery usuario@host (ED25519)\n", stderr="")
        if cmd[0] == "ssh-keygen": return subprocess.CompletedProcess(cmd, 0, stdout="256 SHA256:BBBBhuellaRecovery comentario-distinto (ED25519)\n", stderr="")
        return real(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", fake); assert T3.preflight_local()["clave_ssh_en_el_agente"][0] is True              # coincide la huella aunque el comentario sea distinto
    def fake2(cmd, *a, **k):
        if cmd[0] == "ssh-add": return subprocess.CompletedProcess(cmd, 0, stdout="256 SHA256:AAAAhuellaDeOtraClave nexoeventos_recovery (ED25519)\n", stderr="")
        return fake(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", fake2); assert T3.preflight_local()["clave_ssh_en_el_agente"][0] is False              # un comentario «nexoeventos_recovery» con OTRA huella NO vale


def test_marcas_utc_se_registran_una_sola_vez(tmp_path):
    f = tmp_path / "m.json"; assert T3.main(["marca", "apply_inicio", "--file", str(f)]) == 0 and "apply_inicio" in json.loads(f.read_text())
    assert T3.main(["marca", "apply_inicio", "--file", str(f)]) == 1                              # no se reescribe una marca
    assert T3.main(["marca", "apply_fin", "--file", str(f)]) == 0 and T3.secs(json.loads(f.read_text()), "apply_inicio", "apply_fin") >= 0


def test_sin_los_archivos_de_la_fase_2_o_sin_marcas_es_parcial(tmp_path):
    args = build(tmp_path); i = args.index("--recovery-dir-rw"); del args[i:i + 2]; j = args.index("--marcas"); del args[j:j + 2]
    assert T3.main(args) == 1; r = verdict(tmp_path); assert r["veredicto"] == "PARCIAL"
    sin = {c["id"] for c in r["criterios"] if c["resultado"] == "SIN_MEDIR"}; assert {"fase_escritura_humo_todo_ok", "reservas_funcionales_ok", "tiempos_de_reconstruccion_registrados"} <= sin


def test_el_tiempo_de_una_recuperacion_abortada_no_cuenta_como_rto(tmp_path):
    args = build(tmp_path, etapas={"resultado": "FALLO", "etapa_fallida": "postgres", "total_s": 1591.7, "etapas": {"descarga": 5}})
    assert T3.main(args) == 1; r = verdict(tmp_path)
    assert next(c for c in r["criterios"] if c["id"] == "rto_recuperacion_total_s")["resultado"] == "SIN_MEDIR"
