"""Herramientas de la prueba híbrida: administración del vallado (precheck/instalación/reversión con doble llave), lease_admin, sondas de escritor, análisis de solapamientos y plan."""
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
H = ROOT / "scripts/multicloud/hybrid"
sys.path.insert(0, str(H)); sys.path.insert(0, str(ROOT / "scripts/multicloud/tests"))
import analyze as AN  # noqa: E402
import hybrid_plan as HP  # noqa: E402
import test_lease_http as L  # noqa: E402


def sh(script, *args, env=None):
    return subprocess.run([sys.executable, str(H / script), *args], capture_output=True, text=True, env={**os.environ, **(env or {})})


# ───────────────────────────── plan ─────────────────────────────
def test_el_plan_no_toca_dns_iam_claves_ni_s14_y_todo_cambio_tiene_reversion_y_verificacion():
    txt = json.dumps(HP.PLAN, ensure_ascii=False).lower()
    for prohibido in ("route53", "duckdns", "iam ", "put-role-policy", "attach-role", "s14", "terraform apply", "terraform destroy", "delete-secret", "rotate-secret", "authorize-security-group", "revoke-security-group"):
        assert prohibido not in txt, prohibido
    for p in HP.PLAN:
        assert p["verifica"], p["id"]
        if p["cambia"]:
            assert p["revierte"] or p["id"] in ("R1",) or p["id"].startswith("C"), p["id"]
    ids = [p["id"] for p in HP.PLAN]
    assert ids[-1] == "R1" and "C3" in ids and "C4" in ids                                      # escritor anterior, regreso de AWS y reversión están en el plan
    assert any("failover" in p["titulo"].lower() for p in HP.PLAN) is False                    # no se confunde con el failover automático
    auth = HP.required_authorizations()
    assert any("PAR" in a for a in auth) and any("EC2 y RDS" in a for a in auth) and any("DDL en el RDS" in a for a in auth) and any("iptables" in a for a in auth)


def test_el_plan_clasifica_cada_paso_y_no_instala_triggers_en_tablas_de_negocio_y_mantiene_los_bloqueos():
    assert set(HP.ALCANCE) == {p["id"] for p in HP.PLAN}
    txt = json.dumps([p for p in HP.PLAN if p["id"] in ("B3", "C0", "C3")], ensure_ascii=False)
    assert "nexo_fence_lab" in txt and "NO se tocan" in txt and "tablas de public" not in txt
    assert HP.BLOQUEOS and any("rds_superuser" in b for b in HP.BLOQUEOS)
    assert any("generar las claves" in a for a in HP.required_authorizations())


# ───────────────────────────── análisis de solapamientos ─────────────────────────────
def rec(t, ok=True, **kw):
    return {"t_end": (datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=t)).isoformat(timespec="milliseconds"), "accepted": ok, **kw}


def test_analisis_detecta_solapamientos_y_exige_que_ambos_lados_hayan_escrito():
    a = [rec(i * 0.1) for i in range(50)]                              # AWS escribe hasta t=5
    b = [rec(15 + i * 0.1) for i in range(30)]                         # el standby escribe desde t=15 (hueco de 10 s)
    v = AN.verdict(a, b); assert v["seguro"] and v["solapamientos"] == 0 and v["hueco_entre_el_ultimo_commit_de_A_y_el_primero_de_B_s"] > 9
    solapado = AN.verdict(a, [rec(4.9)]); assert not solapado["seguro"] and solapado["solapamientos"] >= 1
    assert not AN.verdict(a, [])["seguro"] and "NO tuvo efecto" in AN.verdict(a, [])["nota"]       # sin escrituras de un lado la prueba no demuestra nada
    hold_ok = AN.verdict(a, b + [{**rec(9, ok=False), "mode": "hold"}]); assert hold_ok["escritor_anterior_rechazado"] is True and hold_ok["seguro"]
    hold_bad = AN.verdict(a, b + [{**rec(9, ok=True), "mode": "hold"}]); assert hold_bad["escritor_anterior_rechazado"] is False and not hold_bad["seguro"]
    assert AN.verdict(a, [rec(5.2)], tolerance_s=0.1)["solapamientos"] == 0 and AN.verdict(a, [rec(5.2)], tolerance_s=0.5)["solapamientos"] >= 1


# ───────────────────────────── lease_admin contra el servidor HTTP falso ─────────────────────────────
@pytest.fixture
def lease_srv(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), L.H); srv.s = L.Srv(); threading.Thread(target=srv.serve_forever, daemon=True).start()
    f = tmp_path / "par.url"; f.write_text(f"http://127.0.0.1:{srv.server_port}/p/{L.SECRET}/n/ns/b/bk/o/"); os.chmod(f, 0o600)
    yield srv, f
    srv.shutdown(); srv.server_close()


def test_lease_admin_status_init_una_sola_vez_y_rechaza_archivos_abiertos(lease_srv, tmp_path):
    srv, f = lease_srv
    r = sh("lease_admin.py", "status", "--par-url-file", str(f), "--allow-http-localhost"); assert r.returncode == 1 and '"inicializado": false' in r.stdout
    assert sh("lease_admin.py", "init", "--par-url-file", str(f), "--allow-http-localhost").returncode == 0
    r = sh("lease_admin.py", "status", "--par-url-file", str(f), "--allow-http-localhost"); d = json.loads(r.stdout)
    assert r.returncode == 0 and d["inicializado"] and d["titular"] is None and d["epoca"] == 0 and d["liberado"] is True and L.SECRET not in r.stdout + r.stderr
    again = sh("lease_admin.py", "init", "--par-url-file", str(f), "--allow-http-localhost"); assert again.returncode == 0 and "ya existe" in again.stdout     # no lo toca
    os.chmod(f, 0o644); assert sh("lease_admin.py", "status", "--par-url-file", str(f), "--allow-http-localhost").returncode == 2
    os.chmod(f, 0o600); srv.s.enforce = False       # un servicio que IGNORA las condiciones no se acepta
    assert sh("lease_admin.py", "status", "--par-url-file", str(f), "--allow-http-localhost").returncode == 1


# ───────────────────────────── fence_admin y writer_probe contra PostgreSQL 18 desechable ─────────────────────────────
from test_pg_fence_hardening import start_cluster, PGBIN, run as _run  # noqa: E402
import shutil  # noqa: E402


@pytest.fixture(scope="module")
def cl(tmp_path_factory):
    ctx, t, sock = start_cluster(tmp_path_factory, "hyb")
    ctx["dsn"] = lambda user: f"host={ctx['sock']} port={ctx['port']} dbname=hard user={user}"
    yield ctx
    _run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


def dsn_file(tmp_path, text, name="d.dsn", mode=0o600):
    f = tmp_path / name; f.write_text(text); os.chmod(f, mode); return str(f)


pytestmark_pg = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")


@pytestmark_pg
def test_fence_admin_precheck_solo_lectura_instalacion_con_doble_llave_atestacion_y_reversion(cl, tmp_path):
    adm, kp = dsn_file(tmp_path, cl["dsn"]("master_like"), "adm.dsn"), dsn_file(tmp_path, cl["dsn"]("nexo_fence_keeper"), "kp.dsn")
    r = sh("fence_admin.py", "precheck", "--admin-dsn-file", adm); out = json.loads(r.stdout)
    assert r.returncode == 0 and out["ok_to_install"] and out["install_mode"] == "keeper_attach" and "master_like" not in r.stdout           # no imprime credenciales ni el usuario
    assert _run([str(PGBIN / "psql"), "-d", "hard", "-At", "-c", "select count(*) from pg_namespace where nspname in ('nexo_fence','nx_probe')"], env=cl["env"]).stdout.strip() == "0"   # precheck no deja nada
    assert sh("fence_admin.py", "install", "--admin-dsn-file", adm, "--confirm", "INSTALAR VALLADO EN LA BASE").returncode == 3              # sin NEXO_ALLOW_DB_CHANGE
    assert sh("fence_admin.py", "install", "--admin-dsn-file", adm, "--confirm", "no", env={"NEXO_ALLOW_DB_CHANGE": "YES", "NEXO_ALLOW_BUSINESS_DB": "YES"}).returncode == 3     # frase incorrecta
    assert sh("fence_admin.py", "precheck", "--admin-dsn-file", dsn_file(tmp_path, cl["dsn"]("master_like"), "abierto.dsn", 0o644)).returncode == 2   # credenciales con permisos abiertos
    rb = sh("fence_admin.py", "install", "--admin-dsn-file", adm, "--confirm", "INSTALAR VALLADO EN LA BASE", env={"NEXO_ALLOW_DB_CHANGE": "YES"})
    assert rb.returncode == 3 and "LABORATORIO" in rb.stderr                                          # una base que no es de laboratorio se rechaza aunque las llaves estén dadas
    ok = sh("fence_admin.py", "install", "--admin-dsn-file", adm, "--confirm", "INSTALAR VALLADO EN LA BASE", env={"NEXO_ALLOW_DB_CHANGE": "YES", "NEXO_ALLOW_BUSINESS_DB": "YES"}); assert ok.returncode == 0, ok.stdout + ok.stderr
    a = sh("fence_admin.py", "attest", "--keeper-dsn-file", kp); assert a.returncode == 0 and json.loads(a.stdout)["ok"] is True
    assert sh("fence_admin.py", "status", "--keeper-dsn-file", kp).returncode == 0
    # sondas de escritor: sin autoridad rechaza; con autoridad acepta; el «escritor anterior» (hold) es rechazado al vencer
    app = dsn_file(tmp_path, cl["dsn"]("nexoeventos_app"), "app.dsn"); out_f = str(tmp_path / "probe.jsonl")
    sh("writer_probe.py", "--once", "1", "--dsn-file", app, "--out", out_f, "--side", "aws")
    keeper = lambda sql: _run([str(PGBIN / "psql"), "-q", "-d", "hard", "-U", "nexo_fence_keeper", "-At", "-c", sql], env=cl["env"])
    keeper("SELECT nexo_fence.grant_authority(1,'aws',20)")
    sh("writer_probe.py", "--once", "1", "--dsn-file", app, "--out", out_f, "--side", "aws")
    keeper("SELECT nexo_fence.grant_authority(1,'aws',2)")
    sh("writer_probe.py", "--hold", "1", "--hold-seconds", "3.5", "--dsn-file", app, "--out", out_f, "--side", "aws")                          # tarda más que la autoridad
    recs = [json.loads(l) for l in Path(out_f).read_text().splitlines()]
    assert [(r["accepted"], r.get("reason")) for r in recs] == [(False, "NEXO_FENCE"), (True, None), (False, "NEXO_FENCE")] and oct(os.stat(out_f).st_mode & 0o777) == "0o600"
    assert recs[2]["mode"] == "hold" and "dsn" not in json.dumps(recs).lower()
    # reversión completa
    assert sh("fence_admin.py", "uninstall", "--admin-dsn-file", adm, "--confirm", "REVERTIR VALLADO EN LA BASE").returncode == 3
    u = sh("fence_admin.py", "uninstall", "--admin-dsn-file", adm, "--confirm", "REVERTIR VALLADO EN LA BASE", env={"NEXO_ALLOW_DB_CHANGE": "YES", "NEXO_ALLOW_BUSINESS_DB": "YES"}); assert u.returncode == 0 and "triggers restantes: 0" in u.stdout
    assert _run([str(PGBIN / "psql"), "-d", "hard", "-At", "-U", "nexoeventos_app", "-c", "insert into reservas(v) values ('libre') returning id"], env=cl["env"]).returncode == 0      # vuelve a escribir sin vallado


# ───────────────────────────── B2: preparación de la validación en RDS real (solo lectura) ─────────────────────────────
def test_b2_rds_readiness_plan_y_veredicto_con_fixtures():
    import rds_readiness as RR
    plan = "\n".join(RR.plan("mi-rds", "perfil", "us-east-1"))
    assert "describe-db-instances" in plan and "describe-db-parameters" in plan and "precheck" in plan and "evaluate" in plan
    for peligroso in ("start-db-instance", "stop-db-instance", "modify-db", "reboot", "create-", "delete-", "terraform"):
        assert peligroso not in plan, peligroso                                                      # el plan de B2 es SOLO LECTURA
    aws = {"DBInstanceStatus": "available", "Engine": "postgres", "EngineVersion": "18.3", "MultiAZ": True, "ReadReplicaDBInstanceIdentifiers": [], "AutomaticRestartTime": "2026-11-26T15:27:00Z"}
    prm = [{"ParameterName": "track_commit_timestamp", "ParameterValue": "0"}]
    pg = {"ok_to_install": True, "is_superuser": False, "member_rds_superuser": True, "max_prepared_transactions": 0, "can_signal_backends": True, "rds_superuser_can_signal": True, "track_commit_timestamp": "off"}
    r = RR.evaluate(aws, prm, pg)
    assert r["ready_for_b3"] and r["hard_fence_possible"] and r["strong_fence_available"] and any("track_commit_timestamp" in w and "REINICIO" in w for w in r["warnings"])
    assert any("Multi-AZ" in n for n in r["notes"]) and any("reinicio automático" in n for n in r["notes"])
    # sin poder terminar sesiones: no hay vallado por la base; sin réplicas sigue la parada confirmada
    r2 = RR.evaluate(aws, prm, {**pg, "can_signal_backends": False}); assert not r2["hard_fence_possible"] and r2["stop_confirmation_possible"] and r2["strong_fence_available"]
    # con réplicas de lectura la RDS no se puede detener; sin pg_signal_backend tampoco hay vallado fuerte → NO hay mecanismo fuerte
    r3 = RR.evaluate({**aws, "ReadReplicaDBInstanceIdentifiers": ["r1"]}, prm, {**pg, "can_signal_backends": False}); assert not r3["strong_fence_available"]
    # bloqueos: RDS apagada, versión, prepared xacts, precheck no apto
    assert not RR.evaluate({**aws, "DBInstanceStatus": "stopped"}, prm, pg)["ready_for_b3"]
    assert not RR.evaluate({**aws, "EngineVersion": "16.4"}, prm, pg)["ready_for_b3"]
    assert not RR.evaluate(aws, prm, {**pg, "max_prepared_transactions": 5})["ready_for_b3"]
    assert not RR.evaluate(aws, prm, {**pg, "ok_to_install": False, "blockers": ["x"]})["ready_for_b3"]


def test_fence_business_plan_es_solo_texto_no_cambia_propietarios_y_declara_bloqueos_y_riesgos():
    import fence_business as FB
    fases = FB.plan(); txt = "\n".join(f["sql"] + f["ejecuta"] for f in fases)
    assert len(fases) == 8 and "GRANT TRIGGER ON ALL TABLES" in txt and "ALTER DEFAULT PRIVILEGES" in txt and "nexoeventos_migrator" in txt
    for prohibido in ("OWNER TO", "DROP DATABASE", "DROP TABLE", "DISABLE TRIGGER", "session_replication_role = replica", "TRUNCATE"): assert prohibido not in txt, prohibido
    assert "<generada en la EC2" in txt and "PASSWORD '" in txt and txt.count("PASSWORD") == 1            # ninguna contraseña real: solo el marcador
    assert any("MIGRACIONES" in n for n in FB.NOTAS) and any("session_replication_role" in n and "NO DESAPARECE" in n for n in FB.NOTAS)
    assert all(q.rstrip().startswith("SELECT") for q in FB.PREGUNTAS)                                     # las preguntas previas son de solo lectura


def test_b4_readiness_todo_importable_y_el_automatico_sigue_bloqueado():
    import b4_readiness as BR
    s = BR.status()
    assert all(c["implementado_y_probado_en_local"] for c in s["componentes"]), [c for c in s["componentes"] if not c["implementado_y_probado_en_local"]]
    assert s["automatico_permitido"] is False and s["b4_ejecutable_hoy"] is False and s["por_defecto"] == {"automatic": False, "validated_strong_fence": False, "validated_antirollback": False}
    assert len(s["bloqueos_del_automatico"]) >= 4


def test_laboratorio_oci_del_sello_politicas_minimas_matriz_y_controles_negativos():
    import oci_seal_lab as L
    b = L.BUCKET_PREFIX + "20261121"; pol = "\n".join(L.policy_statements(b))
    assert "nexoeventos-recovery" not in pol and b in pol and pol.count("OBJECT_CREATE") == 2                                  # writer y operator: crear
    for linea in pol.splitlines():                                                                                              # los grupos de SERVICIO jamás reciben sobrescribir ni borrar
        if any(g in linea for g in ("nexo-seal-writers", "nexo-seal-operators", "nexo-seal-readers")):
            assert "OBJECT_OVERWRITE" not in linea and "OBJECT_DELETE" not in linea and "manage buckets" not in linea
    assert "manage preauthenticated-requests" in pol and "nexo-seal-lab-admins" in pol
    assert L.main(["plan", "--bucket", "nexoeventos-recovery"]) == 3 and L.main(["plan", "--bucket", "otro"]) == 3
    # la matriz con la configuración CORRECTA demuestra todas las garantías requeridas
    ok = L.evaluate(L.run_suite(L.FakeCloud())); assert ok["validated_antirollback_propuesto"] and not ok["fallan"] and not ok["faltan"]
    assert ok["par_de_escritura_es_solo_adicion"] is True and "SOLO pasa a true" in ok["nota"]
    # CONTROLES NEGATIVOS: cada mala configuración se detecta
    malos = {"writer con OVERWRITE": L.FakeCloud(perms={**L.FakeCloud().perms, "writer": {"CREATE", "INSPECT", "READ", "OVERWRITE"}}), "writer con DELETE": L.FakeCloud(perms={**L.FakeCloud().perms, "writer": {"CREATE", "INSPECT", "READ", "DELETE"}}),
             "lector que puede crear": L.FakeCloud(perms={**L.FakeCloud().perms, "reader": {"CREATE", "INSPECT", "READ"}}), "retención que no bloquea": L.FakeCloud(retention_effective=False)}
    for nombre, cloud in malos.items():
        r = L.evaluate(L.run_suite(cloud)); assert not r["validated_antirollback_propuesto"] and r["fallan"], nombre
    # el PAR de escritura creado por una identidad sin OVERWRITE solo cuenta como solo-adición si el resultado REAL lo demuestra
    assert L.evaluate(L.run_suite(L.FakeCloud(par_rw_by_writer_overwrites=True)))["par_de_escritura_es_solo_adicion"] is False
    assert L.evaluate([r for r in L.run_suite(L.FakeCloud()) if r["id"] != "T8"])["faltan"] == []                                  # (T8b sostiene la misma garantía)
    assert "retencion_bloquea_al_admin" in L.evaluate([r for r in L.run_suite(L.FakeCloud()) if r["garantia"] != "retencion_bloquea_al_admin"])["faltan"]   # una garantía sin probar NO se da por buena


def test_laboratorio_oci_fases_iam_existente_limpieza_y_presupuesto():
    import oci_seal_lab as L
    ids = {t[0] for t in L.TESTS}; assert ids == set(L.REQUIERE) == {i for _, g in L.FASES for i in g}                       # toda prueba está en una fase y tiene sus requisitos
    f0, f1, f2 = L.FASES
    assert all("iam_nuevo" not in L.REQUIERE[i] and "retencion" not in L.REQUIERE[i] for i in f0[1])                         # F0: sin IAM nueva ni retención
    assert all("retencion" not in L.REQUIERE[i] for i in f1[1]) and any("iam_nuevo" in L.REQUIERE[i] for i in f1[1])        # F1: IAM nueva, sin retención
    assert all("retencion" in L.REQUIERE[i] for i in f2[1])
    # las pruebas de IAM (writer/operator/reader) NO se pueden hacer sin IAM nueva: el uploader existente no tiene nada en un bucket nuevo
    assert "NINGUNO" in L.IDENTIDADES_EXISTENTES["nexoeventos-backup-uploader"]["en_un_bucket_nuevo"] and "TODOS" in L.IDENTIDADES_EXISTENTES["admin@example.invalid"]["en_un_bucket_nuevo"]
    assert any("reader" in x for x in L.NO_EXISTEN) and len(L.CAMBIOS_IAM_MINIMOS) == 3
    cp = "\n".join(L.cleanup_plan(L.BUCKET_PREFIX + "x")); assert "472003" in cp and cp.index("PAR") < cp.index("retención") < cp.index("objetos") < cp.index("borrar el bucket") < cp.index("IAM del laboratorio")
    assert L.PRESUPUESTO["techo_usd"] <= 0.05 and L.PRESUPUESTO["computo_necesario"] is False
    with pytest.raises(AssertionError): L.cleanup_plan("nexoeventos-recovery")
    assert L.main(["fases"]) == 0 and L.main(["limpieza", "--bucket", L.BUCKET_PREFIX + "x"]) == 0
