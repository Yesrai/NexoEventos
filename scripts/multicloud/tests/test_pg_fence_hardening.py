"""Endurecimiento del vallado en la base frente a las RESTRICCIONES REALES de RDS (administrador NO superusuario) y a las vías de escape: event triggers no disponibles, triggers desactivados,
session_replication_role, transacciones preparadas, saltos del reloj, atestación caducada y reversión completa. PostgreSQL 18 desechable; el «administrador tipo RDS» es un rol CREATEDB/CREATEROLE
sin SUPERUSER, miembro de un rol `rds_superuser`, propietario de las tablas (como `postgres` en RDS)."""
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "scripts/multicloud/failover"))
PGBIN = next((Path(p) for p in ("/opt/homebrew/opt/postgresql@18/bin", "/usr/local/opt/postgresql@18/bin") if (Path(p) / "postgres").exists()), None)
pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")

import psycopg  # noqa: E402
from app.failover.gate import WriteGate  # noqa: E402
from app.failover.lease import LeaseClient, LeaseConfig, init_lease  # noqa: E402
from app.failover.pg_fence import FenceAttestation, PgFence, install_sql, precheck, uninstall_sql  # noqa: E402
from app.failover.store import InMemoryStore  # noqa: E402
import evidence as EV  # noqa: E402
from pg_standby import PsycopgExecutor  # noqa: E402


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def start_cluster(tmp_path_factory, name, extra=""):
    t = Path(tmp_path_factory.mktemp(name, numbered=True)); os.chmod(t, 0o700)
    sock = Path("/tmp") / f"{name}{os.getpid()}"; sock.mkdir(mode=0o700, exist_ok=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "PGHOST": str(sock), "PGPORT": str(port), "PGUSER": "postgres", "LC_ALL": "en_US.UTF-8"}
    run([str(PGBIN / "initdb"), "-D", str(t / "pg"), "-U", "postgres", "-E", "UTF8", "--locale=C", "-A", "trust"], env=env, check=True)
    assert run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-o", f"-c listen_addresses= -c unix_socket_directories={sock} -c port={port} -c fsync=off {extra}", "-l", str(t / "log"), "-w", "start"], env=env).returncode == 0
    psql = lambda db, sql: run([str(PGBIN / "psql"), "-q", "-v", "ON_ERROR_STOP=1", "-d", db], input=sql, env=env)
    r = psql("postgres", """CREATE ROLE rds_superuser NOLOGIN; CREATE ROLE master_like LOGIN CREATEDB CREATEROLE NOSUPERUSER; GRANT rds_superuser TO master_like;
        CREATE ROLE nexoeventos_app LOGIN; CREATE ROLE nexo_fence_keeper LOGIN; CREATE DATABASE hard OWNER master_like;""")
    assert r.returncode == 0, r.stderr
    r = psql("hard", "SET ROLE master_like; CREATE TABLE reservas(id serial primary key, v text); CREATE TABLE users(id serial primary key, name text); RESET ROLE;"
                     "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexoeventos_app; GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO nexoeventos_app;")
    assert r.returncode == 0, r.stderr
    ctx = dict(sock=str(sock), port=port, env=env, psql=psql)
    ctx["ex"] = lambda user: PsycopgExecutor(host=str(sock), port=port, dbname="hard", user=user)
    return ctx, t, sock


@pytest.fixture(scope="module")
def rds_like(tmp_path_factory):
    ctx, t, sock = start_cluster(tmp_path_factory, "hdn")
    yield ctx
    run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


@pytest.fixture(scope="module")
def prepared_on(tmp_path_factory):
    ctx, t, sock = start_cluster(tmp_path_factory, "hdp", "-c max_prepared_transactions=4")
    yield ctx
    run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


def fence(ctx):
    return PgFence(ctx["ex"]("nexo_fence_keeper"), app_role="nexoeventos_app")


def test_precheck_mide_al_administrador_tipo_rds_sin_suponer_que_es_superusuario(rds_like):
    r = precheck(rds_like["ex"]("master_like"), app_role="nexoeventos_app", local_now=datetime.now(timezone.utc))
    assert r["is_superuser"] is False and r["member_rds_superuser"] is True
    assert r["can_create_secdef_and_constraint_triggers"] is True and r["can_create_event_trigger"] is False       # sin event triggers: el guardián engancha las tablas nuevas
    assert r["install_mode"] == "keeper_attach" and r["ok_to_install"] is True and any("event triggers" in w for w in r["warnings"])
    assert r["max_prepared_transactions"] == 0 and r["tables_not_owned_or_member"] == [] and (r["clock_skew_s"] is None or r["clock_skew_s"] < 2)
    sup = precheck(rds_like["ex"]("postgres"), app_role="nexoeventos_app")
    assert sup["is_superuser"] is True and sup["can_create_event_trigger"] is True and sup["admin_can_set_session_replication_role"] is True
    assert any("session_replication_role" in w for w in sup["warnings"])                                         # la vía de administración queda señalada
    # el precheck no deja nada instalado
    assert rds_like["ex"]("postgres")("SELECT count(*) FROM pg_namespace WHERE nspname IN ('nx_probe','nexo_fence')")[0][0] == 0
    # rol de la aplicación que sería propietario de las tablas, o administrador que no posee las tablas → bloqueos
    rds_like["psql"]("hard", "CREATE ROLE ajeno LOGIN CREATEDB CREATEROLE; CREATE ROLE dueno NOLOGIN; CREATE TABLE public.de_otro(i int); ALTER TABLE public.de_otro OWNER TO dueno;")
    b = precheck(rds_like["ex"]("ajeno"), app_role="nexoeventos_app")
    assert b["ok_to_install"] is False and any("no posee" in x for x in b["blockers"])
    rds_like["psql"]("hard", "DROP TABLE public.de_otro; DROP ROLE ajeno; DROP ROLE dueno;")


def test_precheck_bloquea_si_la_aplicacion_puede_saltarse_los_triggers_o_hay_transacciones_preparadas(prepared_on):
    r = precheck(prepared_on["ex"]("master_like"), app_role="nexoeventos_app")
    assert r["ok_to_install"] is False and any("max_prepared_transactions" in b for b in r["blockers"])
    p = precheck(prepared_on["ex"]("master_like"), app_role="master_like")                                       # la «aplicación» posee las tablas
    assert any("saltarse triggers" in b for b in p["blockers"])


def test_instalacion_sin_event_trigger_cobertura_exigida_y_vias_de_escape_bloquean_la_autoridad(rds_like):
    adm, f = rds_like["ex"]("master_like"), fence(rds_like)
    adm(install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper", event_trigger=False))
    a = f.attest(); assert a["ok"] is True and a["event_trigger"] is False and a["event_trigger_expected"] is False and a["bypass_paths"] == []
    assert f.grant(1, "aws", 30)["db_now"] is not None
    # tabla nueva SIN trigger: la renovación es RECHAZADA por la base (cobertura incompleta) hasta que el guardián la engancha
    adm("CREATE TABLE public.nueva(i int)")
    a = f.attest(); assert a["ok"] is False and a["uncovered"] == ["nueva"]
    with pytest.raises(Exception) as ex: f.grant(1, "aws", 30)
    assert "cobertura" in str(ex.value)
    assert f.attach_all() == 1 and f.attest()["ok"] is True and f.grant(1, "aws", 30)
    adm("DROP TABLE public.nueva")
    # vías de escape detectables: trigger desactivado (D) o solo para réplica (R)
    for sql, undo in (("ALTER TABLE reservas DISABLE TRIGGER nexo_fence_commit", "ALTER TABLE reservas ENABLE TRIGGER nexo_fence_commit"),
                      ("ALTER TABLE users ENABLE REPLICA TRIGGER nexo_fence_commit", "ALTER TABLE users ENABLE TRIGGER nexo_fence_commit")):
        adm(sql); a = f.attest()
        assert a["ok"] is False and a["uncovered"], sql
        with pytest.raises(Exception): f.grant(1, "aws", 30)
        adm(undo); assert f.attest()["ok"] is True
    sup = rds_like["ex"]("postgres")     # (en PostgreSQL vainilla el administrador tipo RDS NO puede fijar este parámetro; en RDS está sin verificar: se prueba con superusuario el peor caso)
    sup("ALTER DATABASE hard SET session_replication_role = replica")
    a = f.attest(); assert a["ok"] is False and any("session_replication_role" in x for x in a["bypass_paths"])
    with pytest.raises(Exception): f.grant(1, "aws", 30)
    sup("ALTER DATABASE hard RESET session_replication_role"); assert f.attest()["ok"] is True
    f.revoke(1)


def test_la_aplicacion_no_puede_deshabilitar_alterar_ni_reemplazar_el_mecanismo(rds_like):
    app = rds_like["ex"]("nexoeventos_app"); permitidas = []
    for sql in ("ALTER TABLE reservas DISABLE TRIGGER ALL", "DROP TRIGGER nexo_fence_commit ON reservas", "DROP SCHEMA nexo_fence CASCADE",
                "CREATE OR REPLACE FUNCTION nexo_fence.check_write() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN NULL; END'", "ALTER FUNCTION nexo_fence.check_write() SECURITY INVOKER",
                "DROP FUNCTION nexo_fence.check_write() CASCADE", "UPDATE nexo_fence.writer_fence SET valid_until = 'infinity'", "UPDATE nexo_fence.config SET app_role = 'x'",
                "SELECT nexo_fence.grant_authority(9,'x',99)", "SELECT nexo_fence.attach_all()", "SELECT nexo_fence.reset_after_restore()", "SET session_replication_role = replica",
                "ALTER TABLE reservas OWNER TO nexoeventos_app", "ALTER ROLE nexoeventos_app SUPERUSER", "CREATE FUNCTION public.clock_timestamp() RETURNS timestamptz LANGUAGE sql AS 'select now()'",
                "CREATE EVENT TRIGGER x ON ddl_command_end EXECUTE FUNCTION nexo_fence.on_ddl()"):   # (en este clúster no hay event trigger: se prueba aparte con superusuario)
        try:
            app(sql); permitidas.append(sql)
        except psycopg.errors.Error:
            pass
    assert permitidas == [], permitidas
    # y el rol guardián tampoco puede escribir datos de negocio ni tocar las tablas (solo concede/revoca autoridad)
    with pytest.raises(psycopg.errors.Error): rds_like["ex"]("nexo_fence_keeper")("INSERT INTO reservas(v) VALUES ('x')")
    with pytest.raises(psycopg.errors.Error): rds_like["ex"]("nexo_fence_keeper")("ALTER TABLE reservas DISABLE TRIGGER ALL")


def test_transacciones_preparadas_son_una_via_real_de_escape_y_la_base_las_trata_como_tal(prepared_on):
    """Con max_prepared_transactions>0 el trigger diferido se comprueba al PREPARE, no al COMMIT PREPARED: un commit posterior a perder la autoridad PASA. Por eso es un BLOQUEO (precheck y atestación)."""
    adm = prepared_on["ex"]("master_like")
    adm(install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper", event_trigger=False))
    f = fence(prepared_on); a = f.attest()
    assert a["ok"] is False and any("max_prepared_transactions" in x for x in a["bypass_paths"])
    with pytest.raises(Exception) as ex: f.grant(1, "aws", 30)
    assert "vías de escape" in str(ex.value)                                                                      # la base NO concede autoridad en este estado
    # demostración de la vía (autoridad concedida a la fuerza por el propietario de la base, como un error de operación)
    prepared_on["psql"]("hard", "UPDATE nexo_fence.writer_fence SET epoch = 1, valid_until = clock_timestamp() + interval '2 seconds' WHERE id = 1;")
    with psycopg.connect(host=prepared_on["sock"], port=prepared_on["port"], dbname="hard", user="nexoeventos_app") as c:
        c.autocommit = False; cur = c.cursor(); cur.execute("SELECT set_config('nexo.writer_epoch','1',true)"); cur.execute("INSERT INTO reservas(v) VALUES ('preparada')")
        cur.execute("PREPARE TRANSACTION 'tx1'")
    time.sleep(2.5)
    r = prepared_on["psql"]("hard", "COMMIT PREPARED 'tx1';")
    assert r.returncode == 0                                                                                       # CONFIRMÓ sin autoridad: la vía existe, por eso el failover queda bloqueado
    prepared_on["psql"]("hard", "DELETE FROM reservas WHERE v='preparada'; ALTER TABLE reservas DISABLE TRIGGER ALL; DELETE FROM reservas; ALTER TABLE reservas ENABLE TRIGGER ALL;")


def test_guardia_del_reloj_revoca_ante_un_salto_y_no_concede_hasta_ver_intervalos_sanos():
    class FakeFence:
        def __init__(self): self.offset, self.grants, self.revokes, self.cover = 0.0, 0, 0, True
        def now(self): return datetime.fromtimestamp(time.time() + self.offset, tz=timezone.utc)
        def grant(self, e, h, s): self.grants += 1; return {"valid_until": self.now() + timedelta(seconds=s), "db_now": self.now(), "seconds": s}
        def revoke(self, e): self.revokes += 1
        def status(self): return {"epoch": 1, "holder": "x", "remaining_s": 0.0, "valid": False, "db_now": self.now()}
        def attest(self): return {"ok": True}
    store = InMemoryStore(); store.verified = True; init_lease(store)
    gate = WriteGate(LeaseClient(store, LeaseConfig(ttl_s=3.0, margin_s=0.6), holder_id="p"), role="primary", db_fence=FakeFence(), clock_tolerance_s=0.3)
    gate.keeper_step(); gate.keeper_step(); fakef = gate.db_fence
    assert fakef.grants == 2 and gate.status()["db_fence"]["clock_anomalies"] == 0
    time.sleep(0.2); fakef.offset -= 2.0                                                  # el reloj de la base RETROCEDE 2 s (alargaría la autoridad)
    gate.keeper_step()
    assert gate.status()["db_fence"]["clock_anomalies"] == 1 and fakef.revokes >= 1 and gate.last_db_sync_ok is False
    g0 = fakef.grants
    time.sleep(0.15); gate.keeper_step(); assert fakef.grants == g0                         # mientras el reloj de la base siga corrido (desfase ABSOLUTO) no se concede nunca
    fakef.offset += 2.0                                                                    # el reloj se corrige (NTP)
    for _ in range(3): time.sleep(0.15); gate.keeper_step()                                # observa intervalos sanos SIN conceder (el primero ve el salto de la corrección)
    assert fakef.grants == g0
    time.sleep(0.15); gate.keeper_step(); assert fakef.grants == g0 + 1                    # recuperado: vuelve a conceder


def test_una_atestacion_caducada_o_incompleta_nunca_basta_para_promover(rds_like):
    clock = {"t": 5000.0}; att = FenceAttestation(InMemoryStore(), wall=lambda: clock["t"])
    att.publish({"ok": True, "tables_total": 2, "tables_covered": 2}, 3)
    assert att.read()["ok"] is True                                                       # por defecto la ventana es de 30 s
    clock["t"] += 31; r = att.read(); assert r["ok"] is False and r["reason"] == "atestación vencida"
    db_att = lambda: att.read(max_age_s=30, min_epoch=3)
    assert EV.assess_fencing(gate=None, gate_attested=True, lease_held=True, db_attested=bool(db_att()["ok"]))["verdict"] == "UNKNOWN"      # sin atestación vigente: bloqueo
    clock["t"] = 5000.0; att.publish({"ok": False, "tables_total": 2, "tables_covered": 1}, 3)
    assert att.read()["ok"] is False and EV.assess_fencing(gate=None, gate_attested=True, lease_held=True, db_attested=bool(att.read()["ok"]))["verdict"] == "UNKNOWN"


def test_reversion_completa_deja_la_base_como_antes_y_se_puede_reinstalar(rds_like):
    adm = rds_like["ex"]("master_like")
    adm(install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper", event_trigger=False))
    assert adm("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'nexo_fence_%'")[0][0] > 0
    adm(uninstall_sql())
    assert adm("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'nexo_fence_%'")[0][0] == 0
    assert adm("SELECT count(*) FROM pg_namespace WHERE nspname = 'nexo_fence'")[0][0] == 0 and adm("SELECT count(*) FROM pg_event_trigger")[0][0] == 0
    rds_like["ex"]("nexoeventos_app")("INSERT INTO reservas(v) VALUES ('sin-vallado')")                          # tras revertir, la aplicación escribe como antes
    adm("DELETE FROM reservas WHERE v = 'sin-vallado'")
    adm(install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper", event_trigger=False)); assert fence(rds_like).attest()["ok"] is True      # reinstalable
    adm(uninstall_sql())


def test_precheck_puro_de_lectura_no_puede_escribir_nada_y_mide_los_hechos_de_RDS(rds_like):
    from app.failover.pg_fence import precheck_readonly
    adm = rds_like["ex"]("master_like"); sup = rds_like["ex"]("postgres")
    antes = sup("SELECT count(*) FROM pg_namespace WHERE nspname LIKE 'nx_%' OR nspname = 'nexo_fence'")[0][0]
    r = precheck_readonly(adm, app_role="nexoeventos_app")
    assert r["read_only"] is True and r["ok_to_install"] is None and r["member_rds_superuser"] is True and r["is_superuser"] is False
    assert r["max_prepared_transactions"] == 0 and r["tables"] >= 2 and r["tables_not_owned_or_member"] == [] and r["app_role_exists"] is True and r["blockers"] == []
    assert any("B3" in w for w in r["warnings"])                                                                  # lo que exige DDL se declara NO medido
    assert sup("SELECT count(*) FROM pg_namespace WHERE nspname LIKE 'nx_%' OR nspname = 'nexo_fence'")[0][0] == antes
    # la propia base lo impide: dentro de esa transacción ninguna escritura ni DDL es posible
    with pytest.raises(Exception) as e:
        adm("BEGIN TRANSACTION READ ONLY; CREATE SCHEMA nx_intento; ROLLBACK;")
    assert "read-only" in str(e.value).lower()
    with pytest.raises(Exception): adm("BEGIN TRANSACTION READ ONLY; INSERT INTO reservas(v) VALUES ('x'); ROLLBACK;")
    # prepared xacts / app role peligrosa se reportan como bloqueos provisionales
    p = precheck_readonly(adm, app_role="master_like"); assert any("saltarse triggers" in b for b in p["blockers"])
