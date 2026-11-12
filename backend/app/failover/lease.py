"""Lease (arrendamiento) de escritor único con compare-and-swap y vallado por época (B-10). Solo biblioteca estándar.

Garantía que se pretende — y sus SUPUESTOS (si alguno falla, NO hay garantía):
  S1. El almacén aplica `If-Match` de forma atómica y las lecturas son fuertes (verificado en documentación; hay que comprobarlo en el bucket real con verify_store_semantics).
  S2. Los relojes MONÓTONOS de los procesos tienen deriva de tasa acotada ρ (|rapidez − 1| ≤ ρ) y el margen cumple  margen ≥ ρ · ttl.  No se compara el reloj de pared entre máquinas.
  S3. Un proceso no se pausa entre comprobar `is_valid()` y completar la escritura protegida más de `margen` (el backend vuelve a comprobar justo antes del COMMIT: gate.py).
Idea: el titular solo se considera válido hasta  t_envío_de_la_última_renovación + ttl − margen  (reloj monótono propio, medido desde el ENVÍO, no desde la respuesta).
Quien quiere tomar el lease NO compara relojes: observa que el ETag no cambia durante ≥ ttl + margen en SU reloj monótono y entonces hace CAS con ese ETag y época+1.
Un fallo de red nunca amplía la validez; una escritura de resultado incierto se resuelve leyendo (si el registro ya es nuestro, se adopta el ETag, no se amplía el plazo).
Esto NO elimina por completo el riesgo de «doble escritor» (ver LIMITACIONES en docs/entregable3/19): pausas largas entre comprobación y escritura, deriva de reloj mayor que ρ,
almacén no verificado. La época (`epoch`) es el token de vallado que una capa de datos compartida podría exigir; entre nubes no hay capa de datos compartida, así que NO se declara seguro el failover.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

from .store import ConditionalStore, PreconditionFailed, StoreError, StoreUnavailable


class LeaseConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LeaseConfig:
    ttl_s: float = 15.0
    margin_s: float = 5.0
    drift_ppm_assumed: int = 50_000          # ρ asumida = 5 %
    allow_unsafe_margin: bool = False        # SOLO pruebas que demuestran por qué hace falta el margen

    def validate(self) -> None:
        if self.ttl_s <= 0 or self.margin_s < 0 or self.margin_s * 2 >= self.ttl_s:
            raise LeaseConfigError("se exige 0 ≤ margen < ttl/2")
        rho = self.drift_ppm_assumed / 1_000_000
        if not self.allow_unsafe_margin and self.margin_s < rho * self.ttl_s:
            raise LeaseConfigError(f"margen insuficiente: debe ser ≥ ρ·ttl = {rho * self.ttl_s:.2f} s (deriva asumida {rho:.1%})")

    @property
    def renew_interval_s(self) -> float:
        return max((self.ttl_s - self.margin_s) / 3.0, 0.05)


@dataclass
class Record:
    holder: str | None
    epoch: int
    seq: int
    ttl_s: float
    margin_s: float
    released: bool = False

    def dump(self) -> bytes:
        return json.dumps({"v": 1, "holder": self.holder, "epoch": self.epoch, "seq": self.seq, "ttl_s": self.ttl_s, "margin_s": self.margin_s, "released": self.released}).encode()

    @staticmethod
    def load(data: bytes) -> "Record":
        try:
            d = json.loads(data)
            return Record(d["holder"], int(d["epoch"]), int(d["seq"]), float(d["ttl_s"]), float(d["margin_s"]), bool(d["released"]))
        except (ValueError, KeyError, TypeError):
            raise StoreError("registro de lease ilegible (se rechaza; falla cerrado)")


@dataclass
class Result:
    ok: bool
    reason: str
    wait_s: float = 0.0


@dataclass
class LeaseClient:
    store: ConditionalStore
    config: LeaseConfig = field(default_factory=LeaseConfig)
    holder_id: str = field(default_factory=lambda: f"nodo-{uuid.uuid4().hex[:8]}")
    mono: callable = time.monotonic
    require_verified_store: bool = True

    def __post_init__(self):
        self.config.validate()
        self._etag: str | None = None
        self._epoch: int | None = None
        self._seq = 0
        self._deadline: float | None = None
        self._lost = False
        self._observed: tuple[str, float] | None = None
        self.holding_since_epoch: int | None = None

    # ---------------------------------------------------------------- estado local (SIN red: apto para la ruta de cada petición)
    def is_valid(self) -> bool:
        return (not self._lost) and self._deadline is not None and self.mono() < self._deadline

    @property
    def epoch(self) -> int | None:
        return self._epoch if self.is_valid() else None

    def remaining_s(self) -> float:
        return 0.0 if not self.is_valid() else self._deadline - self.mono()

    def status(self) -> dict:
        return {"holder": self.holder_id, "valid": self.is_valid(), "epoch": self.epoch, "remaining_s": round(self.remaining_s(), 3), "lost": self._lost}

    def _invalidate(self, lost: bool):
        self._deadline = None
        self._lost = lost or self._lost

    # ---------------------------------------------------------------- operaciones
    def _check_store(self) -> Result | None:
        if self.require_verified_store and not getattr(self.store, "verified", False):
            return Result(False, "almacén NO verificado (ejecuta verify_store_semantics): se rechaza, falla cerrado")
        return None

    def acquire(self) -> Result:
        bad = self._check_store()
        if bad: return bad
        try:
            rv = self.store.read()
        except StoreError:
            return Result(False, "almacén no disponible")
        if rv is None:
            return Result(False, "lease no inicializado (usa init_lease una sola vez)")
        try:
            rec = Record.load(rv.data)
        except StoreError as e:
            return Result(False, str(e))
        now = self.mono()
        if rec.holder == self.holder_id and not rec.released:
            # Una escritura nuestra de resultado incierto sí se aplicó: se adopta el ETag y se renueva (la validez solo la da la renovación confirmada).
            self._etag, self._epoch, self._seq, self._lost = rv.etag, rec.epoch, rec.seq, False
            return self._renew_locked()
        takeable = rec.released or rec.holder is None
        if not takeable:
            if self._observed is None or self._observed[0] != rv.etag:
                self._observed = (rv.etag, now)             # vemos este ETag por primera vez: empieza la observación
                return Result(False, "titular activo: observando", wait_s=rec.ttl_s + max(rec.margin_s, self.config.margin_s))
            waited = now - self._observed[1]
            need = rec.ttl_s + max(rec.margin_s, self.config.margin_s)
            if waited < need:
                return Result(False, "titular activo: aún no caducado", wait_s=need - waited)
        # Toma por CAS contra el ETag observado: si el titular renovó mientras tanto, el servidor lo rechaza.
        t_send = self.mono()
        new = Record(self.holder_id, rec.epoch + 1, 0, self.config.ttl_s, self.config.margin_s, False)
        try:
            etag = self.store.replace(rv.etag, new.dump())
        except PreconditionFailed:
            self._observed = None
            return Result(False, "perdió la carrera (otro escritor cambió el lease)")
        except StoreUnavailable:
            return Result(False, "resultado incierto: no se asume el lease; se resolverá en el próximo intento")
        self._etag, self._epoch, self._seq, self._lost, self._observed = etag, new.epoch, 0, False, None
        self._deadline = t_send + self.config.ttl_s - self.config.margin_s
        return Result(True, f"lease adquirido (época {new.epoch})")

    def renew(self) -> Result:
        if self._lost or self._etag is None:
            return Result(False, "sin lease que renovar")
        return self._renew_locked()

    def _renew_locked(self) -> Result:
        bad = self._check_store()
        if bad:
            self._invalidate(False); return bad
        t_send = self.mono()
        rec = Record(self.holder_id, self._epoch, self._seq + 1, self.config.ttl_s, self.config.margin_s, False)
        try:
            etag = self.store.replace(self._etag, rec.dump())
        except PreconditionFailed:
            return self._resolve_conflict(t_send)
        except StoreUnavailable:
            return Result(False, "renovación sin confirmar: la validez NO se amplía")
        self._etag, self._seq = etag, rec.seq
        new_deadline = t_send + self.config.ttl_s - self.config.margin_s
        # OJO: el reloj monótono puede tener cualquier origen (incluso negativo): nunca se usa «or 0.0» para comparar plazos.
        self._deadline = new_deadline if self._deadline is None else max(self._deadline, new_deadline)
        return Result(True, "renovado")

    def _resolve_conflict(self, t_send: float) -> Result:
        """El CAS falló: ¿otro nos quitó el lease o fue nuestra propia escritura previa de resultado incierto?"""
        try:
            rv = self.store.read()
            rec = Record.load(rv.data) if rv else None
        except StoreError:
            return Result(False, "conflicto sin resolver: la validez NO se amplía")
        if rec and rec.holder == self.holder_id and rec.epoch == self._epoch and not rec.released:
            self._etag, self._seq = rv.etag, rec.seq         # adoptamos; no ampliamos el plazo (no conocemos el instante de envío de esa escritura)
            return Result(False, "escritura previa de resultado incierto adoptada; renovar de nuevo")
        self._invalidate(True)
        return Result(False, "lease PERDIDO (otro escritor lo tomó): no se recupera sin adquirir de nuevo")

    def release(self) -> Result:
        # Primero se deja de escribir (local), después se publica la liberación.
        had = self._etag is not None and not self._lost
        epoch, seq, etag = self._epoch, self._seq, self._etag
        self._invalidate(False)
        if not had:
            return Result(True, "no había lease")
        try:
            self.store.replace(etag, Record(None, epoch, seq + 1, self.config.ttl_s, self.config.margin_s, True).dump())
        except StoreError:
            return Result(False, "liberación no confirmada (el lease caducará solo)")
        self._etag = None
        return Result(True, "liberado")


def init_lease(store: ConditionalStore, allow_non_atomic: bool = False, ttl_s: float = 15.0, margin_s: float = 5.0) -> str:
    """Crea el objeto del lease UNA vez (acción de operación, no del camino de ejecución). Con almacenes sin create atómico (CLI de OCI) exige confirmación explícita."""
    if not store.ATOMIC_CREATE and not allow_non_atomic:
        raise StoreError("este almacén no garantiza create atómico: la inicialización debe hacerla una sola persona, una sola vez (allow_non_atomic=True)")
    return store.create(Record(None, 0, 0, ttl_s, margin_s, True).dump())
