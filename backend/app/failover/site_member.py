"""Varias instancias de UN MISMO sitio (p. ej. dos EC2 detrás de un ALB) frente al lease de escritura del SITIO.

Problema: el lease entre nubes (AWS vs OCI) es UNO por sitio. Si las dos EC2 de AWS compiten por él, solo una lo obtiene y la otra rechazaría con 503 todas las escrituras que le reparta el ALB
(media aplicación sin poder vender), o —con una identidad compartida— ambas podrían «pelearse» el registro.

Diseño: dentro del sitio solo UNA instancia —la LÍDER— habla con el almacén del lease entre nubes. Las demás son MIEMBROS: no tocan ese almacén, y su autoridad de escritura es la que la
BASE DE DATOS ya tiene concedida (`nexo_fence.fence_status()`: época + tiempo restante con el reloj de la base), recortada por un margen y medida con el reloj monótono local. Es la misma
base que valida cada COMMIT (trigger diferido con el reloj de la base y la época declarada), así que un miembro nunca puede escribir más allá de lo que la base y el lease del líder permiten.

La elección del líder usa un bloqueo consultivo de PostgreSQL (`pg_try_advisory_lock`) en una conexión dedicada con keepalive TCP agresivo: el bloqueo desaparece con la conexión. Es un asunto de
DISPONIBILIDAD, NO de seguridad: si por cualquier fallo dos instancias creyeran ser líderes, la seguridad la siguen dando el lease (CAS) y el vallado de la base, exactamente como antes.
Límite honesto: un líder CONGELADO con la conexión abierta retiene el bloqueo hasta que el ALB lo sustituya (health check) o el keepalive cierre la conexión; mientras tanto el lease caduca y el
sitio no escribe (falla cerrado, nunca escribe de más)."""
from __future__ import annotations

import hashlib
import logging
import time

logger = logging.getLogger("nexo.site_member")


def lock_key(site_id: str) -> int:
    """Clave de 63 bits derivada del identificador del sitio (los bloqueos consultivos usan bigint)."""
    return int.from_bytes(hashlib.sha256(b"nexo-site-leader:" + site_id.encode()).digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF


class SiteElection:
    """Elección del líder del sitio. `connect()` devuelve un objeto NUEVO con `scalar(sql, params) -> valor` y `close()` sobre una conexión en autocommit, SOLO para este bloqueo (con `keepalives*`)."""

    def __init__(self, connect, site_id: str, check_every_s: float = 1.0):
        self._connect, self.key, self.check_every_s = connect, lock_key(site_id), check_every_s
        self._conn = None
        self._leader = False
        self._checked = 0.0

    @property
    def is_leader(self) -> bool:
        return self._leader

    def _drop(self) -> None:
        c, self._conn, self._leader = self._conn, None, False
        if c is not None:
            try: c.close()
            except Exception: pass

    def step(self) -> bool:
        """Un ciclo: intenta ser líder (o comprueba que sigue siéndolo). Cualquier error de la conexión ⇒ se deja el liderazgo (el bloqueo cae con la conexión)."""
        try:
            if self._conn is None:
                self._conn = self._connect()
            if self._leader:
                if time.monotonic() - self._checked >= self.check_every_s:
                    self._conn.scalar("SELECT 1", ())             # prueba de vida: si la conexión murió, se pierde el bloqueo y el liderazgo
                    self._checked = time.monotonic()
                return True
            self._leader = bool(self._conn.scalar("SELECT pg_try_advisory_lock(%s)", (self.key,))); self._checked = time.monotonic()
            return self._leader
        except Exception:  # noqa: BLE001
            logger.warning("elección de líder del sitio: conexión perdida; se deja el liderazgo")
            self._drop()
            return False

    def resign(self) -> None:
        """Deja el liderazgo (cierra la conexión: el servidor libera el bloqueo)."""
        self._drop()


class DelegatedLease:
    """Autoridad de un MIEMBRO del sitio. Misma interfaz que `LeaseClient` para la ruta de cada petición (sin red). La autoridad es la de la base (fence_status) menos un margen,
    y se mide con el reloj monótono desde ANTES de la consulta (conservador). Sin consulta reciente y válida, caduca sola."""

    def __init__(self, holder_id: str, config, mono=time.monotonic):
        self.holder_id, self.config, self.mono = holder_id, config, mono
        self._epoch: int | None = None
        self._deadline: float | None = None
        self._lost = False
        self._etag = None                       # (compatibilidad con la interfaz: un miembro nunca posee el lease entre nubes)
        self.tamper_events = 0
        self.delegations = 0

    def is_valid(self) -> bool:
        return (not self._lost) and self._deadline is not None and self.mono() < self._deadline

    @property
    def epoch(self) -> int | None:
        return self._epoch if self.is_valid() else None

    def remaining_s(self) -> float:
        return 0.0 if not self.is_valid() else self._deadline - self.mono()

    def status(self) -> dict:
        return {"holder": self.holder_id, "valid": self.is_valid(), "epoch": self.epoch, "remaining_s": round(self.remaining_s(), 3), "lost": self._lost, "tamper_events": self.tamper_events, "delegated": True}

    def update(self, st: dict | None, t_send: float) -> bool:
        """Refresca desde `PgFence.status()`. Sin autoridad vigente en la base ⇒ se retira la delegación al instante."""
        rem = (st or {}).get("remaining_s", 0.0) - self.config.margin_s
        if not st or not st.get("valid") or not st.get("epoch") or rem <= 0.05:
            self.invalidate(); return False
        self._epoch = int(st["epoch"])
        self._deadline = t_send + rem                               # t_send es anterior a la lectura: nunca se amplía por latencia
        self._lost = False; self.delegations += 1
        return True

    def invalidate(self) -> None:
        self._deadline = None

    # Un miembro NO adquiere ni renueva el lease entre nubes: estas operaciones no existen para él.
    def acquire(self): raise RuntimeError("un miembro del sitio no adquiere el lease")
    def renew(self): raise RuntimeError("un miembro del sitio no renueva el lease")
    def release(self): self.invalidate()
