"""SELLO ANTIRRETROCESO: registro de APENDICE (append-only) encadenado + trinquete monotónico en la base del consumidor.

Problema (bloqueo del automático): el sello de seal.py es UN objeto. Una identidad con permiso de SOBRESCRITURA puede restaurar una versión ANTIGUA y legítimamente firmada («unsealed») y AWS la verificaría. Verificar la firma
no basta: hace falta que el estado NO pueda retroceder. Mecanismo, en tres capas independientes:
  1. APÉNDICE: cada cambio es un objeto NUEVO `seal-log/<seq>.json` creado con If-None-Match (nunca se sobrescribe). En OCI el prefijo lleva una REGLA DE RETENCIÓN (WORM): el servicio rechaza sobrescribir o borrar
     cada objeto mientras dure; un PAR de lectura/escritura solo puede AÑADIR nombres nuevos (que necesitan firma válida y secuencia/hash correctos).
  2. CADENA: cada entrada firma `seq`, `prev_hash` (hash de la entrada anterior) y el estado. Faltar una entrada, saltarse una o sustituir una rompe la cadena ⇒ se rechaza (falla cerrado).
  3. TRINQUETE: el consumidor (AWS) anota en SU PROPIA base (persistente, fuera del almacén de OCI) la mayor `seq` vista; si luego el registro muestra una `seq` MENOR (se borró/revirtió el final), se detecta el retroceso
     y se bloquea. El trinquete se sube también desde el lado de OCI al promover (mientras la RDS esté viva) y desde la guardia de reinicio.
LÍMITES: quien pueda borrar objetos sin respetar la retención (administrador del bucket) y además dañar el trinquete de la base puede revertir; un consumidor NUEVO sin trinquete y sin WORM dependería solo de la cadena
(un final borrado no se vería). Por eso el automático exige WORM validado en OCI REAL y trinquete en la base: ver failover_config (`primary.seal.antirollback_validated`)."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

from .store import ParHttpStore, PreconditionFailed, StoreError, StoreUnavailable

GENESIS = "0" * 64
PREFIX = "seal-log/"


@dataclass
class Entry:
    seq: int
    state: str            # sealed | unsealed
    failover_epoch: int
    prev_hash: str
    at: float
    signer: str
    sig: str | None = None

    def canonical(self) -> bytes:
        return json.dumps({"v": 1, "seq": self.seq, "state": self.state, "failover_epoch": self.failover_epoch, "prev_hash": self.prev_hash, "at": self.at, "signer": self.signer}, sort_keys=True, separators=(",", ":")).encode()

    def digest(self) -> str:
        return hashlib.sha256(self.canonical() + (self.sig or "").encode()).hexdigest()

    def dump(self) -> bytes:
        return json.dumps({**json.loads(self.canonical()), "sig": self.sig}).encode()

    @staticmethod
    def load(b: bytes) -> "Entry":
        try:
            d = json.loads(b)
            if d["state"] not in ("sealed", "unsealed"): raise ValueError
            return Entry(int(d["seq"]), d["state"], int(d["failover_epoch"]), str(d["prev_hash"]), float(d["at"]), str(d["signer"]), d.get("sig"))
        except (ValueError, KeyError, TypeError):
            raise StoreError("entrada del sello ilegible")


class InMemoryLog:
    """Almacén de objetos con prefijo. worm=True modela la regla de retención de OCI (sin sobrescribir ni borrar); worm=False modela un bucket SIN retención con un PAR de sobrescritura (CONTROL NEGATIVO)."""
    def __init__(self, worm: bool = True):
        self.worm, self.objs, self.down = worm, {}, False
    def _chk(self):
        if self.down: raise StoreUnavailable("almacén inaccesible")
    def names(self): self._chk(); return sorted(self.objs)
    def read(self, name): self._chk(); return self.objs.get(name)
    def create(self, name, data):
        self._chk()
        if name in self.objs: raise PreconditionFailed("ya existe")
        self.objs[name] = data
    def put_blind(self, name, data):                                  # lo que haría quien tiene un PAR de lectura/escritura
        if name in self.objs and self.worm: raise PreconditionFailed("retención: no se sobrescribe")
        self.objs[name] = data
    def delete(self, name):                                           # lo que haría quien tiene permiso de borrado
        if self.worm: raise PreconditionFailed("retención: no se borra")
        self.objs.pop(name, None)


class MemRatchet:
    def __init__(self): self.v = 0; self.down = False
    def observe(self, n):
        if self.down: raise StoreUnavailable("base inaccesible")
        self.v = max(self.v, n); return self.v


class PgRatchet:
    """Trinquete en la BASE del consumidor (nexo_fence.ratchet_seal). Persistente y fuera del almacén de OCI."""
    def __init__(self, execute): self.execute = execute
    def observe(self, n):
        rows = self.execute("SELECT nexo_fence.ratchet_seal(%(n)s)", {"n": int(n)})
        return int(rows[0][0])


def _name(seq): return f"{PREFIX}{seq:010d}.json"


def append(log, auth, signer: str, state: str, failover_epoch: int, now=time.time) -> Entry:
    """Añade UNA entrada nueva (If-None-Match). `signer`: «oci» para sealed, «operator» para unsealed. Si otro la añadió a la vez, falla (PreconditionFailed): se relee y se reintenta."""
    names = log.names(); seq = len(names) + 1
    prev = GENESIS
    if names:
        last = Entry.load(log.read(names[-1])); prev = last.digest()
    e = Entry(seq, state, int(failover_epoch), prev, now(), signer); e.sig = auth.sign(signer, e.canonical())
    log.create(_name(seq), e.dump()); return e


class LogGuard:
    """Lado AWS: __call__(lease_epoch) -> (ok, motivo). Verifica cadena, firmas, secuencia contigua, trinquete y época."""
    def __init__(self, log, verifier, ratchet, operator="operator", sealer="oci", require_init: bool = False, require_head: bool = False):
        """`require_init`: un consumidor SIN trinquete previo (seq 0) NO confía en la completitud del registro: se bloquea hasta que una persona inicialice el trinquete con una cabeza verificada (init_ratchet).
        `require_head`: exige que el registro del lease publique la cabeza del sello (ancla de frescura) cuando ya hubo una promoción."""
        self.log, self.verifier, self.ratchet, self.operator, self.sealer = log, verifier, ratchet, operator, sealer
        self.require_init, self.require_head = require_init, require_head
        self.tamper_events = 0

    def check(self, lease_epoch, lease_head=None):
        try:
            names = self.log.names()
        except (StoreError, OSError):
            return False, "almacén del sello inaccesible (falla cerrado)"
        if not names:
            return False, "registro del sello vacío: debe inicializarse (entrada «unsealed» del operador); falla cerrado"
        prev = GENESIS; last = None
        for i, nm in enumerate(names, 1):
            if nm != _name(i):
                self.tamper_events += 1; return False, f"cadena del sello rota: falta o sobra la entrada {i} (falla cerrado)"
            try:
                e = Entry.load(self.log.read(nm))
            except (StoreError, OSError):
                return False, "entrada ilegible (falla cerrado)"
            want = self.sealer if e.state == "sealed" else self.operator
            if e.seq != i or e.prev_hash != prev or e.signer != want or not e.sig or not self.verifier.verify(e.signer, e.canonical(), e.sig):
                self.tamper_events += 1; return False, f"entrada {i} inválida (firma, secuencia o hash previo): falla cerrado"
            prev, last = e.digest(), e
        if names and Entry.load(self.log.read(names[0])).state != "unsealed":
            return False, "la primera entrada debe ser «unsealed» del operador"
        # ANCLA DE FRESCURA: la cabeza [seq, digest] que publicó el titular del lease en su registro firmado. Un registro más corto (truncado) o con otra entrada en esa posición se rechaza aunque TODAS las firmas sean válidas.
        if lease_head:
            try: hseq, hdig = int(lease_head[0]), str(lease_head[1])
            except (ValueError, TypeError, IndexError):
                return False, "cabeza del sello ilegible en el registro del lease (falla cerrado)"
            if last.seq < hseq:
                self.tamper_events += 1; return False, f"TRUNCAMIENTO: el lease anuncia la cabeza {hseq} del sello y el registro solo llega a la {last.seq} (falla cerrado)"
            nm = _name(hseq)
            try: ent = Entry.load(self.log.read(nm))
            except (StoreError, OSError): return False, "no se pudo comprobar la cabeza anunciada (falla cerrado)"
            if ent.digest() != hdig:
                self.tamper_events += 1; return False, f"la entrada {hseq} no coincide con la cabeza anunciada por el lease: historia distinta (falla cerrado)"
        elif self.require_head and last.seq > 1:
            return False, "el registro de sello ya tiene entradas y el lease no publica su cabeza: sin ancla de frescura no se confía en la completitud (falla cerrado)"
        try:
            before = self.ratchet.observe(0)
            if self.require_init and before == 0:
                return False, "trinquete SIN inicializar en esta base: un consumidor nuevo no puede saber si el registro está completo; una persona debe inicializarlo con una cabeza verificada (falla cerrado)"
            top = self.ratchet.observe(last.seq)                      # el trinquete sube y devuelve el máximo visto jamás
        except (StoreError, OSError, Exception):  # noqa: BLE001
            return False, "trinquete de la base inaccesible (falla cerrado)"
        if top > last.seq:
            self.tamper_events += 1; return False, f"RETROCESO del sello: se vio la entrada {top} y ahora la última es la {last.seq} (falla cerrado)"
        if last.state == "sealed":
            return False, f"SELLADO por la promoción de OCI (época {last.failover_epoch}): el failback es manual"
        # El «unsealed» debe cubrir la ÚLTIMA promoción sellada (época del último «sealed»): la cadena garantiza el orden. NO se compara con la época del lease: tras un failback el lease sigue creciendo y comparar bloquearía
        # al titular legítimo en su primera renovación (defecto corregido: con la génesis «unsealed» de época 0 un lease de época ≥ 1 quedaba bloqueado).
        selladas = [Entry.load(self.log.read(n)).failover_epoch for n in names if Entry.load(self.log.read(n)).state == "sealed"]
        if selladas and last.failover_epoch < max(selladas):
            self.tamper_events += 1; return False, f"el «unsealed» (época {last.failover_epoch}) no cubre la última promoción sellada (época {max(selladas)})"
        return True, "sin sello"

    def __call__(self, lease_epoch=None, lease_head=None):
        return self.check(lease_epoch, lease_head)

    def head(self):
        """Cabeza actual [seq, digest] del registro (la publica el titular del lease en cada renovación)."""
        names = self.log.names()
        if not names: return None
        e = Entry.load(self.log.read(names[-1])); return [e.seq, e.digest()]


def init_ratchet(guard: "LogGuard", expected_head_seq: int) -> int:
    """ACCIÓN HUMANA: inicializa el trinquete de una base NUEVA con una cabeza que la persona VERIFICÓ fuera de banda (p. ej. la lista de entradas del bucket). Comprueba cadena y firmas antes de fijarla."""
    ok, why = guard.__class__(guard.log, guard.verifier, MemRatchet(), guard.operator, guard.sealer).check(None)          # verificación completa en seco (sin tocar el trinquete real)
    names = guard.log.names()
    if len(names) != expected_head_seq: raise StoreError(f"el registro tiene {len(names)} entradas y la persona verificó {expected_head_seq}: no se inicializa")
    if not ok and "SELLADO" not in why and "sin sello" not in why and "unsealed" not in why: raise StoreError(f"registro no válido: {why}")
    return guard.ratchet.observe(expected_head_seq)


class ParLogStore(ParHttpStore):
    """Registro de sello sobre un PAR de PREFIJO de OCI (la URL del archivo acaba en `/o/seal-log/`): listar (GET en la raíz /o/), leer y crear con If-None-Match. USO RECOMENDADO: SOLO LECTOR (PAR de lectura con listado).
    Un PAR de lectura/escritura NO es de solo adición: se observó que sobrescribe (un PAR no puede BORRAR, pero sí reemplazar); la escritura debe hacerla OciSdkLogStore con una identidad sin OBJECT_OVERWRITE/OBJECT_DELETE.
    SIN VALIDAR contra OCI real: el formato de listado del PAR y la retención WORM deben comprobarse en el bucket de laboratorio antes de declarar `antirollback_validated`."""
    def __init__(self, par_url_file, allow_create: bool = False, prefix: str | None = None, **kw):
        """LECTOR por defecto: `create` está DESHABILITADO (el sello lo escribe OciSdkLogStore con una identidad sin OVERWRITE/DELETE). `allow_create=True` solo para pruebas y para el control negativo del laboratorio."""
        super().__init__(par_url_file, **kw)
        self.allow_create = allow_create
        i = self._url.index("/o/") + 3
        self._root, self._prefix = self._url[:i], self._url[i:]
        if not self._prefix and prefix:                      # FORMATO REAL de OCI (F0, 20-nov): el PAR de prefijo acaba en «/o/» (el prefijo va dentro del token, no en la ruta): se indica aparte
            self._prefix = prefix
        if not self._prefix.endswith("/") or ".." in self._prefix:
            raise StoreError("la URL del PAR del registro debe acabar en un prefijo «.../o/<prefijo>/»")

    def names(self):
        code, body, _ = self._do("GET", url=self._root)
        if code == 404: return []
        if code != 200:
            raise StoreUnavailable(f"listado: HTTP {code}") if code >= 500 or code in (408, 429) else StoreError(f"listado rechazado (HTTP {code})")
        try:
            return sorted(o["name"] for o in json.loads(body).get("objects", []) if str(o.get("name", "")).startswith(self._prefix))
        except (ValueError, AttributeError, TypeError, KeyError):
            raise StoreError("listado ilegible")

    def read(self, name):
        import urllib.parse
        if not name.startswith(self._prefix): raise StoreError("nombre fuera del prefijo")
        code, body, _ = self._do("GET", url=self._root + urllib.parse.quote(name, safe="/"))
        if code == 404: return None
        if code == 200: return body
        raise StoreUnavailable(f"lectura: HTTP {code}") if code >= 500 else StoreError(f"lectura rechazada (HTTP {code})")

    def create(self, name, data):
        import urllib.parse
        if not self.allow_create: raise StoreError("ParLogStore es de SOLO LECTURA: un PAR de escritura no es solo-adición; el sello se escribe con OciSdkLogStore")
        if not name.startswith(self._prefix): raise StoreError("nombre fuera del prefijo")
        code, _, _ = self._do("PUT", data, {"If-None-Match": "*", "Content-Type": "application/octet-stream"}, url=self._root + urllib.parse.quote(name, safe="/"))
        if code in (200, 201): return
        if code in (412, 409): raise PreconditionFailed("la entrada ya existe")
        raise StoreUnavailable(f"escritura: HTTP {code}") if code >= 500 or code in (408, 429) else StoreError(f"escritura rechazada (HTTP {code})")


class OciSdkLogStore:
    """Registro de sello con IDENTIDAD FIRMADA de OCI (SDK de OCI; instance principal o clave de API): lado ESCRITOR/OPERADOR. Solo usa tres operaciones: ListObjects (OBJECT_INSPECT), GetObject (OBJECT_READ) y PutObject con
    `if_none_match='*'` sobre un nombre NUEVO (OBJECT_CREATE). Con la política de permisos mínimos (sin OBJECT_OVERWRITE ni OBJECT_DELETE) el SERVICIO impide sobrescribir y borrar, sin depender de una URL. `client` es un
    ObjectStorageClient (inyectable); SIN VALIDAR contra OCI real."""
    def __init__(self, client, namespace: str, bucket: str, prefix: str = PREFIX):
        self.c, self.ns, self.bucket, self.prefix = client, namespace, bucket, prefix

    def names(self):
        out, start = [], None
        while True:
            r = self.c.list_objects(self.ns, self.bucket, prefix=self.prefix, start=start, fields="name")
            out += [o.name for o in r.data.objects]; start = r.data.next_start_with
            if not start: return sorted(out)
            if len(out) > 100000: raise StoreError("registro de sello absurdamente largo")

    def read(self, name):
        try:
            return self.c.get_object(self.ns, self.bucket, name).data.content
        except Exception as e:  # noqa: BLE001
            if getattr(e, "status", None) == 404: return None
            raise StoreUnavailable(f"lectura: {type(e).__name__}")

    def create(self, name, data):
        if not name.startswith(self.prefix): raise StoreError("nombre fuera del prefijo")
        try:
            self.c.put_object(self.ns, self.bucket, name, data, if_none_match="*")
        except Exception as e:  # noqa: BLE001
            st = getattr(e, "status", None)
            if st in (412, 409): raise PreconditionFailed("la entrada ya existe")
            if st in (401, 403, 404): raise StoreError("denegado: la identidad no puede crear (¿política?)")     # sin OBJECT_CREATE (404 enmascarado por OCI)
            raise StoreUnavailable(f"escritura: {type(e).__name__}")


def make_sealer(log, oci_auth, ratchet=None, witness_report=None):
    """Lado OCI/orquestador: `sealer(epoch)` añade la entrada «sealed» (firmada por «oci») y, si se alcanza la base de AWS, sube SU trinquete (la guardia de reinicio lo repite cuando la RDS vuelva)."""
    def sealer(epoch):
        e = append(log, oci_auth, "oci", "sealed", int(epoch))
        if witness_report is not None:
            witness_report(e.seq, e.digest(), int(epoch))      # OBLIGATORIO: si el testigo no registra la cabeza, la promoción NO se completa (la entrada ya escrita solo puede BLOQUEAR a AWS: falla seguro)
        if ratchet is not None:
            try: ratchet.observe(e.seq)
            except Exception: pass                       # RDS detenida: lo hará la guardia de reinicio
        return e
    return sealer
