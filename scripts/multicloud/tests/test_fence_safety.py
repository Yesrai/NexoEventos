"""Seguridad de la instalación y la REVERSIÓN del vallado ante fallos parciales (PostgreSQL 18 desechable, administrador tipo RDS sin superusuario):
transacción única con rollback total, conexión matada a mitad de la instalación, lock_timeout frente a un bloqueo ajeno, reversión bloqueada por un objeto ajeno dependiente,
huella del catálogo idéntica tras instalar+revertir (incluido el CREATE del rol de la aplicación), idempotencia y aislamiento de una base de laboratorio dentro del mismo servidor."""
import hashlib
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pg_fence_hardening import PGBIN, run, start_cluster  # noqa: E402,F401

import psycopg  # noqa: E402
from app.failover.pg_fence import catalog_snapshot, install_sql, uninstall_sql  # noqa: E402

pytestmark = pytest.mark.skipif(PGBIN is None, reason="requiere PostgreSQL 18 local")
GUARD = "SET LOCAL lock_timeout = '1s'; SET LOCAL statement_timeout = '60s';"


@pytest.fixture(scope="module")
def cl(tmp_path_factory):
    ctx, t, sock = start_cluster(tmp_path_factory, "fsf")
    yield ctx
    run([str(PGBIN / "pg_ctl"), "-D", str(t / "pg"), "-m", "immediate", "stop"], env=ctx["env"]); shutil.rmtree(sock, ignore_errors=True)


def conn(cl, user="master_like", db="hard", **kw):
    return psycopg.connect(host=cl["sock"], port=cl["port"], dbname=db, user=user, autocommit=True, **kw)


def snap(cl, db="hard"):
    return catalog_snapshot(lambda sql, p=None: [tuple(r) for r in conn(cl, db=db).execute(sql, p).fetchall()], roles=("nexo_fence_keeper", "nexoeventos_app"))


def data_hash(cl, db="hard"):
    rows = conn(cl, db=db).execute("SELECT 'r'||id||v FROM reservas ORDER BY id").fetchall() + conn(cl, db=db).execute("SELECT 'u'||id||name FROM users ORDER BY id").fetchall()
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def count_fence_objects(cl, db="hard"):
    return conn(cl, db=db).execute("SELECT (SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'nexo_fence_%'), (SELECT count(*) FROM pg_namespace WHERE nspname='nexo_fence')").fetchone()


INSTALL = install_sql(app_role="nexoeventos_app", keeper_role="nexo_fence_keeper", event_trigger=False)
UNINSTALL = uninstall_sql(keeper_role="nexo_fence_keeper")


def atomic(sql):
    return f"BEGIN;\n{GUARD}\n{sql}\nCOMMIT;"


@pytest.fixture(autouse=True)
def limpio(cl):
    """Cada prueba parte del estado «sin vallado» con datos de negocio y con el CREATE concedido a la app (para probar que se restaura)."""
    c = conn(cl)
    if count_fence_objects(cl)[1]:
        c.execute(atomic(UNINSTALL))
    c.execute("TRUNCATE reservas, users RESTART IDENTITY CASCADE; INSERT INTO reservas(v) VALUES ('a'),('b'); INSERT INTO users(name) VALUES ('x');")
    c.execute("GRANT CREATE ON SCHEMA public TO nexoeventos_app")
    yield


def test_instalar_y_revertir_deja_el_catalogo_identico_y_restaura_el_create_de_la_app(cl):
    antes, datos = snap(cl), data_hash(cl)
    conn(cl).execute(atomic(INSTALL))
    assert count_fence_objects(cl)[1] == 1 and snap(cl) != antes
    assert conn(cl).execute("SELECT has_schema_privilege('nexoeventos_app','public','CREATE')").fetchone()[0] is False       # la instalación lo quita…
    conn(cl).execute(atomic(UNINSTALL))
    assert count_fence_objects(cl) == (0, 0)
    assert conn(cl).execute("SELECT has_schema_privilege('nexoeventos_app','public','CREATE')").fetchone()[0] is True        # …y la reversión lo devuelve
    assert snap(cl) == antes and data_hash(cl) == datos


def test_fallo_forzado_a_mitad_de_la_instalacion_deshace_todo(cl):
    antes, datos = snap(cl), data_hash(cl)
    with pytest.raises(psycopg.errors.DivisionByZero):
        conn(cl).execute(atomic(INSTALL + "\nSELECT 1/0;"))
    assert snap(cl) == antes and count_fence_objects(cl) == (0, 0) and data_hash(cl) == datos


def test_conexion_matada_a_mitad_de_la_instalacion_deshace_todo(cl):
    antes = snap(cl)
    errores = []
    victima = conn(cl, application_name="instalador_a_matar")

    def instalar():
        try:
            victima.execute(atomic(INSTALL + "\nSELECT pg_sleep(30);"))
        except psycopg.Error as e:
            errores.append(e)
    th = threading.Thread(target=instalar); th.start()
    admin = conn(cl, user="postgres")
    for _ in range(100):                                                                                                     # esperar a que esté dentro del pg_sleep
        if admin.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name='instalador_a_matar' AND query LIKE '%pg_sleep%'").fetchone()[0]:
            break
        time.sleep(0.1)
    admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name='instalador_a_matar'")
    th.join(20)
    assert errores, "la instalación debía fallar al matar la conexión"
    assert snap(cl) == antes and count_fence_objects(cl) == (0, 0)


def test_lock_timeout_aborta_la_instalacion_si_otra_sesion_bloquea_una_tabla(cl):
    antes = snap(cl)
    bloqueador = conn(cl, user="postgres"); bloqueador.autocommit = False
    bloqueador.execute("LOCK TABLE reservas IN ACCESS EXCLUSIVE MODE")
    try:
        t0 = time.time()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            conn(cl).execute(atomic(INSTALL))
        assert time.time() - t0 < 10                                                                                         # no se queda esperando indefinidamente
    finally:
        bloqueador.rollback(); bloqueador.close()
    assert snap(cl) == antes and count_fence_objects(cl) == (0, 0)


def test_reversion_bloqueada_por_un_objeto_ajeno_falla_entera_y_no_toca_nada(cl):
    conn(cl).execute(atomic(INSTALL))
    conn(cl).execute("CREATE VIEW vista_cliente AS SELECT * FROM nexo_fence.config")                                          # objeto ajeno que depende del vallado
    instalado = snap(cl)
    with pytest.raises(psycopg.Error):
        conn(cl).execute(atomic(UNINSTALL))
    assert snap(cl) == instalado and count_fence_objects(cl)[0] > 0 and count_fence_objects(cl)[1] == 1                      # el vallado sigue ENTERO, no a medias
    assert conn(cl).execute("SELECT count(*) FROM pg_views WHERE viewname='vista_cliente'").fetchone()[0] == 1
    conn(cl).execute("DROP VIEW vista_cliente")
    conn(cl).execute(atomic(UNINSTALL)); assert count_fence_objects(cl) == (0, 0)


def test_reinstalar_y_revertir_dos_veces_es_idempotente(cl):
    antes = snap(cl)
    conn(cl).execute(atomic(INSTALL)); conn(cl).execute(atomic(INSTALL))
    assert count_fence_objects(cl)[1] == 1
    conn(cl).execute(atomic(UNINSTALL)); conn(cl).execute(atomic(UNINSTALL))
    assert snap(cl) == antes


def test_instalar_en_base_de_laboratorio_no_cambia_la_base_real_ni_sus_datos(cl):
    real_antes, datos = snap(cl), data_hash(cl)
    adm = conn(cl, user="postgres", db="postgres")
    adm.execute("DROP DATABASE IF EXISTS lab"); adm.execute("CREATE DATABASE lab OWNER master_like")
    lab = conn(cl, db="lab")
    lab.execute("CREATE TABLE reservas(id serial primary key, v text); CREATE TABLE users(id serial primary key, name text)")
    lab.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexoeventos_app")
    lab.execute(atomic(INSTALL))
    assert count_fence_objects(cl, db="lab")[1] == 1
    assert snap(cl) == real_antes and count_fence_objects(cl) == (0, 0) and data_hash(cl) == datos                           # la «real» ni se entera
    lab.execute(atomic(UNINSTALL)); lab.close()
    adm.execute("DROP DATABASE lab")
    assert snap(cl) == real_antes


def test_trinquete_del_sello_en_la_base_solo_sube_y_lo_puede_usar_el_guardian_no_la_app(cl):
    from app.failover.seal_log import PgRatchet
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "failover"))
    from pg_standby import PsycopgExecutor
    conn(cl).execute(atomic(INSTALL))
    try:
        k = PgRatchet(PsycopgExecutor(host=cl["sock"], port=cl["port"], dbname="hard", user="nexo_fence_keeper"))
        assert k.observe(5) == 5 and k.observe(3) == 5 and k.observe(9) == 9 and k.observe(0) == 9             # monotónico: nunca baja
        with pytest.raises(psycopg.Error): PsycopgExecutor(host=cl["sock"], port=cl["port"], dbname="hard", user="nexoeventos_app")("SELECT nexo_fence.ratchet_seal(0)")
        with pytest.raises(psycopg.Error): PsycopgExecutor(host=cl["sock"], port=cl["port"], dbname="hard", user="nexoeventos_app")("UPDATE nexo_fence.seal_ratchet SET seq = 0")
    finally:
        conn(cl).execute(atomic(UNINSTALL))
