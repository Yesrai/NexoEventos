"""INSTALAR EL VALLADO EN LAS TABLAS DE NEGOCIO sin cambiar sus propietarios, sobre una COPIA LOCAL representativa: las 14 tablas reales creadas por las migraciones de Alembic (rol propietario NOLOGIN
`nexoeventos_owner`, migrador miembro, aplicación solo DML, administrador tipo RDS que NO es propietario ni miembro). Tres roles y tres fases (ver pg_fence.owner_grants_sql): el propietario solo concede TRIGGER; `nexo_fence_owner`
instala; guardián y aplicación no pueden saltarse nada. Se comprueba que instalar y revertir deja IDÉNTICOS datos, propietarios, permisos, catálogo y migraciones, y que las migraciones siguen funcionando con el vallado instalado."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "failover"))
from test_pg_fence_hardening import PGBIN, run, start_cluster  # noqa: E402
from app.failover.pg_fence import PgFence, catalog_snapshot, db_grants_sql, db_revoke_sql, install_sql, owner_grants_sql, owner_revoke_sql, precheck, uninstall_sql, uninstall_triggers_sql  # noqa: E402
from pg_standby import PsycopgExecutor  # noqa: E402

pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")
ROOT = Path(__file__).resolve().parents[3]; PWD = "pw-ficticia-de-prueba-123456"
OWNER, APP, FO, KP, ADM, MIG = "nexoeventos_owner", "nexoeventos_app", "nexo_fence_owner", "nexo_fence_guardian", "nexoeventos_admin", "nexoeventos_migrator"


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    ctx, t, sock = start_cluster(tmp_path_factory, "bi")
    pg = lambda sql, db="postgres", user="postgres": PsycopgExecutor(host=ctx["sock"], port=ctx["port"], dbname=db, user=user)(sql)
    pg(f"CREATE ROLE {OWNER} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"); pg(f"CREATE ROLE {MIG} LOGIN NOINHERIT"); pg(f"GRANT {OWNER} TO {MIG}")
    pg(f"CREATE ROLE {ADM} LOGIN CREATEDB CREATEROLE NOSUPERUSER"); pg(f"GRANT rds_superuser TO {ADM}")                      # administrador tipo RDS (maestro): NO es propietario ni miembro del propietario
    ctx["pg"] = pg
    yield ctx
    run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


@pytest.fixture(params=["propietario", "administrador"])
def rep(cluster, request):
    """La base la posee el propietario de las tablas (como en CI) o el administrador (como la crea RDS con DBName): el procedimiento debe funcionar en los dos casos. Réplica de scripts/provision-database-roles.py:
    el propietario posee las tablas Y el esquema public; el migrador (miembro) ejecuta Alembic con SET ROLE."""
    ctx = dict(cluster); db = f"nexoeventos_rep_{request.param}"; ctx["db_owner"] = request.param
    pg = cluster["pg"]; db_owner = OWNER if request.param == "propietario" else ADM
    pg(f'CREATE DATABASE "{db}" OWNER {db_owner}'); pg(f'REVOKE CONNECT ON DATABASE "{db}" FROM PUBLIC'); pg(f'GRANT CONNECT ON DATABASE "{db}" TO {APP}, {MIG}, {ADM}')
    pg(f"ALTER SCHEMA public OWNER TO {OWNER}", db=db); pg("REVOKE CREATE ON SCHEMA public FROM PUBLIC", db=db); pg(f"GRANT USAGE ON SCHEMA public TO {APP}", db=db)
    env = {**os.environ, "MIGRATION_DATABASE_URL": f"postgresql+psycopg://{MIG}@/{db}?host={ctx['sock']}&port={ctx['port']}"}
    r = subprocess.run([str(ROOT / "backend/.venv/bin/alembic"), "upgrade", "head"], cwd=ROOT / "backend", env=env, capture_output=True, text=True); assert r.returncode == 0, r.stderr[-400:]
    ctx.update(alembic=lambda *a, epoch=None: subprocess.run([str(ROOT / "backend/.venv/bin/alembic"), *a], cwd=ROOT / "backend", env={**env, **({"PGOPTIONS": f"-c nexo.writer_epoch={epoch}"} if epoch else {})}, capture_output=True, text=True), db=db)
    ctx["ex"] = lambda user: PsycopgExecutor(host=ctx["sock"], port=ctx["port"], dbname=db, user=user)
    yield ctx
    pg(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
    for r in (KP, FO): pg(f"DROP ROLE IF EXISTS {r}")


def estado(rep):
    """Todo lo que la instalación NO debe cambiar al revertirla: catálogo con ACL, propietarios, privilegios efectivos de la aplicación, migraciones y datos de TODAS las tablas."""
    ex = rep["ex"](OWNER) if False else rep["ex"](MIG)
    tablas = [r[0] for r in rep["ex"](MIG)("SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1")]
    datos = {}
    for t in tablas:
        rows = rep["ex"](MIG)(f"SET ROLE {OWNER}; SELECT coalesce(md5(string_agg(x::text, ',' ORDER BY x::text)), '-'), count(*) FROM \"{t}\" x")
        datos[t] = tuple(rows[0])
    propietarios = rep["ex"](MIG)("SELECT relname, pg_get_userbyid(relowner) FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r','S') ORDER BY 1")
    privs = rep["ex"](MIG)(f"SELECT c.relname, has_table_privilege('{APP}', c.oid, 'SELECT'), has_table_privilege('{APP}', c.oid, 'INSERT'), has_table_privilege('{APP}', c.oid, 'UPDATE'), has_table_privilege('{APP}', c.oid, 'DELETE'), has_table_privilege('{APP}', c.oid, 'TRUNCATE'), has_table_privilege('{APP}', c.oid, 'TRIGGER') FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' ORDER BY 1")
    return {"tablas": tablas, "datos": datos, "propietarios": propietarios, "privs_app": privs, "alembic": rep["ex"](MIG)(f"SET ROLE {OWNER}; SELECT version_num FROM alembic_version"),
            "catalogo": catalog_snapshot(rep["ex"](MIG), roles=(FO, KP)), "schema_create_app": rep["ex"](MIG)(f"SELECT has_schema_privilege('{APP}', 'public', 'CREATE')")}


def phases_install(rep):
    adm = rep["ex"](ADM)
    adm(f"CREATE ROLE {FO} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"); adm(f"GRANT {FO} TO {ADM} WITH INHERIT FALSE, SET TRUE"); adm(f"CREATE ROLE {KP} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '{PWD}'")
    DB = rep["db"]; db_por_admin = rep["db_owner"] == "administrador"
    if db_por_admin: adm(db_grants_sql(fence_owner=FO, keeper_role=KP, database=DB))                                          # FASE 0: permisos de BASE por quien POSEE la base (aquí el administrador)
    rep["ex"](MIG)(owner_grants_sql(owner_role=OWNER, fence_owner=FO, app_role=APP, database=DB, keeper_role=KP, include_db_grants=not db_por_admin))   # FASE 1: el propietario (vía el migrador, miembro) concede TRIGGER
    pre = precheck(adm, app_role=APP, acting_role=FO); assert pre["ok_to_install"], pre["blockers"]                   # FASE 2: el administrador actúa COMO fence_owner
    assert pre["install_mode"] == "keeper_attach"
    adm("BEGIN;\n" + install_sql(app_role=APP, keeper_role=KP, event_trigger=False, fence_owner=FO) + "\nCOMMIT;")
    return pre


def phases_revert(rep, had_create):
    adm = rep["ex"](ADM)
    rep["ex"](MIG)(uninstall_triggers_sql(owner_role=OWNER))                                                           # FASE A: el propietario quita los triggers de sus tablas
    adm("BEGIN;\n" + uninstall_sql(keeper_role=KP, fence_owner=FO, drop_triggers=False) + "\nCOMMIT;")                 # FASE B: fence_owner quita sus objetos (RESTRICT: falla si quedara un trigger)
    DB = rep["db"]; db_por_admin = rep["db_owner"] == "administrador"
    rep["ex"](MIG)(owner_revoke_sql(owner_role=OWNER, fence_owner=FO, app_role=APP, database=DB, keeper_role=KP, restore_app_create=had_create, include_db_grants=not db_por_admin))   # FASE C: el propietario retira lo concedido
    if db_por_admin: adm(db_revoke_sql(fence_owner=FO, keeper_role=KP, database=DB))
    adm(f"REVOKE ALL ON SCHEMA public FROM {KP}") if False else None
    adm(f"DROP ROLE {KP}"); adm(f"DROP ROLE {FO}")                                                                      # FASE D: el administrador elimina los roles


def test_el_administrador_actual_sin_la_fase_del_propietario_no_puede_instalar_bloqueo_explicito(rep):
    adm = rep["ex"](ADM)
    adm(f"CREATE ROLE {FO} NOLOGIN"); adm(f"GRANT {FO} TO {ADM} WITH INHERIT FALSE, SET TRUE")
    try:
        pre = precheck(adm, app_role=APP)                                                                              # tal cual el administrador real (B2/B3): ni propietario ni miembro ni TRIGGER
        assert not pre["ok_to_install"] and any("no posee" in b for b in pre["blockers"]), pre["blockers"]            # BLOQUEO EXPLÍCITO: sin TRIGGER sobre las tablas del propietario no hay instalación posible
        pre2 = precheck(adm, app_role=APP, acting_role=FO); assert not pre2["ok_to_install"]                           # tampoco como fence_owner sin las concesiones del propietario (falta TRIGGER y CREATE en la base)
        with pytest.raises(psycopg.Error): adm("BEGIN;\n" + install_sql(app_role=APP, keeper_role=KP, event_trigger=False, fence_owner=FO) + "\nCOMMIT;")
        assert rep["ex"](MIG)("SELECT count(*) FROM pg_namespace WHERE nspname = 'nexo_fence'")[0][0] == 0
    finally:
        adm(f"DROP ROLE {FO}")


def test_instalar_y_revertir_sin_cambiar_propietarios_datos_permisos_ni_migraciones(rep):
    from app.failover.pg_fence import SNAPSHOT_SQL
    def lineas(rep):
        import re
        q = re.sub(r"SELECT md5\(string_agg\(x, E'.*?' ORDER BY x\)\)\s*,\s*count\(\*\) FROM \(", "SELECT x FROM (", SNAPSHOT_SQL, flags=re.S).replace(") q", ") q ORDER BY 1")
        return [r[0] for r in rep["ex"](MIG)(q, {"s": "public", "roles": [FO, KP]})]
    antes = estado(rep); lineas_antes = lineas(rep); had_create = rep["ex"](MIG)(f"SELECT has_schema_privilege('{APP}', 'public', 'CREATE')")[0][0]
    phases_install(rep)
    try:
        durante = estado(rep)
        assert durante["propietarios"] == antes["propietarios"] and all(o == OWNER for _, o in durante["propietarios"] if _ not in ()), "cambió algún propietario"
        assert durante["datos"] == antes["datos"] and durante["alembic"] == antes["alembic"] and durante["privs_app"] == antes["privs_app"], "cambió algo visible para la aplicación"
        k = PgFence(rep["ex"](KP), app_role=APP); a = k.attest()
        assert a["ok"] is True and a["tables_total"] == a["tables_covered"] == len(antes["tablas"]) and a["bypass_paths"] == [] and OWNER not in a["admin_roles"] and ADM in a["admin_roles"]
        # la aplicación (rol real de la aplicación, tabla REAL de negocio) escribe SOLO con autoridad
        def app_sql(sql, epoch):
            with psycopg.connect(host=rep["sock"], port=rep["port"], dbname=rep["db"], user=APP) as c:
                c.execute("SELECT set_config('nexo.writer_epoch', %s, true)", (str(epoch),)); c.execute(sql); c.commit()
        ins = "INSERT INTO auth_rate_limits (key_hash, window_started_at) VALUES ('ficticio-b4', now())"
        k.grant(1, "lab", 30); app_sql(ins, 1); app_sql("DELETE FROM auth_rate_limits WHERE key_hash = 'ficticio-b4'", 1)       # con autoridad: acepta (y se deja la tabla como estaba)
        with pytest.raises(psycopg.Error) as e1: app_sql(ins, 7)                                                              # época equivocada
        assert "NEXO_FENCE" in str(e1.value)
        k.revoke(1)
        with pytest.raises(psycopg.Error) as e2: app_sql(ins, 1)                                                              # sin autoridad
        assert "NEXO_FENCE" in str(e2.value)
        # las MIGRACIONES siguen funcionando con el vallado instalado: bajar y subir la última recrea una tabla de negocio, que debe quedar cubierta por el guardián (TRIGGER por privilegios por defecto)
        # (la propia migración ESCRIBE en alembic_version: sin autoridad la base la rechaza; una migración exige una ventana de mantenimiento con autoridad y la época declarada por PGOPTIONS)
        r = rep["alembic"]("downgrade", "-1"); assert r.returncode != 0 and "NEXO_FENCE" in r.stderr, "una migración sin autoridad debe rechazarse"
        k.grant(1, "mantenimiento", 120)
        assert rep["alembic"]("downgrade", "-1", epoch=1).returncode == 0 and rep["alembic"]("upgrade", "head", epoch=1).returncode == 0
        assert k.attest()["uncovered"] == ["queue_entries"] and k.attach_all() >= 1 and k.attest()["ok"] is True
        k.revoke(1)
    finally:
        pass
    phases_revert(rep, had_create)
    despues = estado(rep)
    if despues["catalogo"] != antes["catalogo"]: print("DIF-CATALOGO", sorted(set(lineas_antes) ^ set(lineas(rep))))
    assert despues == antes, {k: (antes[k], despues[k]) for k in antes if antes[k] != despues[k]}                       # catálogo, ACL, propietarios, datos y migraciones IDÉNTICOS


def test_ni_la_aplicacion_ni_el_guardian_pueden_saltarse_los_triggers_y_la_atestacion_lo_detecta_si_se_configura_mal(rep):
    had_create = rep["ex"](MIG)(f"SELECT has_schema_privilege('{APP}', 'public', 'CREATE')")[0][0]
    phases_install(rep)
    try:
        for rol in (APP, KP):
            ex = rep["ex"](rol)
            for sentencia in ("SET session_replication_role = replica", "ALTER TABLE events DISABLE TRIGGER ALL", "ALTER TABLE events DISABLE TRIGGER nexo_fence_commit", "DROP TRIGGER nexo_fence_commit ON events",
                              "DROP SCHEMA nexo_fence CASCADE", "CREATE OR REPLACE FUNCTION nexo_fence.check_write() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN NULL; END'", "ALTER TABLE events OWNER TO " + rol):
                with pytest.raises(psycopg.Error): ex(sentencia)
        k = PgFence(rep["ex"](KP), app_role=APP); assert k.attest()["ok"]
        # configuración equivocada: si el guardián fuese miembro de rds_superuser, la atestación lo declara vía de escape y la base NO concede autoridad
        rep["pg"](f"GRANT rds_superuser TO {KP}")
        try:
            a = k.attest(); assert a["ok"] is False and any("guardián" in x for x in a["bypass_paths"]) and KP in a["admin_roles"]
            with pytest.raises(Exception) as e: k.grant(1, "lab", 5)
            assert "cobertura" in str(e.value) or "vías de escape" in str(e.value)
        finally:
            rep["pg"](f"REVOKE rds_superuser FROM {KP}")
        # y si el guardián fuese propietario de las tablas
        rep["pg"](f"GRANT {OWNER} TO {KP}")
        try: assert k.attest()["ok"] is False
        finally: rep["pg"](f"REVOKE {OWNER} FROM {KP}")
        assert k.attest()["ok"] is True
    finally:
        phases_revert(rep, had_create)
