#!/usr/bin/env python3
"""B3 · prueba de VALLADO FUERTE (hard_fence) en una base AISLADA `nexo_fence_lab` DENTRO de la RDS REAL, ejecutada en la EC2 por SSM. Alcance: CREATE DATABASE nexo_fence_lab + 2 roles de laboratorio + todo lo que ocurre dentro de esa
base. La base de negocio solo se LEE (catálogo, transacción READ ONLY) antes y después para comprobar que quedó idéntica. La contraseña administrativa se lee dentro de la EC2 y no se imprime ni sale. SIEMPRE revierte
(finally): desinstala el vallado comparando la huella del catálogo, elimina la base y los roles y verifica que la lista de bases y roles es la inicial. Con un plazo (`NEXO_B3_DEADLINE_EPOCH`) para no cruzar el apagado automático.
  build | run --instance-id I --secret-id S --endpoint H --snapshot NOMBRE --confirm "EJECUTAR PASO B3 VALLADO FUERTE EN NEXO_FENCE_LAB" (NEXO_ALLOW_CLOUD_CHANGES=YES) | cleanup (mismo, modo de limpieza)"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid_b2 as B2  # noqa: E402

CONFIRM = "EJECUTAR PASO B3 VALLADO FUERTE EN NEXO_FENCE_LAB"
LAB, KEEPER, APP = "nexo_fence_lab", "nexo_fence_keeper_lab", "nexo_lab_app"

REMOTE = r'''
import base64, importlib.util, json, os, secrets, shutil, sys, tempfile, threading, time, zlib, subprocess
HOST = os.environ.get("NEXO_B3_HOST", {host!r}); PORT = os.environ.get("NEXO_B3_PORT", "5432"); SSL = os.environ.get("NEXO_B3_SSLMODE", "require")
BUSINESS = os.environ.get("NEXO_B3_BUSINESS_DB", {business!r}); SECRET = {secret!r}; MODE = os.environ.get("NEXO_B3_MODE", "run")
LAB, KEEPER, APP = {lab!r}, {keeper!r}, {app!r}
DEADLINE = float(os.environ.get("NEXO_B3_DEADLINE_EPOCH", "0")) or None
SRC = zlib.decompress(base64.b64decode({src!r})).decode()
rep = {{"ok": False, "pasos": {{}}, "mode": MODE}}
tmp = tempfile.mkdtemp(prefix="nexo-b3-"); os.chmod(tmp, 0o700)
open(os.path.join(tmp, "pg_fence_mod.py"), "w").write(SRC)
spec = importlib.util.spec_from_file_location("pg_fence_mod", os.path.join(tmp, "pg_fence_mod.py")); M = importlib.util.module_from_spec(spec); sys.modules["pg_fence_mod"] = M; spec.loader.exec_module(M)
import psycopg
from psycopg.conninfo import make_conninfo
def step(name, **kw): rep["pasos"][name] = kw
def left(): return (DEADLINE - time.time()) if DEADLINE else 1e9
def need(secs, what):
    if left() < secs: raise TimeoutError(f"plazo insuficiente antes de «{{what}}» (quedan {{int(left())}} s)")
class Ex:
    """Ejecutor sobre una conexión por llamada (autocommit); varias sentencias en una cadena."""
    def __init__(self, conninfo): self.ci = conninfo
    def __call__(self, sql, params=None):
        with psycopg.connect(self.ci, autocommit=True) as c, c.cursor() as cur:
            cur.execute(sql, params); rows = []
            while True:
                if cur.description: rows = [tuple(r) for r in cur.fetchall()]
                if not cur.nextset(): break
            return rows
class RoEx(Ex):
    def __call__(self, sql, params=None):
        with psycopg.connect(self.ci, autocommit=True) as c, c.cursor() as cur:
            cur.execute("BEGIN TRANSACTION READ ONLY"); cur.execute(sql, params); rows = [tuple(r) for r in cur.fetchall()] if cur.description else []; cur.execute("ROLLBACK"); return rows
def ci(db, user, pw): return make_conninfo(host=HOST, port=PORT, dbname=db, user=user, password=pw, sslmode=SSL, connect_timeout="15", application_name="nexo-b3-lab")
def lists(adm):
    return {{"dbs": sorted(r[0] for r in adm("SELECT datname FROM pg_database")), "roles": sorted(r[0] for r in adm("SELECT rolname FROM pg_roles"))}}
adm_user = adm_pw = None; pw_k = secrets.token_urlsafe(24); pw_a = secrets.token_urlsafe(24)
before = business_before = None; created_db = created_roles = installed = False; snap_before = None
def revert(admin_pg, admin_lab):
    out = {{}}
    try:
        if installed and admin_lab is not None:
            out["desinstalar"] = "intentado"
            admin_lab("BEGIN; SET LOCAL lock_timeout = '5s'; SET LOCAL statement_timeout = '60s';\n" + M.uninstall_sql(keeper_role=KEEPER, drop_role=False) + "\nCOMMIT;")
            after = M.catalog_snapshot(admin_lab, schema="public", roles=(KEEPER, APP)); out["huella_lab_identica_a_la_previa"] = (after == snap_before)
    except Exception as e: out["desinstalar_error"] = type(e).__name__ + ":" + str(e)[:80]
    try:
        admin_pg("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (LAB,))
        if created_db: admin_pg('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % LAB)
        for r in (APP, KEEPER): admin_pg('DROP ROLE IF EXISTS "%s"' % r)
        out["borrado"] = True
    except Exception as e: out["borrado_error"] = type(e).__name__ + ":" + str(e)[:80]
    return out
try:
    r = subprocess.run(["aws", "secretsmanager", "get-secret-value", "--secret-id", SECRET, "--query", "SecretString", "--output", "text"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0: raise RuntimeError("secreto no legible")
    sec = json.loads(r.stdout); adm_user, adm_pw = sec["username"], sec["password"]; del r, sec
    admin_pg = Ex(ci("postgres", adm_user, adm_pw)); admin_lab = Ex(ci(LAB, adm_user, adm_pw)); biz = RoEx(ci(BUSINESS, adm_user, adm_pw))
    before = lists(admin_pg); step("estado_inicial", bases=len(before["dbs"]), roles=len(before["roles"]), lab_existia=LAB in before["dbs"])
    if MODE == "verify":
        rep.update(listas=before, ok=True)
    else:
        if MODE == "cleanup":
            created_db = LAB in before["dbs"]; rep["limpieza"] = revert(admin_pg, None); rep["despues"] = lists(admin_pg); rep["ok"] = True
        else:
            if LAB in before["dbs"] or KEEPER in before["roles"] or APP in before["roles"]: raise RuntimeError("el laboratorio ya existe: se detiene sin tocar nada")
            business_before = M.catalog_snapshot(biz, schema="public", roles=()); step("negocio_huella_antes", elementos=business_before["elementos"])
            need(600, "crear la base de laboratorio")
            from psycopg import sql
            admin_pg(sql.SQL("CREATE ROLE {{}} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {{}}").format(sql.Identifier(KEEPER), sql.Literal(pw_k)).as_string(None))
            admin_pg(sql.SQL("CREATE ROLE {{}} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {{}}").format(sql.Identifier(APP), sql.Literal(pw_a)).as_string(None)); created_roles = True
            admin_pg(f'CREATE DATABASE "{{LAB}}"'); created_db = True
            admin_pg(f'REVOKE ALL ON DATABASE "{{LAB}}" FROM PUBLIC; GRANT CONNECT ON DATABASE "{{LAB}}" TO "{{KEEPER}}", "{{APP}}"'); step("lab_creada", base=LAB, roles=[KEEPER, APP])
            admin_lab("CREATE TABLE reservas (id serial PRIMARY KEY, v text); CREATE TABLE users (id serial PRIMARY KEY, name text); "
                      f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{{APP}}"; GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO "{{APP}}"')
            pre = M.precheck(admin_lab, app_role=APP)
            step("precheck_ddl_en_lab", ok_to_install=pre["ok_to_install"], install_mode=pre["install_mode"], can_create_secdef_and_constraint_triggers=pre.get("can_create_secdef_and_constraint_triggers"), can_create_event_trigger=pre.get("can_create_event_trigger"),
                 admin_can_set_srr=pre.get("admin_can_set_session_replication_role"), can_signal_backends=pre.get("can_signal_backends"), blockers=pre["blockers"], warnings=[w[:90] for w in pre["warnings"]])
            if not pre["ok_to_install"]: raise RuntimeError("precheck con bloqueos en el laboratorio")
            snap_before = M.catalog_snapshot(admin_lab, schema="public", roles=(KEEPER, APP))
            need(300, "instalar el vallado")
            admin_lab("BEGIN; SET LOCAL lock_timeout = '5s'; SET LOCAL statement_timeout = '120s';\n" + M.install_sql(app_role=APP, keeper_role=KEEPER, event_trigger=(pre["install_mode"] == "event_trigger")) + "\nCOMMIT;"); installed = True
            keeper = M.PgFence(Ex(ci(LAB, KEEPER, pw_k)), app_role=APP); att = keeper.attest()
            step("instalado_y_atestado", ok=att.get("ok"), tablas=att.get("tables_total"), cubiertas=att.get("tables_covered"), event_trigger=att.get("event_trigger"), vias_de_escape=att.get("bypass_paths"))
            if not att.get("ok"): raise RuntimeError("atestación no ok")
            g = keeper.grant(1, "b3-lab", 120.0); step("autoridad_concedida", epoca=1)
            def app_txn(sleep_before=0.0, stall=None):
                c = psycopg.connect(ci(LAB, APP, pw_a)); c.execute("SELECT set_config('nexo.writer_epoch', '1', true)")
                if stall: c.execute("SELECT set_config('nexo_test.stall', %s, true)", (str(stall),))
                return c
            c0 = app_txn(); c0.execute("INSERT INTO reservas(v) VALUES ('base-ficticia')"); c0.commit(); c0.close(); step("escritura_previa_aceptada", ok=True)
            # sesiones de la aplicación de laboratorio, algunas con transacción abierta y un COMMIT estancado DENTRO de la base (tras pasar la comprobación)
            admin_lab("CREATE SCHEMA nexo_test; CREATE FUNCTION nexo_test.stall() RETURNS trigger LANGUAGE plpgsql AS $f$ BEGIN PERFORM pg_sleep(coalesce(nullif(current_setting('nexo_test.stall', true), ''), '0')::float); RETURN NULL; END $f$; "
                      "CREATE CONSTRAINT TRIGGER zz_stall AFTER INSERT ON public.reservas DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nexo_test.stall()")
            s1 = app_txn(); s1.execute("INSERT INTO reservas(v) VALUES ('s1-abierta')")                 # idle in transaction
            s3 = app_txn(); s3.rollback()                                                                   # sesión ociosa
            res2 = {{}}
            def commit_estancado():
                try:
                    c = app_txn(stall=40); c.execute("INSERT INTO reservas(v) VALUES ('s2-estancada')"); c.commit(); res2["r"] = "COMMIT_COMPLETADO"
                except Exception as e: res2["r"] = type(e).__name__ + ":" + str(e)[:60]
            th = threading.Thread(target=commit_estancado, daemon=True); th.start(); time.sleep(3.0)
            n_ses = admin_lab("SELECT count(*) FROM pg_stat_activity WHERE usename = %s AND datname = %s", (APP, LAB))[0][0]; sleeping = admin_lab("SELECT count(*) FROM pg_stat_activity WHERE usename = %s AND wait_event = 'PgSleep'", (APP,))[0][0]
            biz_sessions_before = admin_pg("SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (BUSINESS,))[0][0]
            step("sesiones_de_prueba", sesiones_de_la_aplicacion_lab=n_ses, commit_estancado_dentro_de_la_base=sleeping)
            need(240, "hard_fence")
            proof = keeper.hard_fence("b3-lab", wait_s=15.0); step("hard_fence", prueba=proof, prueba_ok=M.PgFence.proof_ok(proof))
            th.join(20); res_s1 = "sin error"
            try: s1.commit()
            except Exception as e: res_s1 = type(e).__name__ + ":" + str(e)[:70]
            filas = {{r[0]: r[1] for r in admin_lab("SELECT v, count(*) FROM reservas GROUP BY v")}}
            step("tras_el_vallado", sesion_abierta_commit=res_s1, commit_estancado=res2.get("r"), filas_en_lab=filas, sesiones_restantes=admin_lab("SELECT count(*) FROM pg_stat_activity WHERE usename = %s AND datname = %s", (APP, LAB))[0][0],
                 sesiones_de_negocio_antes=biz_sessions_before, sesiones_de_negocio_despues=admin_pg("SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (BUSINESS,))[0][0])
            nuevo = "ACEPTADA (MAL)"
            try:
                c = app_txn(); c.execute("INSERT INTO reservas(v) VALUES ('tras-el-vallado')"); c.commit(); c.close()
            except Exception as e: nuevo = ("NEXO_FENCE" if "NEXO_FENCE" in str(e) else type(e).__name__)
            step("escritura_posterior_al_vallado", resultado=nuevo)
            cerrojo = {{}}
            for nombre, ex in (("guardian_misma_sesion", keeper), ("guardian_conexion_nueva", M.PgFence(Ex(ci(LAB, KEEPER, pw_k)), app_role=APP))):
                try: ex.grant(2, "b3-lab", 30.0); cerrojo[nombre] = "CONCEDIDA (MAL)"
                except Exception as e: cerrojo[nombre] = "CERROJADA" if "CERROJADA" in str(e) else type(e).__name__
            cerrojo["latch_en_base"] = admin_lab("SELECT latched FROM nexo_fence.latch")[0][0]; step("cerrojo_persistente", **cerrojo)
            fb = {{}}
            try: keeper.release_latch("frase incorrecta"); fb["frase_incorrecta"] = "ACEPTADA (MAL)"
            except Exception: fb["frase_incorrecta"] = "rechazada"
            keeper.release_latch("LIBERAR CERROJO DEL VALLADO"); keeper.grant(2, "b3-lab", 5.0); keeper.revoke(2); fb["failback_manual_con_frase"] = "ok"; step("failback_manual", **fb)
            admin_lab("DROP TRIGGER zz_stall ON public.reservas; DROP SCHEMA nexo_test CASCADE")
            rep["ok"] = True
        if MODE == "run":
            rv = revert(admin_pg, admin_lab); installed = False; created_db = False; rep["reversion"] = rv
            rep["listas_iguales_a_las_iniciales"] = (lists(admin_pg) == before); rep["lab_existe"] = LAB in lists(admin_pg)["dbs"]
            rep["negocio_huella_identica"] = (M.catalog_snapshot(biz, schema="public", roles=()) == business_before)
except Exception as e:
    rep["error"] = type(e).__name__ + ":" + str(e)[:140]
    try:
        if MODE == "run" and adm_user:
            ap_, al_ = Ex(ci("postgres", adm_user, adm_pw)), Ex(ci(LAB, adm_user, adm_pw))
            rep["reversion_tras_error"] = revert(ap_, al_ if installed else None)
            rep["listas_iguales_a_las_iniciales"] = (lists(ap_) == before) if before else None
    except Exception as e2: rep["reversion_error"] = type(e2).__name__
finally:
    shutil.rmtree(tmp, ignore_errors=True); rep["efimero_eliminado"] = not os.path.exists(tmp); adm_pw = pw_k = pw_a = None
print("NEXO_B3_JSON=" + json.dumps(rep, default=str))
'''


def build_remote(endpoint="", business="nexoeventos", secret_id="") -> str:
    src = base64.b64encode(zlib.compress((ROOT / "backend/app/failover/pg_fence.py").read_bytes(), 9)).decode()
    return REMOTE.format(host=endpoint, business=business, secret=secret_id, lab=LAB, keeper=KEEPER, app=APP, src=src)


def parse(text):
    for line in text.splitlines():
        if line.startswith("NEXO_B3_JSON="):
            return json.loads(line[len("NEXO_B3_JSON="):])
    raise ValueError("sin resultado")


def run_remote(script, instance_id, deadline_epoch, mode="run", **kw):
    wrapped = f"import os\nos.environ['NEXO_B3_DEADLINE_EPOCH']={str(deadline_epoch)!r}\nos.environ['NEXO_B3_MODE']={mode!r}\n" + script
    return parse(B2.ssm_run(wrapped, instance_id, timeout_s=kw.get("timeout_s", 420)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["build", "run", "cleanup", "verify"]); ap.add_argument("--instance-id"); ap.add_argument("--secret-id"); ap.add_argument("--endpoint"); ap.add_argument("--business-db", default="nexoeventos")
    ap.add_argument("--deadline-epoch", type=float, default=0.0); ap.add_argument("--confirm", default=""); a = ap.parse_args(argv)
    if a.cmd == "build":
        print(build_remote(a.endpoint or "<endpoint>", a.business_db, a.secret_id or "<secreto>")); return 0
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES" or a.confirm != CONFIRM:
        print("RECHAZADO: falta NEXO_ALLOW_CLOUD_CHANGES=YES y la frase exacta.", file=sys.stderr); return 3
    if a.cmd == "run" and a.deadline_epoch - time.time() < 20 * 60:
        print("RECHAZADO: quedan menos de 20 minutos hasta el apagado automático: no se ejecutan cambios.", file=sys.stderr); return 3
    try:
        out = run_remote(build_remote(a.endpoint, a.business_db, a.secret_id), a.instance_id, a.deadline_epoch or time.time() + 3600, mode=a.cmd)
    except (RuntimeError, ValueError, OSError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr); return 2
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str)); return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
