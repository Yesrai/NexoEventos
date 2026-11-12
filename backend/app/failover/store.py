"""Almacenes de objetos con ESCRITURAS CONDICIONALES para el lease (B-10). Solo biblioteca estándar.

Contrato (lo que el lease necesita y NADA más):
  read()               -> ObjectVersion(data, etag) | None
  create(data)         -> etag                    solo si el objeto NO existe        (HTTP: If-None-Match: *)
  replace(etag, data)  -> etag nuevo              solo si el ETag actual == etag     (HTTP: If-Match: <etag>)
Errores: PreconditionFailed (412: otro escritor cambió el objeto), StoreUnavailable (red/tiempo/5xx: el resultado de la escritura es INCIERTO), StoreError.

Qué se verificó (documentación oficial, 11-nov-2026): OCI Object Storage PutObject admite If-Match e If-None-Match («*») y es fuertemente consistente (nivel Standard);
Amazon S3 admite ambos (412/409) y Azure Blob admite If-Match/If-None-Match. Qué NO se verificó: el comportamiento REAL de nuestro bucket/cuenta de Academy/OCI.
Por eso un almacén solo se usa si pasa `verify_store_semantics` (autoprueba) y queda marcado `verified=True`; el cliente de lease rechaza almacenes no verificados (falla cerrado).
OJO: el ETag por sí solo NO evita las carreras; las evita que el servidor aplique `If-Match` de forma ATÓMICA. Lo que el ETag no resuelve (reloj, procesos pausados, vallado) lo cubre lease.py/gate.py.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path


class StoreError(Exception):
    pass


class PreconditionFailed(StoreError):
    """El objeto cambió (o ya existe): la escritura NO se aplicó."""


class StoreUnavailable(StoreError):
    """No se pudo completar la operación; si era una escritura, puede haberse aplicado o no (resultado incierto)."""


@dataclass(frozen=True)
class ObjectVersion:
    data: bytes
    etag: str


class ConditionalStore:
    ATOMIC_CREATE = True          # create() es atómico en el servidor
    verified = False              # lo fija verify_store_semantics()

    def read(self) -> ObjectVersion | None: raise NotImplementedError
    def create(self, data: bytes) -> str: raise NotImplementedError
    def replace(self, etag: str, data: bytes) -> str: raise NotImplementedError


class InMemoryStore(ConditionalStore):
    """Almacén de referencia con la semántica exacta que se exige a los reales (hilos). Hooks de fallos para simulaciones."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: bytes | None = None
        self._gen = 0
        self.before_op = None      # callable(op) -> None | puede lanzar StoreUnavailable (se aplica ANTES: la operación no llega)
        self.after_apply = None    # callable(op) -> None | puede lanzar StoreUnavailable (se aplica DESPUÉS: la escritura se aplicó pero la respuesta se pierde)

    def _etag(self) -> str:
        return f"{self._gen}-{hashlib.sha256(self._data or b'').hexdigest()[:12]}"

    def read(self):
        if self.before_op: self.before_op("read")
        with self._lock:
            res = None if self._data is None else ObjectVersion(self._data, self._etag())
        if self.after_apply: self.after_apply("read")
        return res

    def create(self, data):
        if self.before_op: self.before_op("create")
        with self._lock:
            if self._data is not None:
                raise PreconditionFailed("el objeto ya existe")
            self._gen += 1; self._data = data; etag = self._etag()
        if self.after_apply: self.after_apply("create")
        return etag

    def replace(self, etag, data):
        if self.before_op: self.before_op("replace")
        with self._lock:
            if self._data is None or self._etag() != etag:
                raise PreconditionFailed("ETag distinto")
            self._gen += 1; self._data = data; new = self._etag()
        if self.after_apply: self.after_apply("replace")
        return new


class FileStore(ConditionalStore):
    """Almacén en archivo con bloqueo `flock` y reemplazo atómico: semántica real entre PROCESOS (pruebas y demostraciones locales)."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path); self.lock_path = Path(str(path) + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _locked(self):
        import fcntl
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _load(self):
        if not self.path.exists():
            return None
        doc = json.loads(self.path.read_text())
        return doc["gen"], base64.b64decode(doc["data"])

    def _etag(self, gen, data): return f"{gen}-{hashlib.sha256(data).hexdigest()[:12]}"

    def _write(self, gen, data):
        tmp = self.path.with_name(self.path.name + f".{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp")
        tmp.write_text(json.dumps({"gen": gen, "data": base64.b64encode(data).decode()}))
        with open(tmp, "rb") as f: os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def read(self):
        fd = self._locked()
        try:
            cur = self._load()
            return None if cur is None else ObjectVersion(cur[1], self._etag(*cur))
        finally:
            os.close(fd)

    def create(self, data):
        fd = self._locked()
        try:
            if self._load() is not None:
                raise PreconditionFailed("el objeto ya existe")
            self._write(1, data); return self._etag(1, data)
        finally:
            os.close(fd)

    def replace(self, etag, data):
        fd = self._locked()
        try:
            cur = self._load()
            if cur is None or self._etag(*cur) != etag:
                raise PreconditionFailed("ETag distinto")
            self._write(cur[0] + 1, data); return self._etag(cur[0] + 1, data)
        finally:
            os.close(fd)


class OciCliStore(ConditionalStore):
    """Adaptador sobre la CLI de OCI (`oci os object head/get/put`). NO verificado contra OCI real: requiere `verify_store_semantics` en la nube antes de usarse.

    - replace() usa `--if-match <etag> --force` (CAS; la CLI lo traduce a If-Match en PutObject).
    - create() usa `--no-overwrite`: NO está demostrado que sea atómico (puede comprobarse en el cliente). Por eso ATOMIC_CREATE = False y el lease solo lo permite en la
      inicialización manual (init_lease), nunca en el camino de adquisición/renovación.
    - La lectura consistente exige que el ETag de `head` sea el mismo antes y después de `get`.
    """
    ATOMIC_CREATE = False

    def __init__(self, namespace, bucket, object_name, profile, oci_bin="oci", runner=None, timeout=20):
        self.ns, self.bucket, self.name, self.profile, self.oci, self.timeout = namespace, bucket, object_name, profile, oci_bin, timeout
        self._run = runner or (lambda argv: subprocess.run(argv, capture_output=True, timeout=timeout))

    def _base(self, *sub):
        return [self.oci, "os", "object", *sub, "--profile", self.profile, "--namespace-name", self.ns, "--bucket-name", self.bucket]

    def _call(self, argv):
        try:
            cp = self._run(argv)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise StoreUnavailable(f"CLI no disponible: {type(e).__name__}")
        return cp

    @staticmethod
    def _err(cp) -> str:
        return (cp.stderr or b"").decode("utf-8", "replace") if isinstance(cp.stderr, bytes) else str(cp.stderr or "")

    def _head(self):
        cp = self._call(self._base("head") + ["--name", self.name])
        if cp.returncode == 0:
            out = cp.stdout.decode() if isinstance(cp.stdout, bytes) else cp.stdout
            try:
                return str(json.loads(out)["etag"]).strip('"')
            except (ValueError, KeyError):
                raise StoreUnavailable("respuesta de head sin etag")
        err = self._err(cp)
        if "ObjectNotFound" in err or "404" in err:
            return None
        raise StoreUnavailable("head falló")

    def read(self):
        for _ in range(3):
            e1 = self._head()
            if e1 is None:
                return None
            cp = self._call(self._base("get") + ["--name", self.name, "--file", "-"])
            if cp.returncode != 0:
                raise StoreUnavailable("get falló")
            e2 = self._head()
            if e1 == e2:
                return ObjectVersion(cp.stdout if isinstance(cp.stdout, bytes) else cp.stdout.encode(), e1)
        raise StoreUnavailable("lectura inconsistente (el ETag cambió durante la lectura)")

    def _put(self, extra, data):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "obj"; f.write_bytes(data); os.chmod(f, 0o600)
            cp = self._call(self._base("put") + ["--name", self.name, "--file", str(f)] + extra + ["--output", "json"])
        if cp.returncode == 0:
            out = cp.stdout.decode() if isinstance(cp.stdout, bytes) else cp.stdout
            try:
                return str(json.loads(out)["etag"]).strip('"')
            except (ValueError, KeyError):
                raise StoreUnavailable("put sin etag en la respuesta (resultado incierto)")
        err = self._err(cp)
        if any(k in err for k in ("IfMatchFailed", "412", "PreconditionFailed", "already exists", "NoOverwrite")):
            raise PreconditionFailed("precondición no cumplida")
        raise StoreUnavailable("put falló (resultado incierto)")

    def create(self, data):
        return self._put(["--no-overwrite"], data)

    def replace(self, etag, data):
        return self._put(["--if-match", etag, "--force"], data)


def verify_store_semantics(make_store, writers: int = 16) -> dict:
    """Autoprueba de las operaciones condicionales. `make_store()` devuelve un almacén NUEVO (objeto vacío). Devuelve {prueba: bool}; marca `verified` solo si TODAS pasan.
    Para un almacén real usar un nombre de objeto de prueba exclusivo (p. ej. lease-selftest-<uuid>) y borrarlo después."""
    rep: dict[str, bool] = {}
    s = make_store()
    rep["create_vacío_ok"] = _ok(lambda: s.create(b"v0"))
    if s.ATOMIC_CREATE:
        try:
            s.create(b"otro"); rep["create_duplicado_rechazado"] = False
        except PreconditionFailed:
            rep["create_duplicado_rechazado"] = True
    else:
        rep["create_duplicado_rechazado"] = True    # no aplica: create no se usa en producción
    rv = s.read()
    rep["lee_lo_escrito"] = rv is not None and rv.data == b"v0"
    e1 = s.replace(rv.etag, b"v1") if rv else None
    rep["cas_con_etag_actual_ok"] = bool(e1) and e1 != rv.etag
    try:
        s.replace(rv.etag, b"viejo"); rep["cas_con_etag_viejo_rechazado"] = False
    except PreconditionFailed:
        rep["cas_con_etag_viejo_rechazado"] = True
    rv2 = s.read()
    rep["lectura_inmediata_tras_escribir"] = rv2 is not None and rv2.data == b"v1" and rv2.etag == e1
    # Carrera: N escritores con el MISMO ETag → exactamente 1 gana.
    wins, lock = [], threading.Lock()

    def attempt(i):
        try:
            s.replace(rv2.etag, f"w{i}".encode())
            with lock: wins.append(i)
        except PreconditionFailed:
            pass
        except StoreError:
            pass
    ts = [threading.Thread(target=attempt, args=(i,)) for i in range(writers)]
    [t.start() for t in ts]; [t.join() for t in ts]
    rep["carrera_exactamente_un_ganador"] = len(wins) == 1
    s.verified = all(rep.values())
    return rep


def _ok(fn) -> bool:
    try:
        fn(); return True
    except StoreError:
        return False
