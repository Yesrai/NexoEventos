"""ANCLAJE ANTI-RETROCESO DEL TESTIGO (B-T6-1).

Problema: el historial del testigo vive en un almacén que, en la VM de Azure, es un archivo. Restaurar un prefijo antiguo y válido de ese archivo NO se detecta localmente.

Solución: cada entrada del historial se REPLICA, firmada por el testigo, en un almacén de ANCLAJE independiente (otro dominio de fallo; en producción un bucket de OCI con regla de retención BLOQUEADA, donde
los objetos `anchor/<seq>` solo se pueden crear una vez: ni sobrescribir ni borrar). El anclaje NO es «una copia del hash en un objeto sobrescribible»: son objetos distintos, uno por entrada, creados con la
precondición «no existe», encadenados por hash y firmados.

Reglas (todas fallan CERRADO; ningún informe ni atestación se sirve si no se cumplen):
  1. Orden de escritura: primero el almacén primario, después el anclaje. Así el anclaje NUNCA está por delante del primario salvo que el primario haya retrocedido.
  2. primario < anclaje  ⇒  ROLLBACK detectado (`RollbackDetected`): el servicio se bloquea hasta una recuperación explícita del operador (`recover_primary`).
  3. primario > anclaje  ⇒  fallo parcial (el primario se escribió y el anclaje no): se completa el anclaje (idempotente) ANTES de servir nada; si el anclaje no responde, 503.
  4. Prefijos comunes con hash distinto ⇒ bifurcación/alteración ⇒ StoreError.
  5. Objeto de anclaje ilegible, con firma inválida, fuera de secuencia o con la cadena rota ⇒ StoreError (corrupción).
  6. Anclaje vacío con primario de más de una entrada ⇒ ANCLAJE PERDIDO (StoreError); solo se permite arrancar un anclaje vacío con `bootstrap=True` explícito (migración controlada) o con la entrada de génesis en vuelo.
  7. Duplicados: crear de nuevo el mismo contenido es idempotente; contenido distinto bajo el mismo nombre ⇒ bifurcación ⇒ StoreError.
Garantía real de anti-rollback = (reglas anteriores) + inmutabilidad del anclaje (retención bloqueada y credencial sin permiso de borrar/sobrescribir). Sin esa retención el anclaje es solo detección.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

from .store import PreconditionFailed, StoreError, StoreUnavailable

GENESIS = "0" * 64


class RollbackDetected(StoreError):
    """El almacén primario del testigo está POR DEBAJO del anclaje: se restauró un historial antiguo. Bloquea hasta recuperación explícita."""


class AnchorLost(StoreError):
    """El anclaje desapareció o está vacío mientras el primario tiene historial."""


def _canon(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


# ───────────── almacenes de anclaje: create(name, data) condicional + read(name) -> bytes | None ─────────────
class FileAnchorBucket:
    """Anclaje en un DIRECTORIO (pruebas y demostración local): crear con O_EXCL, archivo de solo lectura. NO es inmutable frente a root/propietario; el anclaje real es el bucket con retención de OCI."""
    def __init__(self, directory):
        self.dir = Path(directory); self.dir.mkdir(parents=True, exist_ok=True)

    def create(self, name: str, data: bytes) -> None:
        p = self.dir / name; p.parent.mkdir(parents=True, exist_ok=True)
        try: fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        except FileExistsError: raise PreconditionFailed("el objeto de anclaje ya existe")
        with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())

    def read(self, name: str):
        try: return (self.dir / name).read_bytes()
        except FileNotFoundError: return None
        except OSError as e: raise StoreUnavailable(f"anclaje ilegible: {e}")


class SimAnchorBucket:
    """Bucket simulado en memoria con retención (worm=True: ni sobrescribir ni borrar). Con worm=False modela un atacante con permisos de escritura (CONTROL negativo). Hooks para fallos de red."""
    def __init__(self, worm: bool = True):
        self.o: dict[str, bytes] = {}; self.worm = worm; self._lock = threading.Lock()
        self.before = None; self.after = None           # callables(op, name): pueden lanzar StoreUnavailable (before: no llega; after: se aplicó pero se pierde la respuesta)

    def create(self, name, data):
        if self.before: self.before("create", name)
        with self._lock:
            if name in self.o: raise PreconditionFailed("el objeto de anclaje ya existe")
            self.o[name] = data
        if self.after: self.after("create", name)

    def read(self, name):
        if self.before: self.before("read", name)
        with self._lock: return self.o.get(name)

    # operaciones de ATACANTE (solo para pruebas)
    def put_blind(self, name, data):
        if self.worm: raise PreconditionFailed("retención: no se sobrescribe")
        self.o[name] = data

    def delete(self, name):
        if self.worm: raise PreconditionFailed("retención: no se borra")
        self.o.pop(name, None)


class OciParAnchorBucket:
    """Anclaje en un bucket de OCI mediante una PAR de ESCRITURA+LECTURA de objetos (SIN validar contra OCI real; requiere PAR autorizada). Crear = PUT con `If-None-Match: *` (412 ⇒ ya existe). Requiere que el bucket
    tenga una regla de retención BLOQUEADA para que los objetos no se puedan sobrescribir ni borrar. La URL de la PAR vive en un archivo 0600 (nunca en el repositorio)."""
    def __init__(self, par_url_file, timeout: float = 10.0, allowed_host_suffixes=("oraclecloud.com",), allow_http_localhost: bool = False):
        import stat
        import urllib.parse
        p = Path(par_url_file)
        if p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO): raise SystemExit("el archivo de la PAR de anclaje debe tener permisos 0600")
        self.base = p.read_text().strip().rstrip("/"); u = urllib.parse.urlparse(self.base); self.timeout = timeout
        local = allow_http_localhost and u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")
        if not local and (u.scheme != "https" or not any((u.hostname or "").endswith(s) for s in allowed_host_suffixes)): raise SystemExit("PAR de anclaje: se exige HTTPS a un host de OCI (TLS no se desactiva)")

    def __repr__(self): return "OciParAnchorBucket(<par oculta>)"

    def _do(self, method, name, data=None, headers=None):
        import urllib.error
        import urllib.request
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k): return None
        req = urllib.request.Request(f"{self.base}/{name}", data=data, method=method, headers=headers or {})
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=self.timeout) as r: return r.status, r.read()
        except urllib.error.HTTPError as e: return e.code, b""
        except (urllib.error.URLError, OSError) as e: raise StoreUnavailable(f"anclaje inaccesible: {type(e).__name__}")

    def create(self, name, data):
        st, _ = self._do("PUT", name, data, {"If-None-Match": "*", "Content-Type": "application/json"})
        if st in (200, 201): return
        if st in (409, 412): raise PreconditionFailed("el objeto de anclaje ya existe")
        raise StoreUnavailable(f"anclaje: respuesta inesperada {st}")

    def read(self, name):
        st, body = self._do("GET", name)
        if st == 200: return body
        if st == 404: return None
        raise StoreUnavailable(f"anclaje: respuesta inesperada {st}")


# ───────────── almacén anclado ─────────────
class AnchoredAppendStore:
    """Envuelve un almacén de solo adición (`lines()`/`append(line, seq)`) y lo ancla. Se usa donde Witness espera su almacén."""
    def __init__(self, primary, anchor, signer, verifier, bootstrap: bool = False):
        self.primary, self.anchor, self.signer, self.verifier, self.bootstrap = primary, anchor, signer, verifier, bootstrap
        self.path = getattr(primary, "path", None)
        self._lock = threading.RLock(); self._n = 0; self._last = GENESIS; self._lines: list[str] = []      # prefijo del anclaje ya verificado (el anclaje no retrocede: con retención solo crece)

    # --- objetos de anclaje ---
    @staticmethod
    def _name(seq: int) -> str: return f"anchor/{seq:012d}"

    def _wrap(self, line: str) -> bytes:
        e = json.loads(line); body = {"seq": e["seq"], "hash": e["hash"], "prev": e["prev"], "line": line}
        return json.dumps({**body, "sig": self.signer.sign("witness", _canon(body))}).encode()

    def _unwrap(self, raw: bytes, seq: int, prev: str) -> str:
        try:
            d = json.loads(raw); body = {k: d[k] for k in ("seq", "hash", "prev", "line")}; sig = d["sig"]; e = json.loads(body["line"])
            ok = (body["seq"] == seq == e["seq"] and body["prev"] == prev == e["prev"] and body["hash"] == e["hash"]
                  and hashlib.sha256(_canon({k: e[k] for k in ("seq", "prev", "reporter", "payload", "sig")})).hexdigest() == e["hash"])
        except (ValueError, KeyError, TypeError): raise StoreError(f"objeto de anclaje {seq} CORRUPTO")
        if not ok: raise StoreError(f"objeto de anclaje {seq} incoherente (secuencia/cadena/hash)")
        if not self.verifier.verify("witness", _canon(body), sig): raise StoreError(f"objeto de anclaje {seq}: firma del testigo INVÁLIDA")
        return body["line"]

    def _refresh_anchor(self) -> None:
        """Lee del anclaje las entradas nuevas (sondeo secuencial hasta el primer hueco) verificando firma y cadena."""
        while True:
            raw = self.anchor.read(self._name(self._n + 1))
            if raw is None: break
            line = self._unwrap(raw, self._n + 1, self._last)
            self._lines.append(line); self._n += 1; self._last = json.loads(line)["hash"]
        # un objeto POSTERIOR a un hueco significa que se borró una entrada intermedia: se comprueba un hueco de hasta 3 posiciones
        for gap in (2, 3):
            if self.anchor.read(self._name(self._n + gap)) is not None: raise StoreError("el anclaje tiene un HUECO (entrada intermedia borrada)")

    def _anchor_put(self, line: str) -> None:
        e = json.loads(line)
        try: self.anchor.create(self._name(e["seq"]), self._wrap(line))
        except PreconditionFailed:
            raw = self.anchor.read(self._name(e["seq"]))
            if raw is None: raise StoreUnavailable("anclaje en estado incierto")
            if self._unwrap(raw, e["seq"], e["prev"]) != line: raise StoreError("BIFURCACIÓN: el anclaje ya tiene otra entrada con esa secuencia")      # idéntico ⇒ idempotente (duplicado / reintento tras fallo parcial)

    # --- interfaz de almacén ---
    def lines(self) -> list[str]:
        with self._lock:
            self._refresh_anchor()
            pl = self.primary.lines(); n = len(pl)
            for i in range(min(n, self._n)):
                if pl[i] != self._lines[i]: raise StoreError(f"BIFURCACIÓN: el historial primario difiere del anclado en la entrada {i + 1}")
            if n < self._n: raise RollbackDetected(f"ROLLBACK: el historial del testigo tiene {n} entradas y el anclaje {self._n}: se restauró un prefijo antiguo. Se BLOQUEA hasta recuperación explícita")
            if n > self._n:
                if self._n == 0 and n > 1 and not self.bootstrap: raise AnchorLost("ANCLAJE PERDIDO o vacío con historial existente: no se re-ancla sin `bootstrap` explícito")
                for line in pl[self._n:]:                                               # fallo parcial anterior: completar el anclaje ANTES de servir nada
                    e = json.loads(line); self._anchor_put(line); self._lines.append(line); self._n = e["seq"]; self._last = e["hash"]
            return pl

    def append(self, line: str, seq: int | None = None) -> None:
        with self._lock:
            self.lines()                                                                 # estado verificado y anclado al día antes de escribir
            self.primary.append(line, seq)                                               # 1) primario (condicional)
            e = json.loads(line)
            self._anchor_put(line)                                                       # 2) anclaje; si falla ⇒ StoreUnavailable y el siguiente lines() lo completa
            self._lines.append(line); self._n = e["seq"]; self._last = e["hash"]

    def recover_primary(self, confirm: str) -> int:
        """Recuperación EXPLÍCITA tras un ROLLBACK: reescribe en el primario las entradas que faltan, copiadas del anclaje verificado. Exige la frase de confirmación del operador. No toca el anclaje."""
        if confirm != "RECUPERAR-PRIMARIO-DESDE-ANCLAJE": raise StoreError("falta la confirmación explícita del operador")
        with self._lock:
            self._refresh_anchor(); pl = self.primary.lines(); n = len(pl)
            for i in range(min(n, self._n)):
                if pl[i] != self._lines[i]: raise StoreError("el primario difiere del anclaje en un prefijo: no se recupera automáticamente")
            for line in self._lines[n:]: self.primary.append(line, json.loads(line)["seq"])
            return self._n - n
