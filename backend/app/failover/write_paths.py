"""Inventario de RUTAS DE ESCRITURA frente a la compuerta (B-11) y límites declarados. Es código (y tiene pruebas), no documentación: si alguien añade una ruta de escritura, una tarea de
fondo, otro motor de base de datos o una conexión cruda, tests/test_write_gate_coverage.py falla hasta que se revise y se actualice este inventario.

Qué cubre la compuerta (solo con WRITE_GATE_MODE=enforce; con `off`, el valor por defecto, NO se protege nada):
  1. HTTP: todo método no seguro (POST/PUT/PATCH/DELETE) → 503 sin lease válido, antes de llegar a la aplicación (WriteGateMiddleware).
  2. BASE DE DATOS (la capa que importa): un solo `Engine` (app.state.engine, creado en database.build_engine); `before_cursor_execute` rechaza toda sentencia de escritura sin lease válido y
     el COMMIT se comprueba otra vez justo antes de enviarse, tanto con Session (`before_commit`) como sin ella (`engine.begin()`: evento `commit` del Engine). Alcanza a CUALQUIER código que
     use ese motor: rutas GET que escriban, dependencias, tareas, hilos.
Qué NO cubre (límites explícitos, no resueltos):
  - Cualquier productor que NO use ese Engine: scripts de operación y migraciones (KNOWN_EXTERNAL_WRITERS), psql manual, mantenimiento de RDS. Se mitigan operativamente y con el vallado EXTERNO
    de la base (db_fence.py), no con la compuerta.
  - Efectos laterales que no se ven en el texto SQL (`SELECT mi_funcion_que_escribe()`).
  - Una pausa del proceso entre la última comprobación local y la ejecución efectiva en el servidor: ni la compuerta ni el lease pueden impedirlo (solo el margen del lease lo acota).
  - Estado en memoria del proceso (no es una base de datos): se pierde con el proceso y no diverge entre sitios.
"""
from __future__ import annotations

import re
from pathlib import Path

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Productores de escritura FUERA de la aplicación FastAPI (no pasan por la compuerta). Verificado con búsqueda en el repositorio el 17-nov-2026.
KNOWN_EXTERNAL_WRITERS = (
    {"nombre": "migraciones Alembic", "ruta": "backend/alembic + scripts/db-migrate.sh", "rol": "propietario/migración", "mitigacion": "con pg_fence también las rechaza la BASE sin autoridad vigente (y, mientras hay autoridad, necesitan declarar la época: SET nexo.writer_epoch); no se ejecutan en el primario durante un failover; vallado externo (db_fence)"},
    {"nombre": "aprovisionamiento de roles", "ruta": "scripts/provision-database-roles.py", "rol": "administrador", "mitigacion": "operación manual autorizada"},
    {"nombre": "datos de demostración", "ruta": "scripts/seed-demo-catalog.py, update-demo-*.py, add-demo-images.py, reset-local-password.py, dev-bootstrap.py", "rol": "aplicación/propietario", "mitigacion": "solo entornos locales o de ensayo; nunca durante un failover"},
    {"nombre": "verificaciones y cargas cloud", "ruta": "scripts/cloud/verify-controlled-flow.py, verify-login-burst.py, deploy/verify-load-fixture.py", "rol": "migrador", "mitigacion": "ventanas autorizadas; escriben datos ficticios"},
    {"nombre": "laboratorios de replicación", "ruta": "scripts/repl-lab, scripts/failover-lab, scripts/multicloud/oci-drill", "rol": "propias (Docker/VM de ensayo)", "mitigacion": "no apuntan a la base de producción"},
    {"nombre": "administración manual", "ruta": "psql / consola de RDS / mantenimiento de RDS", "rol": "administrador", "mitigacion": "procedimiento; vallado externo de la base"},
)

KNOWN_LIMITS = (
    "WRITE_GATE_MODE=off es el valor por defecto: sin enforce no hay ninguna protección (los despliegues existentes no cambian).",
    "AWS RDS y OCI PostgreSQL son bases independientes: una época o un token en la base de OCI no impide escribir en el RDS; solo el auto-vallado del primario (lease + compuerta) o el vallado externo (db_fence) lo hacen.",
    "Pausa del proceso entre la comprobación y la ejecución en el servidor: con WRITE_GATE_DB_FENCE=require (pg_fence.py) la BASE rechaza al COMMIT, con su reloj, toda transacción sin autoridad vigente; sin pg_fence solo la acota el margen (≥ ρ·ttl).",
    "pg_fence no cubre a un superusuario ni al propietario de las tablas (pueden desactivar triggers o fijar session_replication_role): son accesos de administración, no del rol de la aplicación; sin verificar en RDS.",
    "Funciones SQL con efectos laterales y procedimientos: no se detectan por texto.",
    "El vallado externo (db_fence) requiere alcanzar la base del primario; si está aislada del orquestador, solo queda el auto-vallado.",
)

# Elementos del código de la aplicación que pueden crear escritores fuera de la compuerta: lo esperado hoy (la prueba lo compara con una búsqueda real).
EXPECTED_ENGINE_FILES = {"database.py", "failover/enforce_readiness.py", "failover/gate.py"}   # gate.py: motor del GUARDIÁN del vallado de la base (NullPool; solo ejecuta pg_fence, no escribe datos de negocio)   # el segundo crea solo un SQLite EN MEMORIA para autoprobar la compuerta (no es una base de negocio)
EXPECTED_BACKGROUND_FILES = {"failover/gate.py", "failover/store.py"}   # hilo guardián del lease y autoprueba concurrente del almacén (ninguno escribe en la base de negocio)
EXPECTED_SUBPROCESS_FILES = {"failover/store.py"}   # OciCliStore invoca la CLI de OCI (almacén del lease, no la base de negocio)
_PATTERNS = {
    "engine": re.compile(r"\bcreate_engine\s*\("),
    "raw": re.compile(r"\braw_connection\s*\(|\.driver_connection\b|psycopg\.connect\s*\(|\bconnection\(\)\.connection\b"),
    "background": re.compile(r"\bthreading\.Thread\b|\basyncio\.create_task\b|\bBackgroundTasks\b|\bapscheduler\b|\bcelery\b|\bsched\.scheduler\b|\bThreadPoolExecutor\b|\.run_in_executor\("),
    "subprocess": re.compile(r"\bsubprocess\b|\bos\.system\b"),
}


def scan_app_sources(app_dir: Path) -> dict[str, set[str]]:
    """{categoria: {archivos relativos}} de lo que pueda saltarse la compuerta. Ignora comentarios de línea y cadenas de documentación de una sola línea de forma simple."""
    out: dict[str, set[str]] = {k: set() for k in _PATTERNS}
    for p in sorted(app_dir.rglob("*.py")):
        if "__pycache__" in p.parts or p.name == "write_paths.py":
            continue
        text = "\n".join(l.split("#", 1)[0] for l in p.read_text().splitlines())
        for k, rx in _PATTERNS.items():
            if rx.search(text):
                out[k].add(str(p.relative_to(app_dir)))
    return out


def route_inventory(app) -> list[dict]:
    """Rutas de la aplicación con su clasificación respecto a la compuerta."""
    rows = []
    for r in app.routes:
        methods = set(getattr(r, "methods", None) or [])
        path = getattr(r, "path", getattr(r, "path_format", "?"))
        if not methods:
            rows.append({"ruta": path, "metodos": [], "clase": "montaje/websocket (revisar a mano)"})
            continue
        unsafe = sorted(methods - SAFE_METHODS)
        rows.append({"ruta": path, "metodos": sorted(methods), "clase": "escritura: HTTP 503 sin lease + guardia de BD" if unsafe else "lectura: la guardia de BD rechaza cualquier escritura que haga"})
    return rows
