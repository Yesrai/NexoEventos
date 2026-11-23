"""SELLO DE PROMOCIÓN: protección PERSISTENTE y VERIFICABLE contra el regreso del primario tras un failover. Vive en el almacén condicional de OCI (el mismo del lease), fuera de la EC2 y de la RDS.

Problema: si la RDS estaba detenida cuando OCI fue promovida, no se pudo poner el cerrojo en su base (el vallado por la base exige que esté viva). La RDS se reinicia sola a los 7 días (o la enciende alguien) y la
aplicación de AWS (backend, guardián, instancias de Auto Scaling) podría adquirir el lease en cuanto el de OCI no se renueve y escribir sobre datos viejos. Con el sello, NINGUNA instancia de AWS adquiere ni renueva
el lease mientras el sello diga «sellado»; levantarlo es el failback y es SOLO MANUAL (firma de una clave de OPERADOR que no está en ningún nodo).

Estados (registro firmado con Ed25519, sin firma válida no existe): sealed (lo escribe OCI al promover, firmado por «oci») · unsealed (lo escribe la persona, firmado por «operator», atado a `for_epoch`: solo vale si
`for_epoch ≥` la época del lease que se observa; así un «unsealed» antiguo reutilizado NO levanta un sello posterior). FALLA CERRADO: sello ausente, ilegible, con firma inválida, con almacén inaccesible o sellado ⇒ no se adquiere.
LÍMITE: un atacante con la URL de lectura/escritura puede restaurar el estado COMPLETO (lease + sello) a un momento anterior; el lease sigue protegido por el CAS y la espera ttl+margen (OCI pierde su lease antes de que
AWS pueda tomarlo), pero AWS volvería a escribir sobre datos viejos sin decisión humana. No lo evita ninguna firma: lo reduce que el PAR sea de lectura para AWS y solo OCI/operador puedan escribir.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .store import ConditionalStore, PreconditionFailed, StoreError, StoreUnavailable


@dataclass
class SealRecord:
    state: str          # sealed | unsealed
    failover_epoch: int
    seq: int
    at: float
    signer: str
    sig: str | None = None

    def canonical(self) -> bytes:
        return json.dumps({"v": 1, "state": self.state, "failover_epoch": self.failover_epoch, "seq": self.seq, "at": self.at, "signer": self.signer}, sort_keys=True, separators=(",", ":")).encode()

    def dump(self) -> bytes:
        return json.dumps({"v": 1, "state": self.state, "failover_epoch": self.failover_epoch, "seq": self.seq, "at": self.at, "signer": self.signer, "sig": self.sig}).encode()

    @staticmethod
    def load(data: bytes) -> "SealRecord":
        try:
            d = json.loads(data)
            if d["state"] not in ("sealed", "unsealed"):
                raise ValueError
            return SealRecord(d["state"], int(d["failover_epoch"]), int(d["seq"]), float(d["at"]), str(d["signer"]), d.get("sig"))
        except (ValueError, KeyError, TypeError):
            raise StoreError("sello ilegible (falla cerrado)")


@dataclass
class Verdict:
    ok: bool
    reason: str


class SealGuard:
    """Lado AWS (solo LEE): `__call__(lease_epoch) -> (ok, reason)`. `verifier.verify(signer, bytes, sig)`; firmantes aceptados: sealed ← «oci»; unsealed ← «operator»."""
    SEALER, OPERATOR = "oci", "operator"

    def __init__(self, store: ConditionalStore, verifier, cache_s: float = 1.0, now=time.monotonic):
        self.store, self.verifier, self.cache_s, self.now = store, verifier, cache_s, now
        self._cached: tuple[float, tuple[bool, str], int | None] | None = None

    def _valid(self, rec: SealRecord) -> bool:
        want = self.SEALER if rec.state == "sealed" else self.OPERATOR
        return rec.signer == want and bool(rec.sig) and self.verifier.verify(rec.signer, rec.canonical(), rec.sig)

    def check(self, lease_epoch: int | None) -> Verdict:
        try:
            rv = self.store.read()
        except (StoreError, OSError):
            return Verdict(False, "almacén del sello inaccesible (falla cerrado)")
        if rv is None:
            return Verdict(False, "sin registro de sello: el despliegue debe inicializarlo («unsealed» firmado por el operador); falla cerrado")
        try:
            rec = SealRecord.load(rv.data)
        except StoreError as e:
            return Verdict(False, str(e))
        if not self._valid(rec):
            return Verdict(False, "sello con firma inválida (falla cerrado)")
        if rec.state == "sealed":
            return Verdict(False, f"SELLADO por la promoción de OCI (época {rec.failover_epoch}): el failback es manual")
        if lease_epoch is not None and rec.failover_epoch < lease_epoch:
            return Verdict(False, f"el «unsealed» es para la época {rec.failover_epoch} < {lease_epoch} del lease actual (reutilizado o anterior a la última promoción)")
        return Verdict(True, "sin sello")

    def __call__(self, lease_epoch: int | None = None) -> tuple[bool, str]:
        t = self.now()
        if self._cached and t - self._cached[0] < self.cache_s and self._cached[2] == lease_epoch and not self._cached[1][0]:
            return self._cached[1]                                     # (solo se cachean los NO: un «sí» se vuelve a comprobar siempre)
        v = self.check(lease_epoch); res = (v.ok, v.reason); self._cached = (t, res, lease_epoch)
        return res


def _write(store: ConditionalStore, rec: SealRecord, sign) -> None:
    rec.sig = sign(rec.canonical())
    rv = store.read()
    if rv is None:
        store.create(rec.dump()); return
    cur = SealRecord.load(rv.data)
    if rec.seq <= cur.seq:
        raise StoreError("secuencia no creciente")
    store.replace(rv.etag, rec.dump())


def seal(store: ConditionalStore, auth, epoch: int, now=time.time) -> SealRecord:
    """Lado OCI/orquestador: se llama ANTES de habilitar escrituras en OCI. `auth.sign(holder, bytes)` con la clave de «oci». Idempotente; con CAS."""
    rv = store.read(); seq = (SealRecord.load(rv.data).seq + 1) if rv else 1
    rec = SealRecord("sealed", int(epoch), seq, now(), SealGuard.SEALER)
    _write(store, rec, lambda b: auth.sign(SealGuard.SEALER, b)); return rec


def unseal(store: ConditionalStore, operator_auth, for_epoch: int, now=time.time) -> SealRecord:
    """FAILBACK MANUAL (persona): firma con la clave de «operator» (offline), atada a `for_epoch` (≥ la época actual del lease)."""
    rv = store.read(); seq = (SealRecord.load(rv.data).seq + 1) if rv else 1
    rec = SealRecord("unsealed", int(for_epoch), seq, now(), SealGuard.OPERATOR)
    _write(store, rec, lambda b: operator_auth.sign(SealGuard.OPERATOR, b)); return rec
