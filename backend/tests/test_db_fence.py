"""Vallado EXTERNO de la base (db_fence.py) contra un PostgreSQL LOCAL DESECHABLE: una base y un rol temporales (nombres con sufijo aleatorio) que se eliminan siempre al terminar.
No toca nexoeventos_test ni ninguna base real. Demuestra que el SERVIDOR rechaza las escrituras del rol de la aplicación aunque el proceso de la aplicación no coopere.
LÍMITES: se prueba contra PostgreSQL local, no contra RDS; sesiones de otros roles privilegiados no quedan valladas; hay que alcanzar la base."""
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError

from app.failover.db_fence import DbFence, FenceError
from tests.conftest import admin_engine


@pytest.fixture
def pg():
    suffix = uuid.uuid4().hex[:10]
    db, role = f"nexo_fence_{suffix}", f"nexo_fence_app_{suffix}"
    root = admin_engine.execution_options(isolation_level="AUTOCOMMIT")
    with root.connect() as c:
        c.execute(text(f'CREATE ROLE "{role}" LOGIN PASSWORD \'prueba-{suffix}\''))
        c.execute(text(f'CREATE DATABASE "{db}"'))
    try:
        adm = create_engine(admin_engine.url.set(database=db), isolation_level="AUTOCOMMIT")
        with adm.connect() as c:
            c.execute(text("CREATE TABLE t (id int)"))
            c.execute(text(f'GRANT CONNECT ON DATABASE "{db}" TO "{role}"'))
            c.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            c.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON t TO "{role}"'))

        def executor(sql, params=None):
            with adm.connect() as c:
                r = c.exec_driver_sql(sql, params or {})
                return [tuple(x) for x in r.fetchall()] if r.returns_rows else []

        def app_engine():
            return create_engine(admin_engine.url.set(database=db, username=role, password=f"prueba-{suffix}"), pool_pre_ping=False)
        yield type("PG", (), {"db": db, "role": role, "ex": staticmethod(executor), "app": staticmethod(app_engine), "adm": adm})()
    finally:
        with root.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
            c.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        adm.dispose()


def test_nologin_impide_nuevas_conexiones_y_mata_las_existentes(pg):
    app = pg.app()
    conn = app.connect(); conn.execute(text("INSERT INTO t VALUES (1)")); conn.commit()          # sesión abierta del primario
    f = DbFence(pg.ex, pg.role, mode="nologin")
    rep = f.fence(); assert rep["sesiones_terminadas"] >= 1
    with pytest.raises((DBAPIError, OperationalError)):
        conn.execute(text("INSERT INTO t VALUES (2)")); conn.commit()                              # la sesión existente murió: el proceso no coopera y aun así no escribe
    with pytest.raises(OperationalError):
        pg.app().connect()                                                                        # y no puede reconectarse
    assert pg.ex("SELECT count(*) FROM t") == [(1,)]
    f.unfence()
    with pg.app().begin() as c2:
        c2.execute(text("INSERT INTO t VALUES (3)"))
    assert pg.ex("SELECT count(*) FROM t") == [(2,)]


def test_readonly_permite_leer_pero_el_rol_no_puede_volver_a_escribir_ni_con_set(pg):
    f = DbFence(pg.ex, pg.role, mode="readonly")
    app = pg.app()
    with app.begin() as c:
        c.execute(text("INSERT INTO t VALUES (1)"))
    f.fence()
    with pg.app().connect() as c:
        assert c.execute(text("SELECT count(*) FROM t")).scalar() == 1                             # lee
        for stmt in ("INSERT INTO t VALUES (2)", "UPDATE t SET id = 9", "DELETE FROM t", "TRUNCATE t"):
            with pytest.raises(DBAPIError, match="permission denied"):
                c.execute(text(stmt))
            c.rollback()
        c.execute(text("SET default_transaction_read_only = off"))
        with pytest.raises(DBAPIError):                                                            # anular el modo de la sesión no devuelve los privilegios: los hace cumplir el servidor
            c.execute(text("INSERT INTO t VALUES (3)"))
    assert pg.ex("SELECT count(*) FROM t") == [(1,)]
    f.unfence()
    with pg.app().begin() as c:
        c.execute(text("INSERT INTO t VALUES (4)"))
    assert pg.ex("SELECT count(*) FROM t") == [(2,)]


def test_fence_es_idempotente_y_un_segundo_fence_no_pisa_los_privilegios_guardados(pg):
    f = DbFence(pg.ex, pg.role, mode="readonly")
    f.fence(); saved = list(f.saved["grants"]); f.fence()
    assert f.saved["grants"] == saved and len(saved) == 3                                          # los privilegios de escritura que el rol tenía sobre t: INSERT, UPDATE, DELETE
    f.unfence()
    with pg.app().begin() as c:
        c.execute(text("INSERT INTO t VALUES (1)"))


def test_el_administrador_no_queda_vallado_limite_declarado(pg):
    DbFence(pg.ex, pg.role, mode="nologin").fence()
    pg.ex("INSERT INTO t VALUES (7)")                                                              # un rol privilegiado sigue escribiendo: el vallado es del rol de la aplicación
    assert pg.ex("SELECT count(*) FROM t") == [(1,)]


@pytest.mark.parametrize("role,schema", [('x"; DROP TABLE t; --', "public"), ("ok_rol", 'public"; --'), ("", "public"), ("MAYUS", "public"), ("a" * 70, "public")])
def test_identificadores_peligrosos_se_rechazan(pg, role, schema):
    with pytest.raises(FenceError):
        DbFence(pg.ex, role, schema)
    assert pg.ex("SELECT count(*) FROM t") == [(0,)]


def test_un_fallo_del_ejecutor_es_un_error_explicito_nunca_un_vallado_asumido(pg):
    def roto(sql, params=None): raise RuntimeError("detalle sensible de conexión")
    with pytest.raises(FenceError) as e:
        DbFence(roto, pg.role).fence()
    assert "sensible" not in str(e.value)
    with pytest.raises(FenceError):
        DbFence(pg.ex, "rol_que_no_existe_zz", mode="nologin").fence()
