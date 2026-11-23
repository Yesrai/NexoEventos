"""Detector de escritores externos contra un PostgreSQL DESECHABLE (clúster nuevo en un directorio temporal, sin red; ver pgtemp.py). No toca el clúster ni las bases locales existentes."""
import time

import pytest
from sqlalchemy import create_engine as _ce, text
from sqlalchemy.pool import NullPool


def create_engine(url, **kw):
    return _ce(url, poolclass=NullPool, **kw)  # sin pool: cada conexión se cierra de verdad


from tests import pgtemp
from app.failover.external_writers import API_APP_NAME, ReadOnlyViolation, WriteActivityWatch, readonly, scan_external_writers
from app.failover.gate import is_write_statement

pytestmark = pytest.mark.skipif(not pgtemp.available(), reason="initdb/pg_ctl no disponibles")


@pytest.fixture(scope="module")
def cluster():
    c = pgtemp.TempCluster()
    root = create_engine(c.url(), isolation_level="AUTOCOMMIT")
    with root.begin() as conn:
        for stmt in ("CREATE ROLE app LOGIN", "CREATE ROLE owner_r LOGIN", "CREATE ROLE admin_r LOGIN SUPERUSER", "CREATE ROLE bypass_r LOGIN BYPASSRLS", "CREATE ROLE reader LOGIN",
                     "CREATE ROLE monitor LOGIN", "GRANT pg_read_all_stats TO monitor", "CREATE ROLE blind LOGIN", "CREATE DATABASE nexo OWNER owner_r"):
            conn.execute(text(stmt))
    own = create_engine(c.url("nexo", "owner_r"), isolation_level="AUTOCOMMIT")
    with own.begin() as conn:
        conn.execute(text("CREATE TABLE t (id int)")); conn.execute(text("CREATE TABLE alembic_version (version_num text)"))
        conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON t TO app"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO app"))
    yield c
    c.stop()


def ex_for(cluster, user="monitor"):
    eng = create_engine(cluster.url("nexo", user), isolation_level="AUTOCOMMIT")
    def run(sql, params=None):
        with eng.connect() as c:
            r = c.exec_driver_sql(sql, params or {})
            return [tuple(x) for x in r.fetchall()] if r.returns_rows else []
    return run


class Sessions:
    """Mantiene sesiones abiertas (como psql, scripts o la API) y las cierra al terminar."""
    def __init__(self, cluster): self.c, self.open = cluster, []
    def connect(self, user, app_name=None, tx_sql=None, idle_sql=None):
        eng = create_engine(self.c.url("nexo", user, app_name))
        conn = eng.connect(); self.open.append((conn, eng))
        if tx_sql: conn.execute(text(tx_sql))                       # transacción abierta sin commit (idle in transaction)
        elif idle_sql: conn.execute(text(idle_sql)); conn.commit()
        return conn
    def close(self):
        for conn, eng in self.open:
            try: conn.rollback()
            except Exception: pass
            conn.close(); eng.dispose()
        ex = ex_for(self.c, "monitor"); deadline = time.time() + 5
        while time.time() < deadline and ex("SELECT count(*) FROM pg_stat_activity WHERE datname = 'nexo' AND usename NOT IN ('monitor', 'blind') AND pid <> pg_backend_pid()")[0][0]:
            time.sleep(0.05)                                         # el servidor tarda unos ms en retirar las sesiones cerradas


@pytest.fixture
def sessions(cluster):
    s = Sessions(cluster); yield s; s.close()


def scan(cluster, **kw):
    kw.setdefault("app_role", "app")
    return scan_external_writers(ex_for(cluster), **kw)


def snapshot(cluster):
    ex = ex_for(cluster)
    return (ex("SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcanlogin FROM pg_roles ORDER BY 1"),
            ex("SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants WHERE table_schema='public' ORDER BY 1,2,3"))


def test_la_api_etiquetada_no_se_marca_aunque_escriba(cluster, sessions):
    sessions.connect("app", API_APP_NAME, tx_sql="INSERT INTO t VALUES (1)")
    rep = scan(cluster)
    assert not rep.blocks, rep.as_dict()
    assert rep.visibility == "completa"


def test_conexion_directa_con_el_rol_de_la_aplicacion(cluster, sessions):
    sessions.connect("app", None, idle_sql="SELECT 1")                     # psql/script con el MISMO rol pero sin el nombre de la API
    rep = scan(cluster)
    assert "conexion_directa_rol_aplicacion" in rep.kinds("ADVERTENCIA") and not rep.blocks


def test_conexion_directa_escribiendo_bloquea(cluster, sessions):
    sessions.connect("app", "psql", tx_sql="INSERT INTO t VALUES (2)")
    rep = scan(cluster)
    assert rep.blocks and "escritura_fuera_de_la_compuerta" in rep.kinds("BLOQUEA")


def test_propietario_escribiendo_y_migracion_ddl_en_curso(cluster, sessions):
    sessions.connect("owner_r", None, tx_sql="INSERT INTO t VALUES (3)")
    assert "escritura_fuera_de_la_compuerta" in scan(cluster).kinds("BLOQUEA")
    sessions.close(); sessions.open.clear()
    sessions.connect("owner_r", "alembic", tx_sql="ALTER TABLE t ADD COLUMN extra int")
    rep = scan(cluster)
    assert "migracion_o_ddl_en_curso" in rep.kinds("BLOQUEA")
    sessions.close(); sessions.open.clear()
    sessions.connect("owner_r", "alembic", tx_sql="SELECT version_num FROM alembic_version")   # alembic leyendo su tabla de versión = migración en curso
    assert "migracion_o_ddl_en_curso" in scan(cluster).kinds("BLOQUEA")


def test_superusuario_escribiendo_se_detecta(cluster, sessions):
    sessions.connect("admin_r", "psql", tx_sql="INSERT INTO t VALUES (4)")
    assert "escritura_fuera_de_la_compuerta" in scan(cluster).kinds("BLOQUEA")


def test_inventario_de_roles_privilegiados_y_privilegios_de_escritura(cluster):
    own = create_engine(cluster.url("nexo", "owner_r"), isolation_level="AUTOCOMMIT")
    rep = scan(cluster)
    privil = {f.role for f in rep.findings if f.kind == "rol_privilegiado_con_login"}
    assert {"admin_r", "bypass_r", "postgres"} <= privil and "app" not in privil
    assert "propietario_de_las_tablas" in rep.kinds("INFO")
    with own.begin() as c: c.execute(text("GRANT INSERT ON t TO reader"))
    assert "reader" in {f.role for f in scan(cluster).findings if f.kind == "otro_rol_con_privilegios_de_escritura"}
    with own.begin() as c: c.execute(text("GRANT UPDATE ON t TO PUBLIC"))
    rep = scan(cluster); assert "escritura_concedida_a_public" in rep.kinds("BLOQUEA")
    with own.begin() as c: c.execute(text("REVOKE UPDATE ON t FROM PUBLIC")); c.execute(text("REVOKE INSERT ON t FROM reader"))


def test_rol_de_la_aplicacion_privilegiado_bloquea(cluster):
    with create_engine(cluster.url(), isolation_level="AUTOCOMMIT").begin() as c: c.execute(text("ALTER ROLE app BYPASSRLS"))
    try:
        assert "rol_aplicacion_privilegiado" in scan(cluster).kinds("BLOQUEA")
    finally:
        with create_engine(cluster.url(), isolation_level="AUTOCOMMIT").begin() as c: c.execute(text("ALTER ROLE app NOBYPASSRLS"))


def test_visibilidad_parcial_se_declara_y_no_se_oculta(cluster, sessions):
    sessions.connect("owner_r", None, tx_sql="INSERT INTO t VALUES (5)")
    rep = scan_external_writers(ex_for(cluster, "blind"), app_role="app")           # sin pg_read_all_stats: NO ve la sesión del propietario
    assert rep.visibility == "parcial" and "visibilidad_parcial" in rep.kinds("ADVERTENCIA")
    assert "escritura_fuera_de_la_compuerta" not in rep.kinds()                       # y por eso el informe NO puede dar el entorno por limpio


def test_el_detector_es_de_solo_lectura_y_no_cambia_roles_ni_permisos(cluster, sessions):
    sessions.connect("owner_r", None, idle_sql="SELECT 1")
    seen = []
    base = ex_for(cluster)
    def spy(sql, params=None): seen.append(sql); return base(sql, params)
    before = snapshot(cluster)
    scan_external_writers(spy, app_role="app")
    assert seen and not any(is_write_statement(s) for s in seen)
    assert snapshot(cluster) == before
    with pytest.raises(ReadOnlyViolation): readonly(base)("INSERT INTO t VALUES (9)")
    with pytest.raises(ReadOnlyViolation): readonly(base)("ALTER ROLE app SUPERUSER")
    with pytest.raises(ReadOnlyViolation): readonly(base)("GRANT ALL ON t TO PUBLIC")


def test_el_resultado_no_contiene_consultas_ni_direcciones(cluster, sessions):
    sessions.connect("owner_r", "psql", tx_sql="INSERT INTO t VALUES (424242)")
    blob = str(scan(cluster).as_dict())
    assert "424242" not in blob and "INSERT" not in blob and "127.0.0.1" not in blob


def test_roles_tolerados_y_pids_ignorados(cluster, sessions):
    conn = sessions.connect("owner_r", None, tx_sql="INSERT INTO t VALUES (6)")
    pid = conn.exec_driver_sql("SELECT pg_backend_pid()").scalar()
    assert not scan(cluster, tolerated_roles=("owner_r",)).blocks
    assert not scan(cluster, ignore_pids=(pid,)).blocks


def test_actividad_de_escritura_con_la_compuerta_cerrada(cluster):
    time.sleep(1.5)                                                                  # deja que las estadísticas de las pruebas anteriores terminen de volcarse
    w = WriteActivityWatch(ex_for(cluster)); w.mark()
    time.sleep(1.2); assert w.finding() is None                                      # sin escrituras no hay hallazgo
    with create_engine(cluster.url("nexo", "app")).begin() as c: c.execute(text("INSERT INTO t VALUES (7), (8)"))
    deadline = time.time() + 5; f = None
    while time.time() < deadline and f is None:                                      # las estadísticas de PostgreSQL se vuelcan con un pequeño retraso
        time.sleep(0.3); f = w.finding()
    assert f is not None and f.severity == "BLOQUEA" and f.kind == "escrituras_con_la_compuerta_cerrada"
