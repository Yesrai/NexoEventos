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

import hashlib
import hmac
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
    signer: str | None = None
    sig: str | None = None
    seal_head: list | None = None     # [seq, digest] de la ÚLTIMA entrada del registro de sello que conoce quien escribe este registro (ancla de frescura: ver seal_log.LogGuard)

    def _body(self) -> dict:
        d = {"v": 1, "holder": self.holder, "epoch": self.epoch, "seq": self.seq, "ttl_s": self.ttl_s, "margin_s": self.margin_s, "released": self.released, "signer": self.signer}
        if self.seal_head: d["seal_head"] = list(self.seal_head)
        return d

    def canonical(self) -> bytes:
        return json.dumps(self._body(), sort_keys=True, separators=(",", ":")).encode()

    def dump(self) -> bytes:
        d = self._body()
        if self.sig:
            d["sig"] = self.sig
        return json.dumps(d).encode()

    @staticmethod
    def load(data: bytes) -> "Record":
        try:
            d = json.loads(data)
            return Record(d["holder"], int(d["epoch"]), int(d["seq"]), float(d["ttl_s"]), float(d["margin_s"]), bool(d["released"]), d.get("signer"), d.get("sig"), d.get("seal_head") if isinstance(d.get("seal_head"), list) and len(d["seal_head"]) == 2 else None)
        except (ValueError, KeyError, TypeError):
            raise StoreError("registro de lease ilegible (se rechaza; falla cerrado)")


class HmacAuth:
    """Firma simétrica: cada nodo necesita la clave de QUIEN verifica (comparten secretos). Alternativa mínima: Ed25519Auth."""
    def __init__(self, keys: dict):
        self.keys = {str(k): bytes(v) for k, v in keys.items()}

    def can_sign(self, holder: str) -> bool: return holder in self.keys

    def sign(self, holder: str, data: bytes) -> str:
        return hmac.new(self.keys[holder], data, hashlib.sha256).hexdigest()

    def verify(self, signer: str, data: bytes, sig: str) -> bool:
        key = self.keys.get(signer)
        return bool(key and sig and hmac.compare_digest(sig, hmac.new(key, data, hashlib.sha256).hexdigest()))


class Ed25519Auth:
    """Firma asimétrica: el nodo guarda SOLO su clave privada y las claves PÚBLICAS de los demás (no son secretas). Un nodo comprometido no puede firmar como otro. `peers` admite varias claves públicas
    por titular (rotación: se publica la nueva antes de empezar a firmar con ella)."""
    def __init__(self, own_id: str, own_private: bytes, peers_public: dict):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
        self.own_id = own_id; self._priv = Ed25519PrivateKey.from_private_bytes(bytes(own_private))
        self._pub = {str(h): [Ed25519PublicKey.from_public_bytes(bytes(k)) for k in (ks if isinstance(ks, (list, tuple)) else [ks])] for h, ks in peers_public.items()}
        self._pub.setdefault(own_id, [self._priv.public_key()])

    def can_sign(self, holder: str) -> bool: return holder == self.own_id

    def sign(self, holder: str, data: bytes) -> str:
        return self._priv.sign(data).hex()

    def verify(self, signer: str, data: bytes, sig: str) -> bool:
        from cryptography.exceptions import InvalidSignature
        for k in self._pub.get(signer, []):
            try:
                k.verify(bytes.fromhex(sig), data); return True
            except (InvalidSignature, ValueError, TypeError):
                continue
        return False


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
    # Firmas HMAC por titular ({holder_id: clave}). SIN ellas ningún registro es «auténtico»: nada se acepta por su contenido (ni liberaciones, ni «soy el titular») y toda toma exige observar ttl+margen.
    auth_keys: dict | None = None            # HMAC por titular (simétrico)
    authenticator: object | None = None      # o un Ed25519Auth (asimétrico, recomendado: no hay que repartir secretos)
    state_path: str | None = None    # archivo 0600 con el ETag de NUESTRA última escritura confirmada: permite que un REINICIO del mismo titular adopte su lease (el ETag lo asigna el servidor y no se puede falsificar)
    epoch_reporter: object | None = None      # callable(época): informa al TESTIGO de frescura la época adquirida (best effort: si falla, el testigo se queda atrás y los consumidores nuevos exigirán más)
    head_provider: object | None = None       # callable() -> [seq, digest] | None: el titular (OCI) publica la cabeza del registro de sello en cada renovación
    acquire_guard: object | None = None      # callable(época_del_lease|None) -> (ok, motivo): SELLO de promoción; si no autoriza, NO se adquiere ni se renueva (falla cerrado)
    ttl_cap_factor: float = 4.0      # un ttl/margen publicado nunca se usa por DEBAJO del local (acortaría la espera) ni por encima de este múltiplo (bloquearía para siempre)

    def __post_init__(self):
        self.config.validate()
        self._etag: str | None = None
        self._epoch: int | None = None
        self._seq = 0
        self._deadline: float | None = None
        self._lost = False
        self._observed: tuple[str, float] | None = None
        self.holding_since_epoch: int | None = None
        self._pending: bytes | None = None        # bytes EXACTOS de nuestra última escritura enviada: solo un registro idéntico a ellos se adopta por «resultado incierto»
        self._hwm = 0                              # época máxima vista (nunca se concede una menor o igual)
        self._seen: tuple[int, int] | None = None   # (época, secuencia) del último registro AUTÉNTICO visto en este proceso
        self.tamper_events = 0                     # registros inconsistentes vistos (retroceso de época/secuencia, firma inválida, ilegible): alarma, nunca autoridad

    # ---------------------------------------------------------------- estado local (SIN red: apto para la ruta de cada petición)
    def is_valid(self) -> bool:
        return (not self._lost) and self._deadline is not None and self.mono() < self._deadline

    @property
    def epoch(self) -> int | None:
        return self._epoch if self.is_valid() else None

    def remaining_s(self) -> float:
        return 0.0 if not self.is_valid() else self._deadline - self.mono()

    def status(self) -> dict:
        return {"holder": self.holder_id, "valid": self.is_valid(), "epoch": self.epoch, "remaining_s": round(self.remaining_s(), 3), "lost": self._lost, "tamper_events": self.tamper_events}

    # ---------------------------------------------------------------- autenticidad
    def _persist(self) -> None:
        if not self.state_path:
            return
        import os
        try:
            tmp = f"{self.state_path}.tmp"; fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f: json.dump({"etag": self._etag, "epoch": self._epoch, "seq": self._seq, "holder": self.holder_id}, f)
            os.replace(tmp, self.state_path)
        except OSError:
            pass                                                   # sin persistencia el reinicio simplemente observará ttl+margen (seguro)

    def _persisted_etag(self) -> str | None:
        if not self.state_path:
            return None
        try:
            d = json.loads(open(self.state_path).read())
            et = d.get("etag") if isinstance(d, dict) and d.get("holder") == self.holder_id else None
            return et if isinstance(et, str) and et else None
        except (OSError, ValueError, AttributeError, UnicodeDecodeError):
            return None                                            # ausente o corrupto: no se adopta nada (se observa ttl+margen)

    @property
    def _auth(self):
        return self.authenticator or (HmacAuth(self.auth_keys) if self.auth_keys else None)

    def _sign(self, rec: Record) -> Record:
        a = self._auth
        if a is not None and a.can_sign(self.holder_id):
            rec.signer = self.holder_id; rec.sig = a.sign(self.holder_id, rec.canonical())
        return rec

    def _authentic(self, rec: Record) -> bool:
        a = self._auth
        return bool(a is not None and rec.signer and rec.sig and a.verify(rec.signer, rec.canonical(), rec.sig))

    def _see_epoch(self, rec: Record) -> None:
        """La época máxima solo sube con registros auténticos (con claves) o sin saltos absurdos (sin claves): un registro falsificado no infla ni baja el techo."""
        if self._auth is not None:
            if not self._authentic(rec):
                if rec.epoch != 0: self.tamper_events += 1
                return
        elif rec.epoch > self._hwm + 1000:
            self.tamper_events += 1; return
        if rec.epoch < self._hwm:
            self.tamper_events += 1                    # retroceso de época: reutilización de un registro antiguo
        self._hwm = max(self._hwm, rec.epoch)
        if self._seen is None or (rec.epoch, rec.seq) > self._seen:
            self._seen = (rec.epoch, rec.seq)

    def _invalidate(self, lost: bool):
        self._deadline = None
        self._lost = lost or self._lost

    # ---------------------------------------------------------------- operaciones
    def _check_store(self) -> Result | None:
        if self.require_verified_store and not getattr(self.store, "verified", False):
            return Result(False, "almacén NO verificado (ejecuta verify_store_semantics): se rechaza, falla cerrado")
        return None

    def _head(self):
        try:
            return list(self.head_provider()) if self.head_provider else None
        except Exception:  # noqa: BLE001
            return None

    def _guard(self, epoch, head=None) -> Result | None:
        if self.acquire_guard is None:
            return None
        try:
            try: ok, why = self.acquire_guard(epoch, head)
            except TypeError: ok, why = self.acquire_guard(epoch)              # guardias antiguas sin ancla

        except Exception:  # noqa: BLE001 — un guardia que falla es un guardia que NO autoriza
            ok, why = False, "guardia de sello no disponible (falla cerrado)"
        return None if ok else Result(False, f"sellado: {why}")

    def acquire(self) -> Result:
        bad = self._check_store()
        if bad: return bad
        g = self._guard(None)                              # (sin época todavía: bloquea si está SELLADO, ausente o inválido)
        if g: return g
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
        g = self._guard(rec.epoch, rec.seal_head)           # con la época observada y la cabeza del sello que publicó quien escribió ese registro: un «unsealed» anterior a la última promoción no vale
        if g: return g
        now = self.mono()
        prev_seen = self._seen
        self._see_epoch(rec)
        mine = rv.data == self._pending or (self._persisted_etag() is not None and rv.etag == self._persisted_etag())
        if mine and rec.holder == self.holder_id and not rec.released and (self._auth is None or self._authentic(rec)):
            # Se adopta SOLO un registro que es NUESTRO: byte a byte la última escritura enviada (resultado incierto) o el ETag de nuestra última escritura confirmada guardado en disco (reinicio).
            # Un registro que solo DIGA «soy yo» —o una copia reutilizada, que recibe un ETag nuevo— no se adopta: lo pudo escribir cualquiera.
            self._etag, self._epoch, self._seq, self._lost = rv.etag, rec.epoch, rec.seq, False
            return self._renew_locked()
        # Atajo de toma inmediata SOLO para una liberación AUTÉNTICA (firmada por su titular): quien libera deja de escribir ANTES de publicarla. Sin firma válida no hay atajo.
        # La liberación debe ser AUTÉNTICA *y* una transición que vimos en ESTE proceso (el mismo titular y época, secuencia mayor): una liberación firmada antigua reutilizada no vale para quien no la vio venir.
        takeable = rec.released and ((self._authentic(rec) and prev_seen is not None and rec.epoch == prev_seen[0] and rec.seq > prev_seen[1]) or (self._auth is None and rec.epoch == 0 and rec.seq == 0))   # sin claves (solo pruebas) el registro INICIAL sin firma también; con claves, ni ese
        if not takeable:
            if self._observed is None or self._observed[0] != rv.etag:
                self._observed = (rv.etag, now)             # vemos este ETag por primera vez: empieza la observación
                return Result(False, "titular activo: observando", wait_s=self._need(rec))
            waited = now - self._observed[1]
            need = self._need(rec)
            if waited < need:
                return Result(False, "titular activo: aún no caducado", wait_s=need - waited)
        # Toma por CAS contra el ETag observado: si el titular renovó mientras tanto, el servidor lo rechaza.
        t_send = self.mono()
        new = self._sign(Record(self.holder_id, max(rec.epoch, self._hwm) + 1, 0, self.config.ttl_s, self.config.margin_s, False, seal_head=self._head()))
        payload = new.dump(); self._pending = payload
        try:
            etag = self.store.replace(rv.etag, payload)
        except PreconditionFailed:
            self._observed = None
            return Result(False, "perdió la carrera (otro escritor cambió el lease)")
        except StoreUnavailable:
            return Result(False, "resultado incierto: no se asume el lease; se resolverá en el próximo intento")
        self._etag, self._epoch, self._seq, self._lost, self._observed = etag, new.epoch, 0, False, None
        self._hwm = max(self._hwm, new.epoch); self._persist()
        if self.epoch_reporter:
            try: self.epoch_reporter(new.epoch)
            except Exception: pass
        self._deadline = t_send + self.config.ttl_s - self.config.margin_s
        return Result(True, f"lease adquirido (época {new.epoch})")

    def _need(self, rec: Record) -> float:
        """Espera de observación: NUNCA menor que la configuración local (un ttl/margen falsificado a la baja no acorta la espera) y acotada por arriba (para no bloquear eternamente)."""
        c = self.config
        ttl = min(max(rec.ttl_s, c.ttl_s), c.ttl_s * self.ttl_cap_factor); margin = min(max(rec.margin_s, c.margin_s), max(c.margin_s, 1e-9) * self.ttl_cap_factor)
        return ttl + margin

    def renew(self) -> Result:
        if self._lost or self._etag is None:
            return Result(False, "sin lease que renovar")
        g = self._guard(self._epoch, None)
        if g:
            self._invalidate(True); return g                 # sellado mientras lo teníamos: se pierde y no se recupera sin failback manual
        return self._renew_locked()

    def _renew_locked(self) -> Result:
        bad = self._check_store()
        if bad:
            self._invalidate(False); return bad
        t_send = self.mono()
        rec = self._sign(Record(self.holder_id, self._epoch, self._seq + 1, self.config.ttl_s, self.config.margin_s, False, seal_head=self._head()))
        payload = rec.dump(); self._pending = payload
        try:
            etag = self.store.replace(self._etag, payload)
        except PreconditionFailed:
            return self._resolve_conflict(t_send)
        except StoreUnavailable:
            return Result(False, "renovación sin confirmar: la validez NO se amplía")
        self._etag, self._seq = etag, rec.seq; self._persist()
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
        if rec:
            self._see_epoch(rec)
        if rec and rv.data == self._pending and rec.holder == self.holder_id and rec.epoch == self._epoch and not rec.released:
            self._etag, self._seq = rv.etag, rec.seq         # adoptamos SOLO si es byte a byte nuestra última escritura (un «soy yo» o un registro antiguo reutilizado NO); no ampliamos el plazo (no conocemos el instante de envío de esa escritura)
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
            self.store.replace(etag, self._sign(Record(None, epoch, seq + 1, self.config.ttl_s, self.config.margin_s, True)).dump())
        except StoreError:
            return Result(False, "liberación no confirmada (el lease caducará solo)")
        self._etag = None
        return Result(True, "liberado")


def init_lease(store: ConditionalStore, allow_non_atomic: bool = False, ttl_s: float = 15.0, margin_s: float = 5.0) -> str:
    """Crea el objeto del lease UNA vez (acción de operación, no del camino de ejecución). Con almacenes sin create atómico (CLI de OCI) exige confirmación explícita."""
    if not store.ATOMIC_CREATE and not allow_non_atomic:
        raise StoreError("este almacén no garantiza create atómico: la inicialización debe hacerla una sola persona, una sola vez (allow_non_atomic=True)")
    return store.create(Record(None, 0, 0, ttl_s, margin_s, True).dump())


def pause_budget_s(ttl_s: float, margin_s: float, drift: float = 0.05) -> float:
    """HUECO MÍNIMO real entre el fin de la autoridad del titular anterior y el inicio de la del nuevo (peor caso de deriva ρ): el nuevo espera ttl+margen de SU reloj (que puede ir ρ más rápido) y el anterior
    tiene autoridad ttl−margen del SUYO (que puede ir ρ más lento):  g = (ttl+margen)/(1+ρ) − (ttl−margen)/(1−ρ).  Es lo máximo que puede pasar entre la comprobación de autoridad en el COMMIT de la base y
    la finalización de ese commit (pausa del servidor, VM congelada…) más el desfase tolerado del reloj de la base, sin riesgo de doble escritor. Con ρ=5 %, ttl=15 y margen=5: ≈ 8,5 s."""
    return (ttl_s + margin_s) / (1 + drift) - (ttl_s - margin_s) / (1 - drift)
