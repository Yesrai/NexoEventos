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
import time
import uuid

from sqlalchemy import event

from .lease import LeaseClient, LeaseConfig, pause_budget_s
from .store import FileStore, OciCliStore, build_verified_par_store, verify_store_semantics

logger = logging.getLogger("nexoeventos.writegate")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Conservador (falla cerrada). Además de los verbos DML/DDL: CALL/DO/EXECUTE (código que puede escribir sin verlo en el texto), nextval/setval (avanzan secuencias, un efecto
# que NO se revierte con ROLLBACK), `INTO` (SELECT … INTO crea tablas) y NOTIFY. Un nombre de función con efectos laterales arbitrario (SELECT mi_funcion()) NO se puede detectar
# por texto: es una limitación conocida (ver write_paths.KNOWN_LIMITS).
_WRITE_SQL = re.compile(r"\b(insert|update|delete|merge|truncate|alter|create|drop|grant|revoke|copy|vacuum|reindex|cluster|comment|lock|call|do|execute|nextval|setval|into|notify|refresh)\b", re.I)
_STRIP = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", re.S)


class WriteOutcomeUnknown(RuntimeError):
    """El COMMIT volvió DESPUÉS de perderse la autoridad con la que empezó la transacción: pudo terminar tras el vencimiento. NO se reconoce éxito al cliente (resultado desconocido); la transacción, si se
    aplicó, es huérfana y se descarta en el failback (late_commits)."""


class WriteFenceError(RuntimeError):
    """Se intentó escribir sin un lease válido."""


def is_write_statement(sql: str) -> bool:
    """Conservador (falla cerrada): cualquier verbo de modificación fuera de literales y comentarios cuenta como escritura (incluye `FOR UPDATE`)."""
    return bool(_WRITE_SQL.search(_STRIP.sub(" ", sql)))


class WriteGate:
    def __init__(self, lease: LeaseClient, role: str = "primary", promote_file: str | None = None, allow_paths: frozenset[str] = frozenset(), keeper_interval_s: float | None = None,
                 db_fence=None, attestation=None, attest_every_s: float = 5.0, clock_tolerance_s: float | None = None, attach_every_s: float = 10.0, clock_abs_tolerance_s: float | None = None, election=None):
        if role not in {"primary", "standby"}:
            raise ValueError("WRITE_GATE_ROLE debe ser primary o standby")
        self.lease, self.role, self.promote_file, self.allow_paths = lease, role, promote_file, allow_paths
        # Varias instancias del MISMO sitio (site_member.py): solo la líder (bloqueo consultivo en PostgreSQL) habla con el lease entre nubes; las demás son miembros y reciben la autoridad que la BASE ya tiene
        # concedida (fence_status). Sin `election` el comportamiento es el de siempre (una instancia por sitio).
        self.election, self.own_lease, self.delegated, self.site_member_cycles = election, lease, None, 0
        if election is not None:
            if db_fence is None:
                raise ValueError("la elección de líder del sitio exige el vallado en la base (la autoridad de los miembros sale de la base)")
            from .site_member import DelegatedLease
            self.delegated = DelegatedLease(lease.holder_id, lease.config)
        # Vallado EN LA BASE (pg_fence.py): `db_fence` = PgFence con las credenciales del GUARDIÁN. La autoridad de la base se concede SOLO tras renovar el lease y caduca sola (reloj de la base) si
        # esta sincronización falla; `attestation` (FenceAttestation) publica periódicamente la cobertura del vallado para que el sitio de recuperación la lea aunque este primario quede aislado.
        self.db_fence, self.attestation, self.attest_every_s = db_fence, attestation, attest_every_s
        self._fence_epoch: int | None = None; self._last_attest = 0.0; self.db_sync_errors = 0; self.last_db_sync_ok: bool | None = None
        # Guardia del RELOJ de la base: entre dos concesiones, lo que avanza el reloj de la base debe coincidir (± tolerancia) con lo que avanza el monótono local; si no, la base (o el nodo) saltó
        # de hora: se REVOCA la autoridad y no se vuelve a conceder hasta observar `clock_ok_needed` intervalos sanos. Evita que un salto hacia atrás alargue la autoridad más allá del lease.
        self.clock_tolerance_s = clock_tolerance_s if clock_tolerance_s is not None else max(lease.config.margin_s / 2.0, 0.25)
        self.clock_abs_tolerance_s = clock_abs_tolerance_s if clock_abs_tolerance_s is not None else max(self.clock_tolerance_s, 0.25)
        self._last_clock: tuple[float, float] | None = None; self.clock_anomalies = 0; self._clock_hold = 0; self.clock_ok_needed = 2
        self.attach_every_s = attach_every_s; self._last_attach = 0.0
        self.db_latched = False          # la base está CERROJADA (vallado fuerte tras una promoción): esta instancia NO vuelve a competir por el lease hasta el failback manual
        self.interval = keeper_interval_s or lease.config.renew_interval_s
        self._stop = threading.Event(); self._thread: threading.Thread | None = None
        self.blocked_http = 0; self.blocked_sql = 0; self.blocked_commit = 0; self.unacknowledged = 0

    def is_site_member(self) -> bool:
        return self.election is not None and self.lease is self.delegated

    def _refresh_delegation(self) -> None:
        """MIEMBRO: toma la autoridad de la base (solo lectura con las credenciales del guardián); nunca concede ni toca el lease entre nubes. Con salto de reloj de la base, se retira."""
        t_send = time.monotonic()
        try:
            st = self.db_fence.status()
            if st and st.get("db_now") is not None and not self._clock_ok(st["db_now"]):
                self.delegated.invalidate(); self.last_db_sync_ok = False; return
            self.delegated.update(st, t_send); self.last_db_sync_ok = True
        except Exception:  # noqa: BLE001 — sin consulta no se amplía nada: la delegación caduca sola
            self.db_sync_errors += 1; self.last_db_sync_ok = False
            logger.warning("miembro del sitio: no se pudo leer la autoridad de la base (la delegación caducará sola)")

    # --- decisión (local, sin red)
    def allows_writes(self) -> bool:
        return self.lease.is_valid()

    def ack_ok(self, begin_epoch) -> bool:
        """BARRERA DE RECONOCIMIENTO: ¿el COMMIT volvió con la MISMA autoridad con la que empezó y aún vigente? Si volvió dentro del plazo, terminó dentro del plazo (el servidor termina antes de responder): ninguna
        confirmación reconocida puede solaparse con la autoridad de otro nodo, aunque el servidor se haya pausado más que cualquier presupuesto. Si no, el resultado es desconocido y no se reconoce."""
        return bool(begin_epoch) and self.lease.is_valid() and self.lease._epoch == begin_epoch

    def status(self) -> dict:
        s = self.lease.status()
        out = {"mode": "enforce", "role": self.role, "lease_tamper_events": s.get("tamper_events", 0), "pause_budget_s": round(pause_budget_s(self.lease.config.ttl_s, self.lease.config.margin_s, self.lease.config.drift_ppm_assumed / 1e6), 3), "holds_lease": s["valid"], "epoch": s["epoch"], "remaining_s": s["remaining_s"], "lost": s["lost"],
               "blocked": {"http": self.blocked_http, "sql": self.blocked_sql, "commit": self.blocked_commit, "unacknowledged": self.unacknowledged}}
        if self.election is not None:
            out["site"] = {"leader": self.election.is_leader, "member": self.is_site_member()}
        if self.db_fence is not None:
            out["db_fence"] = {"enabled": True, "latched": self.db_latched, "last_sync_ok": self.last_db_sync_ok, "sync_errors": self.db_sync_errors, "clock_anomalies": self.clock_anomalies}
        return out

    def _clock_ok(self, db_now) -> bool:
        """¿Avanzó el reloj de la base lo mismo que el monótono local desde la última observación (± tolerancia)?"""
        d_now, d_mono = db_now.timestamp(), time.monotonic()
        prev, self._last_clock = self._last_clock, (d_now, d_mono)
        # Desfase ABSOLUTO: un reloj de la base que quedó corrido (tras un salto ya ocurrido) no se ve comparando solo intervalos, pero alarga o acorta la autoridad real en esa cantidad.
        if abs(d_now - time.time()) > self.clock_abs_tolerance_s:
            self.clock_anomalies += 1
            return False
        if prev is None:
            return True
        if abs((d_now - prev[0]) - (d_mono - prev[1])) > self.clock_tolerance_s:
            self.clock_anomalies += 1
            return False
        return True

    def _sync_db(self) -> None:
        """Refleja el lease en la base: con lease válido concede/renueva la autoridad por el tiempo que le QUEDA (reloj de la base); sin él, la revoca. Un fallo NO amplía nada: la base caduca sola.
        Además: guardia del reloj, enganche periódico de tablas nuevas (sin event trigger) y publicación de la atestación en CADA ciclo (cobertura real, no una foto vieja)."""
        if self.db_fence is None:
            return
        if self.is_site_member():
            self._refresh_delegation(); return
        try:
            now_m = time.monotonic()
            if hasattr(self.db_fence, "attach_all") and now_m - self._last_attach >= self.attach_every_s:
                self._last_attach = now_m
                try:
                    self.db_fence.attach_all()
                except Exception:  # noqa: BLE001 — si no puede, la cobertura queda incompleta y la base NO concederá autoridad
                    logger.exception("attach_all falló (las tablas nuevas quedarían sin cubrir)")
                if hasattr(self.db_fence, "prune_commit_log"):
                    try:
                        self.db_fence.prune_commit_log()
                    except Exception:  # noqa: BLE001
                        logger.warning("no se pudo podar el registro de commits (no afecta a la seguridad)")
            if self._clock_hold > 0:                                  # tras un salto del reloj: se OBSERVA sin conceder hasta ver intervalos sanos
                st = self.db_fence.status() if hasattr(self.db_fence, "status") else None
                if st and st.get("db_now") is not None and self._clock_ok(st["db_now"]):
                    self._clock_hold -= 1
                self.last_db_sync_ok = False
                return
            if self.lease.is_valid() and self.lease.remaining_s() > 0.05:
                self._fence_epoch = self.lease.epoch
                g = self.db_fence.grant(self.lease.epoch, self.lease.holder_id, self.lease.remaining_s())
                dbn = g.get("db_now") if isinstance(g, dict) else None
                if dbn is not None and not self._clock_ok(dbn):
                    logger.error("Salto del reloj de la base detectado: se REVOCA la autoridad")
                    self.db_fence.revoke(self._fence_epoch)               # la ventana extra es solo el tiempo del RPC
                    self._clock_hold = self.clock_ok_needed; self.last_db_sync_ok = False
                    return
            elif self._fence_epoch is not None:
                self.db_fence.revoke(self._fence_epoch)
            self.last_db_sync_ok = True
        except Exception as e:  # noqa: BLE001 — la base no se amplía: su autorización caduca sola
            if "CERROJADA" in str(e):
                self.db_latched = True
                logger.critical("La base está CERROJADA por un vallado fuerte (promoción): esta instancia deja de competir por el lease hasta el failback manual")
                try: self.lease.release()
                except Exception: pass
            self.db_sync_errors += 1; self.last_db_sync_ok = False
            logger.exception("No se pudo sincronizar el vallado de la base (su autoridad caducará sola)")
        if self.attestation is not None and time.monotonic() - self._last_attest >= self.attest_every_s:
            self._last_attest = time.monotonic()
            try:
                self.attestation.publish(self.db_fence.attest(), self._fence_epoch)
            except Exception:  # noqa: BLE001 — sin publicar, la atestación envejece y deja de valer
                logger.exception("No se pudo publicar la atestación del vallado")

    # --- guardián
    def keeper_step(self) -> None:
        """Un paso del guardián (también lo usan las pruebas, sin hilos)."""
        wants = self.role == "primary" or bool(self.promote_file and os.path.exists(self.promote_file))
        if self.election is not None and not self.db_latched:
            leader = wants and self.election.step()
            if not wants: self.election.resign()
            if leader:
                self.lease = self.own_lease; self.delegated.invalidate()
            else:
                if self.own_lease._etag is not None and not self.own_lease._lost:
                    self.own_lease.release()              # dejó de ser líder: no retiene el lease entre nubes
                self.lease = self.delegated; self.site_member_cycles += 1
                self._sync_db(); return                    # miembro: solo refresca la autoridad delegada por la base
        if self.db_latched:
            self._sync_db(); return                       # cerrojo: ni adquirir ni renovar (el failback es manual y levanta el cerrojo en la base y reinicia la instancia)
        if not wants:
            if self.lease._etag is not None and not self.lease._lost:
                self.lease.release()                      # standby sin promoción: no debe retener el lease
            self._sync_db()                               # sin promoción: la base queda SIN autoridad (solo lectura efectiva)
            return
        if self.lease._etag is not None and not self.lease._lost:
            self.lease.renew()
        else:
            self.lease.acquire()
        self._sync_db()

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
        if self.election is not None: self.election.resign()
        try:
            self.lease.release()
        except Exception:
            pass
        if self.db_fence is not None and self._fence_epoch is not None:
            try:
                self.db_fence.revoke(self._fence_epoch)
            except Exception:  # noqa: BLE001
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
    @event.listens_for(engine, "begin")
    def _reset_ack(conn):
        conn.info.pop("gate_begin_epoch", None); conn.info.pop("gate_wrote_ack", None)          # estado de la barrera: por transacción

    if gate.db_fence is not None:
        @event.listens_for(engine, "begin")
        def _claim_epoch(conn):
            """Cada transacción declara a la BASE la época de SU lease (0 si no lo tiene): la base la compara con la suya al COMMIT (pg_fence.py)."""
            conn.exec_driver_sql("SELECT set_config('nexo.writer_epoch', %s, true)", (str(gate.lease.epoch or 0),))

    @event.listens_for(engine, "before_cursor_execute")
    def _before_execute(conn, cursor, statement, parameters, context, executemany):
        if is_write_statement(statement):
            if not gate.allows_writes():
                gate.blocked_sql += 1
                raise WriteFenceError("sentencia de escritura rechazada: sin lease válido")
            conn.info["gate_wrote"] = True
            conn.info["gate_wrote_ack"] = True                                                    # (gate_wrote lo borra el evento commit ANTES del COMMIT; este lo lee la barrera DESPUÉS)
            conn.info.setdefault("gate_begin_epoch", gate.lease._epoch if gate.lease.is_valid() else None)

    @event.listens_for(session_factory, "before_commit")
    def _before_commit(session):
        conn = session.connection()
        session.info["gate_ack"] = (conn.info.get("gate_wrote_ack"), conn.info.get("gate_begin_epoch"))     # la barrera lo lee tras el COMMIT (session.connection() allí abriría otra transacción)
        if conn.info.get("gate_wrote") and not gate.allows_writes():
            gate.blocked_commit += 1
            raise WriteFenceError("commit abortado: el lease caducó durante la petición")

    @event.listens_for(engine, "commit")
    def _engine_commit(conn):
        """Ruta SIN Session (engine.begin(), conexiones directas): el COMMIT también se comprueba justo antes de enviarse a la base."""
        wrote = conn.info.get("gate_wrote")
        if wrote and not gate.allows_writes():
            gate.blocked_commit += 1
            raise WriteFenceError("commit abortado: el lease caducó durante la operación")
        conn.info.pop("gate_wrote", None)

    @event.listens_for(engine, "rollback")
    def _engine_rollback(conn):
        conn.info.pop("gate_wrote", None)

    @event.listens_for(session_factory, "after_commit")
    def _ack_barrier(session):
        """Tras volver el COMMIT: si la autoridad con la que empezó ya no está intacta, NO se reconoce el éxito (la transacción pudo terminar tras el vencimiento)."""
        wrote, begin = session.info.pop("gate_ack", (None, None))
        if wrote and not gate.ack_ok(begin):
            gate.unacknowledged += 1
            raise WriteOutcomeUnknown("resultado desconocido: la autoridad se perdió durante el commit")

    @event.listens_for(session_factory, "after_rollback")
    def _reset(session):
        try:
            i = session.connection().info
            i.pop("gate_wrote", None); i.pop("gate_begin_epoch", None); i.pop("gate_wrote_ack", None)
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

    @application.exception_handler(WriteOutcomeUnknown)
    async def _unknown(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Resultado desconocido: se perdió la autoridad de escritura durante la operación; verifique antes de reintentar", "code": "write_outcome_unknown"}, headers={"Retry-After": "5"})

    @application.get("/write-gate")
    async def write_gate_status() -> dict:
        s = gate.status()
        return {k: s[k] for k in ("mode", "role", "holds_lease", "epoch", "remaining_s")}


def _load_lease_auth_keys(env) -> dict | None:
    """Claves HMAC por titular ({"aws": "<hex>", "oci": "<hex>"}) en un archivo 0600. Con ellas, ningún registro del lease se acepta por su contenido (liberaciones, «soy el titular», ttl): ver lease.py."""
    path = env.get("WRITE_GATE_LEASE_AUTH_KEYS_FILE")
    if not path:
        return None
    st = os.stat(path)
    if st.st_mode & 0o077:
        raise RuntimeError("WRITE_GATE_LEASE_AUTH_KEYS_FILE debe tener permisos 0600")
    try:
        raw = json.loads(open(path).read()); keys = {str(k): bytes.fromhex(v) for k, v in raw.items()}
    except (ValueError, TypeError, AttributeError):
        raise RuntimeError("WRITE_GATE_LEASE_AUTH_KEYS_FILE ilegible (se espera JSON {titular: clave hexadecimal})")
    if len(keys) < 2 or any(len(k) < 16 for k in keys.values()):
        raise RuntimeError("se exigen al menos 2 titulares con claves de ≥ 16 bytes")
    return keys


def _load_lease_authenticator(env, holder: str):
    """Ed25519 (recomendado): WRITE_GATE_LEASE_SIGNING_KEY_FILE (clave PRIVADA de ESTE nodo, base64, 0600) + WRITE_GATE_LEASE_PEER_PUBKEYS_FILE (JSON {titular: [clave pública base64, ...]}, no secreto)."""
    import base64
    kf, pf = env.get("WRITE_GATE_LEASE_SIGNING_KEY_FILE"), env.get("WRITE_GATE_LEASE_PEER_PUBKEYS_FILE")
    if not kf and not pf:
        return None
    if not (kf and pf):
        raise RuntimeError("faltan WRITE_GATE_LEASE_SIGNING_KEY_FILE o WRITE_GATE_LEASE_PEER_PUBKEYS_FILE (se exigen ambos)")
    if os.stat(kf).st_mode & 0o077:
        raise RuntimeError("WRITE_GATE_LEASE_SIGNING_KEY_FILE debe tener permisos 0600")
    from .lease import Ed25519Auth
    try:
        priv = base64.b64decode(open(kf).read().strip(), validate=True)
        raw = json.loads(open(pf).read()); peers = {str(h): [base64.b64decode(k, validate=True) for k in (v if isinstance(v, list) else [v])] for h, v in raw.items()}
        auth = Ed25519Auth(holder, priv, peers)
    except Exception:  # noqa: BLE001 — nunca se imprime el contenido de las claves
        raise RuntimeError("claves del lease ilegibles o inválidas (se espera Ed25519 en base64)")
    if len([h for h in peers if h != holder]) < 1:
        raise RuntimeError("faltan las claves públicas del otro titular")
    return auth


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
    elif kind == "par-http":
        par_file = env.get("WRITE_GATE_PAR_URL_FILE")
        if not par_file:
            raise RuntimeError("falta WRITE_GATE_PAR_URL_FILE (archivo 0600 con la URL del PAR de lectura/escritura del bucket del lease; acaba en «/o/»)")
        obj = env.get("WRITE_GATE_OCI_OBJECT", "writer-lease.json")
        # La autoprueba de If-Match / If-None-Match es OBLIGATORIA (no hay variable para omitirla): un servicio que las ignora haría que dos instancias crean tener el lease.
        try:
            store, rep = build_verified_par_store(par_file, obj, allow_http_localhost=env.get("WRITE_GATE_ALLOW_HTTP_LOCALHOST") == "1" and app_env != "production")
        except Exception as e:  # noqa: BLE001 — URL inválida, permisos del archivo, etc.: se rechaza al arrancar, sin imprimir la URL
            raise RuntimeError(f"almacén par-http inválido ({type(e).__name__})")
        if not store.verified:
            raise RuntimeError(f"el almacén del lease NO pasó la autoprueba de escrituras condicionales: {rep}")
    else:
        raise RuntimeError("WRITE_GATE_STORE debe ser file, oci-cli o par-http")
    auth_keys = _load_lease_auth_keys(env); authenticator = _load_lease_authenticator(env, holder)
    db_fence = _build_db_fence(env)
    if db_fence is not None and app_env == "production" and not (auth_keys or authenticator):
        raise RuntimeError("con vallado en la base en producción el lease exige firmas: falta WRITE_GATE_LEASE_SIGNING_KEY_FILE (+ claves públicas) o WRITE_GATE_LEASE_AUTH_KEYS_FILE (el almacén por PAR puede sobrescribirse sin If-Match)")
    role = env.get("WRITE_GATE_ROLE", "primary")
    guard = None
    seal_file = env.get("WRITE_GATE_SEAL_PAR_URL_FILE")
    log_file = env.get("WRITE_GATE_SEAL_LOG_PAR_URL_FILE")
    if role == "primary" and db_fence is not None and app_env == "production" and not seal_file and not log_file:
        raise RuntimeError("el primario en producción exige el SELLO de promoción (WRITE_GATE_SEAL_LOG_PAR_URL_FILE: registro de apéndice con retención y trinquete en la base)")
    if log_file:
        if authenticator is None or db_fence is None or not hasattr(db_fence, "execute"):
            raise RuntimeError("el registro del sello exige claves Ed25519 y el vallado en la base (el trinquete vive en la base del consumidor)")
        from .seal_log import LogGuard, ParLogStore, PgRatchet
        try:
            lstore = ParLogStore(log_file, allow_create=False, allow_http_localhost=env.get("WRITE_GATE_ALLOW_HTTP_LOCALHOST") == "1" and app_env != "production")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"registro del sello inválido ({type(e).__name__})")
        guard = LogGuard(lstore, authenticator, PgRatchet(db_fence.execute))
    elif seal_file:
        if authenticator is None:
            raise RuntimeError("el sello exige claves Ed25519 (WRITE_GATE_LEASE_SIGNING_KEY_FILE + públicas de «oci» y «operator»)")
        from .seal import SealGuard
        from .store import ParHttpStore
        try:
            sstore = ParHttpStore(seal_file, object_name=env.get("WRITE_GATE_SEAL_OBJECT", "failover-seal.json"), allow_http_localhost=env.get("WRITE_GATE_ALLOW_HTTP_LOCALHOST") == "1" and app_env != "production")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"almacén del sello inválido ({type(e).__name__})")
        guard = SealGuard(sstore, authenticator)
    # TESTIGO DE FRESCURA independiente (witness.py): sin él, un lease y un sello restaurados a un estado antiguo y coherente serían aceptados por una instancia nueva. Obligatorio en producción con vallado en la base.
    wurl, wkey = env.get("WRITE_GATE_WITNESS_URL_FILE"), env.get("WRITE_GATE_WITNESS_PUBKEY_FILE")
    if role == "primary" and db_fence is not None and app_env == "production" and not (wurl and wkey):
        raise RuntimeError("el primario en producción exige el TESTIGO de frescura independiente: faltan WRITE_GATE_WITNESS_URL_FILE y WRITE_GATE_WITNESS_PUBKEY_FILE")
    if wurl or wkey:
        if not (wurl and wkey and authenticator is not None): raise RuntimeError("el testigo exige URL, clave pública del testigo y claves Ed25519 del nodo")
        import base64
        from .lease import Ed25519Auth
        from .witness import CompositeGuard, HttpWitnessClient, WitnessGuard
        try:
            wpub = base64.b64decode(open(wkey).read().strip(), validate=True); vf = Ed25519Auth(holder, b"\x01" * 32, {"witness": [wpub]})
            wc = HttpWitnessClient(wurl, allow_http_localhost=env.get("WRITE_GATE_ALLOW_HTTP_LOCALHOST") == "1" and app_env != "production")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"testigo inválido ({type(e).__name__})")
        wg = WitnessGuard(wc, vf, getattr(guard, "log", None), max_age_s=float(env.get("WRITE_GATE_WITNESS_MAX_AGE_S", "30")))
        guard = CompositeGuard(wg, guard) if guard is not None else wg
    lease = LeaseClient(store, cfg, holder_id=holder, auth_keys=auth_keys, authenticator=authenticator, state_path=env.get("WRITE_GATE_LEASE_STATE_FILE"), acquire_guard=guard)
    attestation = None
    if db_fence is not None and env.get("WRITE_GATE_ATTEST_PAR_URL_FILE"):      # el primario PUBLICA la cobertura de su vallado (objeto aparte, mismo tipo de almacén que el lease)
        from .pg_fence import FenceAttestation
        astore, _rep = build_verified_par_store(env["WRITE_GATE_ATTEST_PAR_URL_FILE"], env.get("WRITE_GATE_ATTEST_OBJECT", "fence-attestation.json"),
                                                 allow_http_localhost=env.get("WRITE_GATE_ALLOW_HTTP_LOCALHOST") == "1" and app_env != "production")
        attestation = FenceAttestation(astore)
    election = _build_election(env, db_fence)
    return WriteGate(lease, role=role, promote_file=env.get("WRITE_GATE_PROMOTE_FILE"), db_fence=db_fence, attestation=attestation, election=election)


def _build_election(env, db_fence):
    """WRITE_GATE_SITE_ELECTION=1: varias instancias del mismo sitio (ALB + Auto Scaling). Solo la líder compite por el lease entre nubes; las demás reciben la autoridad de la base (site_member.py).
    Exige el vallado en la base y que TODAS las instancias usen la misma identidad de sitio (WRITE_GATE_HOLDER_ID) y las mismas claves del sitio."""
    if env.get("WRITE_GATE_SITE_ELECTION", "0") != "1":
        return None
    if db_fence is None or not getattr(db_fence, "connect_url", None):
        raise RuntimeError("WRITE_GATE_SITE_ELECTION=1 exige WRITE_GATE_DB_FENCE=require")
    if not env.get("WRITE_GATE_HOLDER_ID"):
        raise RuntimeError("WRITE_GATE_SITE_ELECTION=1 exige WRITE_GATE_HOLDER_ID con la identidad del SITIO (la misma en todas las instancias, p. ej. «aws»)")
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from .site_member import SiteElection
    eng = create_engine(db_fence.connect_url, poolclass=NullPool, connect_args={"keepalives": 1, "keepalives_idle": 10, "keepalives_interval": 5, "keepalives_count": 3, "application_name": "nexo-site-leader"})

    class _Conn:
        def __init__(self): self.c = eng.connect().execution_options(isolation_level="AUTOCOMMIT")
        def scalar(self, sql, params): return self.c.exec_driver_sql(sql, params).scalar()
        def close(self): self.c.close()
    return SiteElection(_Conn, env["WRITE_GATE_HOLDER_ID"])


def _build_db_fence(env):
    """WRITE_GATE_DB_FENCE=require → vallado en la base (pg_fence.py). Exige WRITE_GATE_FENCE_DATABASE_URL (credenciales del GUARDIÁN, DISTINTAS de las de la aplicación) y, AL ARRANCAR, que la
    atestación de la base sea completa (todas las tablas con trigger, evento DDL, el rol de la aplicación sin poder cambiar el vallado ni poseer tablas). Falla cerrado: sin eso la aplicación no arranca."""
    mode = env.get("WRITE_GATE_DB_FENCE", "off").strip().lower()
    if mode == "off":
        return None
    if mode != "require":
        raise RuntimeError("WRITE_GATE_DB_FENCE debe ser off o require")
    url, app_role = env.get("WRITE_GATE_FENCE_DATABASE_URL"), env.get("WRITE_GATE_APP_ROLE", "nexoeventos_app")
    uf = env.get("WRITE_GATE_FENCE_DATABASE_URL_FILE")
    if uf:                                           # preferible a la variable: las credenciales del guardián en un archivo 0600 (no en el entorno de la API)
        import stat as _stat
        st = os.stat(uf)
        if _stat.S_IMODE(st.st_mode) & 0o077:
            raise RuntimeError("WRITE_GATE_FENCE_DATABASE_URL_FILE debe tener permisos 0600")
        url = open(uf).read().strip()
    if not url:
        raise RuntimeError("falta WRITE_GATE_FENCE_DATABASE_URL_FILE (o WRITE_GATE_FENCE_DATABASE_URL): credenciales del guardián del vallado, distintas de las de la aplicación")
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from .pg_fence import PgFence
    eng = create_engine(url, poolclass=NullPool)

    def execute(sql, params=None):
        with eng.begin() as c:
            res = c.exec_driver_sql(sql, params or ())
            return [tuple(r) for r in res.fetchall()] if res.returns_rows else []
    fence = PgFence(execute, app_role=app_role)
    fence.connect_url = url                          # (solo para la elección de líder del sitio; nunca se imprime)
    att = fence.attest()
    if att.get("ok") is not True:
        raise RuntimeError(f"el vallado de la base NO está completo (atestación): {json.dumps({k: att.get(k) for k in ('uncovered', 'event_trigger', 'app_role_can_change_fence', 'app_role_owns_tables')})}")
    return fence
