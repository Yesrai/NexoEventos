"""Compuerta de escritura que FALLA CERRADA, controlada por el lease (B-11).

DESACTIVADA por defecto (WRITE_GATE_MODE=off → el comportamiento de producción no cambia en absoluto). Con WRITE_GATE_MODE=enforce:
  1. Capa HTTP: toda petición que NO sea GET/HEAD/OPTIONS recibe 503 si este proceso no tiene un lease válido (comprobación LOCAL con reloj monótono, sin red).
  2. Capa de BD (la que importa): cada sentencia que modifica datos (INSERT/UPDATE/DELETE/DDL…) se rechaza si el lease no es válido, y se comprueba DE NUEVO justo
     antes del COMMIT: si el lease caducó mientras se atendía la petición, el commit se aborta (no se persiste nada). Cubre escrituras que no pasan por las rutas HTTP.
  3. Un hilo «guardián» renueva el lease; si el hilo muere o la red falla, el lease caduca solo y las escrituras se detienen (falla cerrada).
Rol `primary`: intenta adquirir el lease. Rol `standby`: NO adquiere salvo que exista el archivo de promoción (WRITE_GATE_PROMOTE_FILE), que crea el orquestador (B-13) tras
vallar al escritor anterior; si el archivo desaparece, libera el lease y deja de escribir.
LIMITACIONES (no se declara seguro el failover entre nubes): una pausa del proceso entre la última comprobación y la escritura efectiva, una deriva de reloj mayor que la
supuesta, o un almacén de lease no verificado pueden permitir dos escritores. Además, AWS y OCI NO comparten base de datos: el lease evita que ambas acepten escrituras a la vez,
pero no reconcilia datos divergentes ni protege contra una partición total del almacén (en ese caso NADIE escribe: se elige consistencia sobre disponibilidad).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid

from sqlalchemy import event

from .lease import LeaseClient, LeaseConfig
from .store import FileStore, OciCliStore, verify_store_semantics

logger = logging.getLogger("nexoeventos.writegate")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_WRITE_SQL = re.compile(r"\b(insert|update|delete|merge|truncate|alter|create|drop|grant|revoke|copy|vacuum|reindex|cluster|comment|lock)\b", re.I)
_STRIP = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", re.S)


class WriteFenceError(RuntimeError):
    """Se intentó escribir sin un lease válido."""


def is_write_statement(sql: str) -> bool:
    """Conservador (falla cerrada): cualquier verbo de modificación fuera de literales y comentarios cuenta como escritura (incluye `FOR UPDATE`)."""
    return bool(_WRITE_SQL.search(_STRIP.sub(" ", sql)))


class WriteGate:
    def __init__(self, lease: LeaseClient, role: str = "primary", promote_file: str | None = None, allow_paths: frozenset[str] = frozenset(), keeper_interval_s: float | None = None):
        if role not in {"primary", "standby"}:
            raise ValueError("WRITE_GATE_ROLE debe ser primary o standby")
        self.lease, self.role, self.promote_file, self.allow_paths = lease, role, promote_file, allow_paths
        self.interval = keeper_interval_s or lease.config.renew_interval_s
        self._stop = threading.Event(); self._thread: threading.Thread | None = None
        self.blocked_http = 0; self.blocked_sql = 0; self.blocked_commit = 0

    # --- decisión (local, sin red)
    def allows_writes(self) -> bool:
        return self.lease.is_valid()

    def status(self) -> dict:
        s = self.lease.status()
        return {"mode": "enforce", "role": self.role, "holds_lease": s["valid"], "epoch": s["epoch"], "remaining_s": s["remaining_s"], "lost": s["lost"],
                "blocked": {"http": self.blocked_http, "sql": self.blocked_sql, "commit": self.blocked_commit}}

    # --- guardián
    def keeper_step(self) -> None:
        """Un paso del guardián (también lo usan las pruebas, sin hilos)."""
        wants = self.role == "primary" or bool(self.promote_file and os.path.exists(self.promote_file))
        if not wants:
            if self.lease._etag is not None and not self.lease._lost:
                self.lease.release()                      # standby sin promoción: no debe retener el lease
            return
        if self.lease._etag is not None and not self.lease._lost:
            self.lease.renew()
        else:
            self.lease.acquire()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        def run():
            while not self._stop.wait(self.interval):
                try:
                    self.keeper_step()
                except Exception:                          # nunca matar el hilo por un error: si algo falla, el lease caduca solo
                    logger.exception("Error en el guardián del lease (el lease caducará si no se renueva)")
        self._thread = threading.Thread(target=run, name="write-gate-keeper", daemon=True); self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread: self._thread.join(timeout=2)
        try:
            self.lease.release()
        except Exception:
            pass


class WriteGateMiddleware:
    """Middleware ASGI puro: rechaza métodos no seguros sin lease válido, antes de llegar a la aplicación."""

    def __init__(self, app, gate: WriteGate):
        self.app, self.gate = app, gate

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS and scope["path"] not in self.gate.allow_paths and not self.gate.allows_writes():
            self.gate.blocked_http += 1
            body = json.dumps({"detail": "Escritura no permitida en esta instancia (sin lease de escritor)", "code": "write_gate_closed"}).encode()
            await send({"type": "http.response.start", "status": 503, "headers": [(b"content-type", b"application/json"), (b"retry-after", b"5"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def install_db_guard(engine, session_factory, gate: WriteGate) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def _before_execute(conn, cursor, statement, parameters, context, executemany):
        if is_write_statement(statement):
            if not gate.allows_writes():
                gate.blocked_sql += 1
                raise WriteFenceError("sentencia de escritura rechazada: sin lease válido")
            conn.info["gate_wrote"] = True

    @event.listens_for(session_factory, "before_commit")
    def _before_commit(session):
        conn = session.connection()
        if conn.info.get("gate_wrote") and not gate.allows_writes():
            gate.blocked_commit += 1
            raise WriteFenceError("commit abortado: el lease caducó durante la petición")

    @event.listens_for(session_factory, "after_commit")
    @event.listens_for(session_factory, "after_rollback")
    def _reset(session):
        try:
            session.connection().info.pop("gate_wrote", None)
        except Exception:
            pass


def install_write_gate(application, engine, session_factory, gate: WriteGate) -> None:
    from fastapi.responses import JSONResponse
    application.add_middleware(WriteGateMiddleware, gate=gate)
    install_db_guard(engine, session_factory, gate)
    application.state.write_gate = gate

    @application.exception_handler(WriteFenceError)
    async def _fence(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Escritura no permitida en esta instancia (sin lease de escritor)", "code": "write_gate_closed"}, headers={"Retry-After": "5"})

    @application.get("/write-gate")
    async def write_gate_status() -> dict:
        s = gate.status()
        return {k: s[k] for k in ("mode", "role", "holds_lease", "epoch", "remaining_s")}


def build_gate_from_env(environ=None) -> WriteGate | None:
    """None si WRITE_GATE_MODE=off (valor por defecto). Una configuración inválida lanza RuntimeError al ARRANCAR (nunca se degrada en silencio)."""
    env = os.environ if environ is None else environ
    mode = env.get("WRITE_GATE_MODE", "off").strip().lower()
    if mode == "off":
        return None
    if mode != "enforce":
        raise RuntimeError("WRITE_GATE_MODE debe ser off o enforce")
    kind = env.get("WRITE_GATE_STORE", "").strip().lower()
    app_env = env.get("APP_ENV", "development").strip().lower()
    holder = env.get("WRITE_GATE_HOLDER_ID") or f"{env.get('HOSTNAME', 'nodo')}-{uuid.uuid4().hex[:6]}"
    cfg = LeaseConfig(ttl_s=float(env.get("WRITE_GATE_TTL_S", "15")), margin_s=float(env.get("WRITE_GATE_MARGIN_S", "5")))
    if kind == "file":
        if app_env == "production":
            raise RuntimeError("WRITE_GATE_STORE=file es solo para pruebas locales: no se permite con APP_ENV=production")
        path = env.get("WRITE_GATE_FILE_PATH")
        if not path:
            raise RuntimeError("falta WRITE_GATE_FILE_PATH")
        store = FileStore(path)
        verify_store_semantics(lambda: FileStore(f"{path}.selftest-{uuid.uuid4().hex[:6]}"))
        store.verified = True
    elif kind == "oci-cli":
        ns, bucket, obj = env.get("WRITE_GATE_OCI_NAMESPACE"), env.get("WRITE_GATE_OCI_BUCKET"), env.get("WRITE_GATE_OCI_OBJECT", "writer-lease.json")
        if not (ns and bucket):
            raise RuntimeError("faltan WRITE_GATE_OCI_NAMESPACE / WRITE_GATE_OCI_BUCKET")
        profile = env.get("WRITE_GATE_OCI_PROFILE", "NEXOEVENTOS_LEASE")
        store = OciCliStore(ns, bucket, obj, profile)
        if env.get("WRITE_GATE_SELFTEST", "1") == "1":                       # autoprueba contra el almacén REAL antes de aceptar escrituras (objeto de prueba exclusivo)
            rep = verify_store_semantics(lambda: OciCliStore(ns, bucket, f"{obj}.selftest-{uuid.uuid4().hex[:8]}", profile))
            if not all(rep.values()):
                raise RuntimeError(f"el almacén del lease NO pasó la autoprueba de escrituras condicionales: {rep}")
            store.verified = True
    else:
        raise RuntimeError("WRITE_GATE_STORE debe ser file u oci-cli")
    lease = LeaseClient(store, cfg, holder_id=holder)
    return WriteGate(lease, role=env.get("WRITE_GATE_ROLE", "primary"), promote_file=env.get("WRITE_GATE_PROMOTE_FILE"))
