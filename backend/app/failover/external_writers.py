"""Detector (SOLO LECTURA) de escritores que pueden saltarse la compuerta de escritura durante una operación de failover (B-11). PostgreSQL. Sin secretos en el resultado.

La compuerta solo vigila el proceso de la API. Aquí se mira la BASE DE DATOS desde fuera con consultas de lectura (cada consulta se comprueba con `is_write_statement`: el
detector NO puede escribir ni cambiar roles/permisos) y se informa de:
  - sesiones de la API (rol de la aplicación con application_name de la API: protegidas por la compuerta) frente a sesiones DIRECTAS (psql, scripts, migraciones) con el mismo rol u otros;
  - sesiones de roles privilegiados o propietarios, y si están en una transacción de escritura (backend_xid) o ejecutan DDL/migraciones;
  - inventario de roles con LOGIN y privilegios que podrían saltarse la compuerta (superusuario, BYPASSRLS, CREATEROLE), privilegios de escritura de otros roles y de PUBLIC;
  - actividad de escritura de la base (contadores de pg_stat_user_tables) mientras la compuerta debería estar cerrada (WriteActivityWatch).
No se devuelve texto de consultas (puede contener datos), direcciones IP ni contraseñas: solo clasificaciones.
LÍMITES: sin pg_read_all_stats o superusuario solo se ven las sesiones del propio rol (visibilidad PARCIAL, se informa); el detector ve el INSTANTE de la consulta (una conexión
corta entre dos muestras no se ve); application_name lo fija el cliente (un script puede imitar el de la API): no es autenticación, es una pista; las funciones con efectos
laterales no se detectan por texto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.failover.gate import is_write_statement

API_APP_NAME = "nexoeventos-api"
_DDL = re.compile(r"^\s*(alter|create|drop|truncate|grant|revoke|comment|reindex|vacuum|cluster)\b", re.I)
_MIGRATION_HINT = re.compile(r"alembic|alembic_version", re.I)


class ReadOnlyViolation(Exception):
    pass


def readonly(execute):
    """Envuelve un ejecutor: rechaza cualquier sentencia que pueda escribir (el detector es de solo lectura por construcción)."""
    def run(sql, params=None):
        if is_write_statement(sql):
            raise ReadOnlyViolation("el detector de escritores externos solo puede ejecutar consultas de lectura")
        return execute(sql, params)
    return run


@dataclass
class Finding:
    severity: str        # BLOQUEA | ADVERTENCIA | INFO
    kind: str
    detail: str
    role: str | None = None


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    visibility: str = "completa"

    @property
    def blocks(self) -> bool:
        return any(f.severity == "BLOQUEA" for f in self.findings)

    def kinds(self, severity: str | None = None) -> set[str]:
        return {f.kind for f in self.findings if severity in (None, f.severity)}

    def as_dict(self) -> dict:
        return {"visibilidad": self.visibility, "bloquea": self.blocks, "hallazgos": [f.__dict__ for f in self.findings]}


def _classify_query(query: str | None) -> str:
    q = (query or "").strip()
    if not q:
        return "vacia"
    if _DDL.match(q) or _MIGRATION_HINT.search(q):
        return "ddl"
    return "escritura" if is_write_statement(q) else "lectura"


def scan_external_writers(execute, *, app_role: str, app_name: str = API_APP_NAME, tolerated_roles: tuple[str, ...] = (), ignore_pids: tuple[int, ...] = ()) -> Report:
    """`execute(sql, params=None) -> list[tuple]` con un rol de MONITOREO (idealmente pg_read_all_stats; no hace falta que escriba). Solo lecturas."""
    ex = readonly(execute)
    rep = Report()
    visible = ex("SELECT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) OR pg_has_role(current_user, 'pg_read_all_stats', 'member')")[0][0]
    if not visible:
        rep.visibility = "parcial"
        rep.findings.append(Finding("ADVERTENCIA", "visibilidad_parcial", "el rol de monitoreo no tiene pg_read_all_stats: solo ve sus propias sesiones; no se pueden descartar otros escritores"))

    # 1) sesiones
    rows = ex("SELECT pid, usename, application_name, state, (backend_xid IS NOT NULL) AS escribiendo, query FROM pg_stat_activity "
              "WHERE datname = current_database() AND backend_type = 'client backend' AND pid <> pg_backend_pid()")
    for pid, user, app, state, in_write_tx, query in rows:
        if pid in ignore_pids or user is None:
            continue
        qk = _classify_query(query)
        writing = bool(in_write_tx) or qk in ("escritura", "ddl")
        if user == app_role and app == app_name:
            continue                                                              # la API: protegida por la compuerta
        if user in tolerated_roles:
            rep.findings.append(Finding("INFO", "rol_tolerado", f"sesión de un rol tolerado ({'escribiendo' if writing else 'sin escribir'})", user)); continue
        direct = "conexion_directa_rol_aplicacion" if user == app_role else "sesion_rol_no_aplicacion"
        who = "rol de la aplicación SIN el application_name de la API (psql/script/otro proceso)" if user == app_role else "rol distinto del de la aplicación (propietario, migración o administrador)"
        if qk == "ddl":
            rep.findings.append(Finding("BLOQUEA", "migracion_o_ddl_en_curso", f"{who} ejecutando DDL/migración: no pasa por la compuerta", user))
        elif writing:
            rep.findings.append(Finding("BLOQUEA", "escritura_fuera_de_la_compuerta", f"{who} en una transacción de escritura (estado {state})", user))
        else:
            rep.findings.append(Finding("ADVERTENCIA", direct, f"{who}: sesión abierta sin escribir en este instante ({state})", user))

    # 2) roles privilegiados con LOGIN (inventario: no prueba uso, indica quién PODRÍA saltarse la compuerta)
    for role, sup, byp, crt in ex("SELECT rolname, rolsuper, rolbypassrls, rolcreaterole FROM pg_roles WHERE rolcanlogin AND rolname !~ '^pg_' ORDER BY 1"):
        if role == app_role:
            if sup or byp or crt:
                rep.findings.append(Finding("BLOQUEA", "rol_aplicacion_privilegiado", "el rol de la APLICACIÓN es superusuario/BYPASSRLS/CREATEROLE: el principio de mínimo privilegio no se cumple", role))
            continue
        if sup or byp or crt:
            flags = ",".join(n for n, v in (("superusuario", sup), ("bypassrls", byp), ("createrole", crt)) if v)
            rep.findings.append(Finding("ADVERTENCIA", "rol_privilegiado_con_login", f"puede escribir sin pasar por la compuerta si alguien lo usa ({flags})", role))

    # 3) privilegios de escritura de otros roles (incluye PUBLIC) sobre las tablas del esquema public
    seen = set()
    # pg_class/aclexplode (visible para cualquier rol; information_schema solo muestra lo que el rol actual puede ver). Se excluye al propietario: ya se informa aparte.
    for grantee, table, priv in ex("SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END, c.relname, a.privilege_type FROM pg_class c "
                                   "JOIN pg_namespace n ON n.oid = c.relnamespace, LATERAL aclexplode(c.relacl) a WHERE n.nspname = 'public' AND c.relkind IN ('r','p') "
                                   "AND a.privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE') AND a.grantee <> c.relowner ORDER BY 1, 2, 3"):
        if grantee == app_role or (grantee, "w") in seen:
            continue
        seen.add((grantee, "w"))
        if grantee == "PUBLIC":
            rep.findings.append(Finding("BLOQUEA", "escritura_concedida_a_public", "PUBLIC tiene privilegios de escritura: cualquier rol puede escribir", "PUBLIC"))
        else:
            rep.findings.append(Finding("ADVERTENCIA", "otro_rol_con_privilegios_de_escritura", "tiene privilegios de escritura sobre tablas de la aplicación", grantee))
    for (owner,) in ex("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"):
        if owner != app_role:
            rep.findings.append(Finding("INFO", "propietario_de_las_tablas", "los propietarios pueden alterar el esquema (migraciones Alembic): fuera de la compuerta", owner))
    return rep


class WriteActivityWatch:
    """Detecta escrituras en la base mientras la compuerta DEBERÍA estar cerrada (por ejemplo, desde que se perdió el lease hasta que se confirma el nuevo escritor).
    Compara los contadores acumulados de pg_stat_user_tables (inserciones+actualizaciones+borrados) entre `mark()` y `delta()`."""
    def __init__(self, execute):
        self.ex = readonly(execute); self._base: int | None = None

    def _total(self) -> int:
        return int(self.ex("SELECT coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) FROM pg_stat_user_tables")[0][0])

    def mark(self) -> None:
        self._base = self._total()

    def delta(self) -> int:
        if self._base is None:
            raise ReadOnlyViolation("falta mark()")
        return self._total() - self._base

    def finding(self) -> Finding | None:
        d = self.delta()
        return Finding("BLOQUEA", "escrituras_con_la_compuerta_cerrada", f"la base registró {d} filas escritas mientras la compuerta debía estar cerrada") if d > 0 else None
