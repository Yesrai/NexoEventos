"""TESTIGO DE FRESCURA INDEPENDIENTE: la referencia que NO puede retroceder junto con el lease, el registro del sello y la base de AWS.

El ataque: un atacante restaura a la vez (a) el registro del lease, (b) el registro del sello y (c) la base de AWS/su trinquete a un estado ANTIGUO pero coherente y con firmas válidas; después arranca una instancia AWS nueva. Nada de lo que vive
en esos tres sitios puede decir «esto es viejo»: el lease, el sello y el trinquete retroceden juntos y las cadenas de hashes y firmas siguen siendo válidas. Hace falta una referencia que viva FUERA de los tres y que solo avance.

Diseño: un servicio mínimo (el TESTIGO), con su propia clave de firma y su propio almacén de solo adición, que:
  · RECIBE informes FIRMADOS de quienes mandan (OCI al promover/sellar, los titulares del lease al adquirir, el operador al hacer failback) y solo acepta AVANCES (época del lease y cabeza del sello nunca bajan; una cabeza distinta con la misma
    secuencia es un conflicto y se rechaza). Cada informe se encadena (hash) y se persiste con fsync: el almacén se verifica al arrancar y cualquier alteración lo detiene.
  · RESPONDE a un RETO (nonce aleatorio del consumidor) con la marca de agua actual FIRMADA y fechada: una respuesta vieja no sirve (el nonce no coincide) ni aunque tenga firma válida.
El consumidor (AWS) solo adquiere autoridad si: el testigo responde, la firma es del testigo anclado en la configuración, el nonce es el suyo, la fecha es reciente, y el lease y el sello que ve NO están por debajo de la marca de agua.
Si el testigo no responde, está sin inicializar o la respuesta no verifica: BLOQUEA (falla cerrado). El testigo ES el punto de confianza: debe vivir en otro dominio de fallo y de confianza (ver docs: almacenamiento inmutable fuera de AWS y OCI)."""
from __future__ import annotations

import hashlib
import threading
import json
import os
import secrets
import time
from pathlib import Path

from .store import PreconditionFailed, StoreError, StoreUnavailable

GENESIS = "0" * 64
KINDS = {"genesis": {"operator"}, "lease_epoch": {"aws", "oci"}, "seal_head": {"oci", "operator"}}


def _canon(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


class FileAppendStore:
    """Almacén de solo adición en un archivo JSONL (desarrollo y pruebas). `append(line, seq)` es CONDICIONAL: solo escribe si la línea nº `seq` es la siguiente (bloqueo de archivo entre procesos); si otro escribió antes, lanza
    PreconditionFailed y quien llama relee y reintenta. REQUISITO del almacén real: la misma operación atómica de «crear si no existe» (Cloud Storage: ifGenerationMatch=0 sobre `log/<seq>`)."""
    def __init__(self, path): self.path = Path(path)
    def lines(self) -> list[str]: return self.path.read_text().splitlines() if self.path.exists() else []
    def append(self, line: str, seq: int | None = None) -> None:
        import fcntl
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if seq is not None:
                with open(self.path) as f: n = sum(1 for _ in f)
                if n != seq - 1: raise PreconditionFailed("otra instancia ya escribió ese número de secuencia")
            os.write(fd, (line + "\n").encode()); os.fsync(fd)
        finally: os.close(fd)


class ObjectAppendStore:
    """Almacén de solo adición sobre un BUCKET de objetos: cada informe es un objeto NUEVO `log/<seq>` creado con la precondición «no existe» (ifGenerationMatch=0 en Cloud Storage). Con la retención del bucket,
    el servicio impide sobrescribir y borrar. `bucket` expone create(name, data) (lanza PreconditionFailed si existe), read(name) y names(). Adaptador real: GcsAppendStore (sin validar contra Google Cloud)."""
    def __init__(self, bucket): self.b = bucket
    def lines(self) -> list[str]: return [self.b.read(n).decode() for n in sorted(self.b.names())]
    def append(self, line: str, seq: int | None = None) -> None:
        seq = seq if seq is not None else len(self.b.names()) + 1
        self.b.create(f"log/{seq:012d}", line.encode())                                   # crear-si-no-existe ATÓMICO: si otra instancia usó ese número, falla (PreconditionFailed)


class ImmutableBucketSim:
    """Simula un bucket con retención: crear una vez, jamás sobrescribir ni borrar (CONTROL: con worm=False un atacante con permisos SÍ puede reemplazar o borrar)."""
    def __init__(self, worm: bool = True): self.o, self.worm = {}, worm
    def create(self, name, data):
        if name in self.o: raise PreconditionFailed("el objeto ya existe (ifGenerationMatch=0)")
        self.o[name] = data
    def read(self, name): return self.o[name]
    def names(self): return sorted(self.o)
    def put_blind(self, name, data):
        if self.worm and name in self.o: raise PreconditionFailed("retención: no se sobrescribe")
        self.o[name] = data
    def delete(self, name):
        if self.worm: raise PreconditionFailed("retención: no se borra")
        self.o.pop(name, None)


class GcsAppendStore(ObjectAppendStore):
    """Adaptador de Cloud Storage (SIN validar contra Google Cloud). Requiere google-cloud-storage. Crea con if_generation_match=0; la cuenta de servicio del testigo solo necesita storage.objects.create + storage.objects.get/list:
    NO tiene storage.objects.delete ni update (roles/storage.objectCreator + roles/storage.objectViewer), y el bucket lleva retención."""
    def __init__(self, bucket_name: str, client=None):
        from google.cloud import storage  # noqa: PLC0415
        self._c = client or storage.Client(); self._bk = self._c.bucket(bucket_name)
        class B:
            def create(_s, name, data):
                from google.api_core.exceptions import PreconditionFailed as PF  # noqa: PLC0415
                try: self._bk.blob(name).upload_from_string(data, if_generation_match=0)
                except PF: raise PreconditionFailed("el objeto ya existe")
            def read(_s, name): return self._bk.blob(name).download_as_bytes()
            def names(_s): return sorted(b.name for b in self._c.list_blobs(self._bk, prefix="log/"))
        super().__init__(B())


class Witness:
    """Lógica del servicio. En producción vive en un servicio independiente; `store` es un almacén de solo adición (archivo, o bucket con retención)."""
    def __init__(self, path, witness_auth, reporters_verifier, now=time.time, seal_verifier=None, max_epoch_jump: int = 8):
        self.seal_verifier, self.max_epoch_jump = seal_verifier, max_epoch_jump       # seal_verifier(seq, digest) -> bool: comprueba contra el registro del sello (solo lectura) que la cabeza informada EXISTE y es válida
        self.store = path if hasattr(path, "lines") else FileAppendStore(path)
        self.path = getattr(self.store, "path", None); self.auth, self.reporters, self.now = witness_auth, reporters_verifier, now
        self.down = False
        self._lock = threading.RLock()     # una instancia es SEGURA entre hilos: (entries, last_hash, wm) se leen y escriben siempre juntos (antes se podía leer «secuencia nueva + hash viejo» y romper la cadena)
        self.wm: dict | None = None; self.entries = 0; self.last_hash = GENESIS
        self._sync()

    def _sync(self) -> None:
        """Recarga del almacén las entradas que OTRAS instancias hayan añadido (verificando la cadena): así dos instancias del servicio nunca trabajan con un estado atrasado ni pierden actualizaciones."""
        for line in self.store.lines()[self.entries:]:
            e = json.loads(line)
            if e["prev"] != self.last_hash or hashlib.sha256(_canon({k: e[k] for k in ("seq", "prev", "reporter", "payload", "sig")})).hexdigest() != e["hash"]:
                raise StoreError("el almacén del testigo está ALTERADO (cadena rota): el servicio no arranca")
            self._apply(e["payload"]); self.entries += 1; self.last_hash = e["hash"]

    def _apply(self, p: dict):
        wm = self.wm or {"lease_epoch": 0, "seal_seq": 0, "seal_digest": None}
        if p["kind"] == "genesis": wm = {"lease_epoch": int(p["lease_epoch"]), "seal_seq": int(p["seal_seq"]), "seal_digest": p["seal_digest"]}
        elif p["kind"] == "lease_epoch": wm["lease_epoch"] = max(wm["lease_epoch"], int(p["lease_epoch"]))
        elif p["kind"] == "seal_head": wm["seal_seq"], wm["seal_digest"] = int(p["seal_seq"]), p["seal_digest"]
        self.wm = wm

    def report(self, reporter: str, payload: dict, sig: str) -> tuple[bool, str]:
        if self.down: raise StoreUnavailable("testigo caído")
        for _ in range(50):                                                                              # carrera con otra instancia: se relee y se REVALIDA contra el estado nuevo
            try: return self._report_once(reporter, payload, sig)
            except PreconditionFailed: continue
        raise StoreUnavailable("demasiada contención al informar")

    def _report_once(self, reporter: str, payload: dict, sig: str) -> tuple[bool, str]:
        with self._lock: return self._report_once_locked(reporter, payload, sig)

    def _report_once_locked(self, reporter: str, payload: dict, sig: str) -> tuple[bool, str]:
        self._sync()
        k = payload.get("kind")
        if k not in KINDS or reporter not in KINDS[k]: return False, "informante no autorizado para ese tipo de informe"
        if not self.reporters.verify(reporter, _canon(payload), sig): return False, "firma del informe inválida"
        if k == "genesis":
            if self.wm is not None: return False, "el testigo ya está inicializado"
        else:
            if self.wm is None: return False, "testigo sin inicializar"
            if k == "lease_epoch" and int(payload["lease_epoch"]) < self.wm["lease_epoch"]: return False, "RETROCESO: la época del lease no puede bajar"
            if k == "lease_epoch" and int(payload["lease_epoch"]) > self.wm["lease_epoch"] + self.max_epoch_jump: return False, "salto de época absurdo: un informante comprometido no puede «envenenar» el testigo con una época enorme"
            if k == "seal_head":
                s, d = int(payload["seal_seq"]), payload["seal_digest"]
                if s < self.wm["seal_seq"]: return False, "RETROCESO: la cabeza del sello no puede bajar"
                if s == self.wm["seal_seq"] and d != self.wm["seal_digest"]: return False, "CONFLICTO: otra entrada con la misma secuencia"
                if self.seal_verifier is not None:
                    try: real = bool(self.seal_verifier(s, d))
                    except Exception: real = False
                    if not real: return False, "la cabeza informada NO existe o no es válida en el registro del sello (no se acepta un informe sin respaldo)"
        body = {"seq": self.entries + 1, "prev": self.last_hash, "reporter": reporter, "payload": payload, "sig": sig}
        h = hashlib.sha256(_canon(body)).hexdigest(); line = json.dumps({**body, "hash": h})
        self.store.append(line, self.entries + 1)                                                        # SOLO ADICIÓN, condicional a que nadie haya usado ese número, y durable ANTES de contestar
        self._apply(payload); self.entries += 1; self.last_hash = h; return True, "ok"

    def attest(self, nonce: str) -> dict:
        with self._lock: return self._attest_locked(nonce)

    def _attest_locked(self, nonce: str) -> dict:
        if self.down: raise StoreUnavailable("testigo caído")
        self._sync()                                                                                     # nunca atestar con un estado más viejo que el del almacén
        body = {"nonce": nonce, "watermark": self.wm, "issued_at": self.now(), "entries": self.entries, "head": self.last_hash}
        return {**body, "sig": self.auth.sign("witness", _canon(body))}

    def report_with_receipt(self, reporter: str, payload: dict, sig: str) -> dict:
        """Como report(), pero devuelve un RECIBO firmado por el testigo {seq, hash}: prueba de que el informe quedó en su cadena (se puede volver a comprobar con entry(seq))."""
        with self._lock:     # el recibo describe EXACTAMENTE la entrada que este informe acaba de escribir
            ok, why = self.report(reporter, payload, sig)
            if not ok: return {"ok": False, "reason": why}
            body = {"seq": self.entries, "hash": self.last_hash, "reporter": reporter}
            return {"ok": True, "reason": why, **body, "sig": self.auth.sign("witness", _canon({"receipt": body}))}

    def entry(self, seq: int) -> dict | None:
        if self.down: raise StoreUnavailable("testigo caído")
        ls = self.store.lines()
        return json.loads(ls[seq - 1]) if 1 <= seq <= len(ls) else None


class LocalWitnessClient:
    """Cliente en proceso (pruebas). En producción: HTTPS con la clave pública del testigo anclada en la configuración."""
    def __init__(self, witness): self.w = witness
    def attest(self, nonce): return self.w.attest(nonce)
    def report(self, reporter, payload, sig): return self.w.report(reporter, payload, sig)


def make_report(auth, reporter: str, **payload) -> tuple[str, dict, str]:
    return reporter, payload, auth.sign(reporter, _canon(payload))


class _Reject(Exception):
    pass


class _Unreachable(_Reject):
    pass


class WitnessMemory:
    """Memoria LOCAL del consumidor sobre el testigo (archivo 0600): última cantidad de informes, cabeza y marca de agua vistas. Un testigo que RETROCEDE (almacén restaurado a un prefijo válido) se delata ante cualquier
    consumidor que ya lo hubiera visto más adelante. No protege a un consumidor totalmente nuevo: para eso están el almacén inmutable del testigo y el QUÓRUM de testigos."""
    def __init__(self, path):
        self.path = Path(path)
    def load(self) -> dict:
        try: return json.loads(self.path.read_text())
        except (OSError, ValueError): return {}
    def check_and_update(self, att: dict) -> None:
        m = self.load(); wm = att.get("watermark") or {}
        if m:
            if att["entries"] < m["entries"] or (att["entries"] == m["entries"] and att.get("head") != m["head"]): raise _Reject("el testigo RETROCEDIÓ respecto a lo que este nodo ya había visto (historial restaurado o testigo sustituido)")
            for k in ("lease_epoch", "seal_seq"):
                if wm.get(k, 0) < m["wm"].get(k, 0): raise _Reject(f"la marca de agua del testigo bajó ({k}): testigo restaurado")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f: json.dump({"entries": att["entries"], "head": att.get("head"), "wm": wm}, f)


class WitnessGuard:
    """Guardia de adquisición/renovación en AWS: exige una atestación FRESCA del testigo y rechaza todo lo que esté por debajo de su marca de agua. Falla cerrado."""
    def __init__(self, client, verifier, log=None, max_age_s: float = 30.0, now=time.time, nonce=lambda: secrets.token_hex(16), memory: "WitnessMemory | None" = None, renew_grace_s: float = 0.0):
        """`renew_grace_s`: ante una caída del testigo (p. ej. de Google Cloud) un titular que YA tenía autoridad con una atestación válida reciente puede RENOVAR la MISMA época durante esta gracia (no hay doble escritura: nadie puede
        ADQUIRIR). Una instancia nueva, o una época distinta, se bloquea de inmediato."""
        self.client, self.verifier, self.log, self.max_age_s, self.now, self.nonce, self.memory = client, verifier, log, max_age_s, now, nonce, memory
        self.renew_grace_s, self._last_ok, self._last_epoch = renew_grace_s, None, None
        self.rejects: list[str] = []

    def _no(self, why): self.rejects.append(why); return False, why

    def attestation(self, client=None, verifier=None) -> dict:
        """Obtiene y VERIFICA una atestación (firma del testigo anclado, reto propio, fecha reciente). Lanza _Reject."""
        n = self.nonce()
        try: att = (client or self.client).attest(n)
        except Exception: raise _Unreachable("testigo de frescura INACCESIBLE: sin referencia independiente no se adquiere autoridad (falla cerrado)")
        try:
            body = {k: v for k, v in att.items() if k != "sig"}
            if not (verifier or self.verifier).verify("witness", _canon(body), att["sig"]): raise _Reject("la atestación del testigo NO verifica (firma)")
            _ = body["nonce"], body["watermark"], body["issued_at"], body["entries"]
        except _Reject: raise
        except Exception: raise _Reject("atestación del testigo ilegible")
        if att["nonce"] != n: raise _Reject("atestación de OTRO reto (reproducción): se rechaza")
        if abs(self.now() - float(att["issued_at"])) > self.max_age_s: raise _Reject("atestación del testigo CADUCADA")
        if not att["watermark"]: raise _Reject("testigo SIN INICIALIZAR (falta el informe de génesis del operador)")
        return att

    def _against(self, wm: dict, lease_epoch):
        if lease_epoch is not None and lease_epoch < wm["lease_epoch"]:
            raise _Reject(f"RETROCESO del lease: el testigo ya vio la época {wm['lease_epoch']} y este registro es de la {lease_epoch}")
        if self.log is not None and wm["seal_seq"]:
            try:
                names = self.log.names()
                if len(names) < wm["seal_seq"]: raise _Reject(f"TRUNCAMIENTO del sello: el testigo vio la entrada {wm['seal_seq']} y el registro solo tiene {len(names)}")
                from .seal_log import Entry, _name
                e = Entry.load(self.log.read(_name(wm["seal_seq"])))
                if e.digest() != wm["seal_digest"]: raise _Reject("el registro del sello tiene OTRA historia que la anclada en el testigo")
            except (StoreError, OSError): raise _Reject("no se pudo comprobar el registro del sello frente al testigo (falla cerrado)")

    def __call__(self, lease_epoch=None, lease_head=None):
        try:
            att = self.attestation()
            if self.memory is not None: self.memory.check_and_update(att)
            self._against(att["watermark"], lease_epoch)
        except _Unreachable as e:
            if self.renew_grace_s and lease_epoch is not None and lease_epoch == self._last_epoch and self._last_ok is not None and self.now() - self._last_ok <= self.renew_grace_s:
                return True, "testigo caído: renovación de la MISMA época tolerada durante la gracia"
            return self._no(str(e))
        except _Reject as e:
            return self._no(str(e))
        if lease_epoch is not None: self._last_epoch = lease_epoch
        self._last_ok = self.now()
        return True, "ok"


class QuorumWitnessGuard(WitnessGuard):
    """QUÓRUM de testigos independientes (p. ej. uno en Google Cloud y otro en otra nube/cuenta): hacen falta ≥ k atestaciones válidas y frescas; la marca de agua efectiva es el MÁXIMO de las válidas, así que
    el atacante debe haber retrocedido k testigos a la vez; si dos testigos dan cabezas distintas para la misma secuencia, se bloquea (conflicto). Un testigo por detrás de los demás se anota en `behind` (alerta)."""
    def __init__(self, members: list, k: int, log=None, max_age_s: float = 30.0, now=time.time, nonce=lambda: secrets.token_hex(16)):
        super().__init__(None, None, log, max_age_s, now, nonce); self.members, self.k = members, k; self.behind: list[str] = []; self.last_errors: dict = {}      # members: [(nombre, cliente, verificador)]

    def __call__(self, lease_epoch=None, lease_head=None):
        valid, errs = [], {}
        for name, client, verifier in self.members:
            try: valid.append((name, self.attestation(client, verifier)))
            except _Reject as e: errs[name] = str(e)
        self.last_errors = errs
        if len(valid) < self.k: return self._no(f"quórum de testigos NO alcanzado ({len(valid)}/{self.k}): " + "; ".join(f"{n}: {e}" for n, e in errs.items()))
        top = max(valid, key=lambda x: (x[1]["watermark"]["lease_epoch"], x[1]["watermark"]["seal_seq"]))[1]["watermark"]
        wm = {"lease_epoch": max(a["watermark"]["lease_epoch"] for _, a in valid), "seal_seq": max(a["watermark"]["seal_seq"] for _, a in valid), "seal_digest": top["seal_digest"]}
        for n, a in valid:
            if a["watermark"]["seal_seq"] == wm["seal_seq"] and a["watermark"]["seal_digest"] != wm["seal_digest"]: return self._no("CONFLICTO entre testigos: cabezas distintas para la misma secuencia del sello")
        self.behind = [n for n, a in valid if (a["watermark"]["lease_epoch"], a["watermark"]["seal_seq"]) < (wm["lease_epoch"], wm["seal_seq"])]
        try: self._against(wm, lease_epoch)
        except _Reject as e: return self._no(str(e))
        return True, "ok"


class CompositeGuard:
    """Todas las guardias deben autorizar (testigo + registro del sello)."""
    def __init__(self, *guards): self.guards = guards
    def __call__(self, lease_epoch=None, lease_head=None):
        for g in self.guards:
            try: ok, why = g(lease_epoch, lease_head)
            except TypeError: ok, why = g(lease_epoch)
            if not ok: return False, why
        return True, "ok"


class HttpWitnessClientBase:
    pass


class HttpWitnessClient:
    """Cliente HTTPS del testigo: GET <url>?nonce=<n> → JSON de la atestación. La URL va en un archivo 0600; solo https (http a localhost solo en pruebas); sin redirecciones. NO hay todavía un servicio real."""
    def __init__(self, url_file, timeout: float = 5.0, allow_http_localhost: bool = False, token_file=None, ca_file=None):
        import ssl
        import stat
        import urllib.parse
        import urllib.request
        # token_file: token Bearer del INVOCADOR (archivo 0600; el servicio solo guarda su SHA-256). ca_file: certificado/CA que se FIJA para el servicio (p. ej. autofirmado de la VM de Azure):
        # con él NO se aceptan otras CA; sin él, la verificación habitual del sistema. Ambos opcionales: sin ellos el comportamiento es el de siempre.
        self._token = None
        if token_file is not None:
            tp = Path(token_file)
            if tp.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO): raise StoreError("el archivo con el token del testigo debe tener permisos 0600")
            self._token = tp.read_text().strip()
            if not self._token: raise StoreError("token del testigo vacío")
        from app.failover.tlsctx import verified_ssl_context
        ctx = ssl.create_default_context(cafile=str(ca_file)) if ca_file is not None else verified_ssl_context()
        p = Path(url_file)
        if p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO): raise StoreError("el archivo con la URL del testigo debe tener permisos 0600")
        u = p.read_text().strip(); pu = urllib.parse.urlparse(u); local = pu.hostname in ("127.0.0.1", "localhost", "::1")
        if pu.scheme != "https" and not (allow_http_localhost and pu.scheme == "http" and local): raise StoreError("la URL del testigo debe ser HTTPS")
        if not pu.hostname or pu.username or pu.password or pu.query or pu.fragment: raise StoreError("URL del testigo inválida")
        self._u, self.timeout = u, timeout
        class _NR(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k): return None
        self._op = urllib.request.build_opener(_NR, urllib.request.HTTPSHandler(context=ctx))

    def _auth(self) -> dict:
        return {"Authorization": "Bearer " + self._token} if self._token else {}

    def attest(self, nonce: str) -> dict:
        import http.client
        import urllib.error
        import urllib.parse
        try:
            with self._op.open(urllib.request.Request(self._u + "?nonce=" + urllib.parse.quote(nonce, safe=""), headers=self._auth()), timeout=self.timeout) as r:
                return json.loads(r.read(65536))
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
            raise StoreUnavailable("testigo inaccesible o respuesta ilegible")

    def report(self, reporter: str, payload: dict, sig: str) -> dict:
        """POST <url> (misma URL base, sufijo /report) con el informe FIRMADO por el informante. Devuelve el recibo del testigo."""
        import http.client
        import urllib.error
        import urllib.request
        data = json.dumps({"reporter": reporter, "payload": payload, "sig": sig}).encode()
        try:
            req = urllib.request.Request(self._u.rsplit("/", 1)[0] + "/report", data=data, method="POST", headers={"Content-Type": "application/json", **self._auth()})
            with self._op.open(req, timeout=self.timeout) as r: return json.loads(r.read(65536))
        except urllib.error.HTTPError as e:
            try: return json.loads(e.read(65536))
            except Exception: raise StoreUnavailable("el testigo rechazó el informe")
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
            raise StoreUnavailable("testigo inaccesible al informar")


class EcdsaP256Signer:
    """Firmante ECDSA P-256/SHA-256 LOCAL (equivalente funcional de una clave de Cloud KMS con nivel HSM: Ed25519 solo existe en KMS con nivel SOFTWARE). La privada nunca sale de este objeto (`sign` cuenta las llamadas)."""
    def __init__(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        self._k = ec.generate_private_key(ec.SECP256R1()); self.calls = 0
    def public_der(self) -> bytes:
        from cryptography.hazmat.primitives import serialization
        return self._k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    def sign(self, holder: str, data: bytes) -> str:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        self.calls += 1; return self._k.sign(data, ec.ECDSA(hashes.SHA256())).hex()


class EcdsaP256Verifier:
    """Verificador de la firma del testigo con su clave PÚBLICA anclada (DER). `verify("witness", datos, firma_hex)`."""
    def __init__(self, public_der: bytes):
        from cryptography.hazmat.primitives import serialization
        self._p = serialization.load_der_public_key(public_der)
    def verify(self, signer: str, data: bytes, sig: str) -> bool:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        if signer != "witness": return False
        try: self._p.verify(bytes.fromhex(sig), data, ec.ECDSA(hashes.SHA256())); return True
        except (InvalidSignature, ValueError, TypeError): return False


class GcpKmsSigner:
    """Firmante con Cloud KMS (SIN validar contra Google Cloud): `asymmetric_sign` con una CryptoKeyVersion EC_SIGN_P256_SHA256 (HSM). La cuenta de servicio del testigo solo tiene roles/cloudkms.signerVerifier sobre ESA clave;
    no puede exportar ni administrar la clave. Requiere google-cloud-kms."""
    def __init__(self, key_version_name: str, client=None):
        from google.cloud import kms  # noqa: PLC0415
        self._kms, self._name, self._c = kms, key_version_name, client or kms.KeyManagementServiceClient()
    def sign(self, holder: str, data: bytes) -> str:
        import hashlib as h
        r = self._c.asymmetric_sign(request={"name": self._name, "digest": {"sha256": h.sha256(data).digest()}}); return r.signature.hex()


class LocalEcdsaFileSigner(EcdsaP256Signer):
    """ECDSA P-256 con la clave en un archivo 0600 (se crea si no existe). SOLO para el contenedor/desarrollo local; en producción la clave está en Cloud KMS (HSM) y no existe como archivo."""
    def __init__(self, path):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        self.calls = 0; p = Path(path)
        if p.exists():
            self._k = serialization.load_pem_private_key(p.read_bytes(), password=None)
        else:
            self._k = ec.generate_private_key(ec.SECP256R1()); fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f: f.write(self._k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


class QuorumReporter:
    """Informa a TODOS los testigos y exige recibos de al menos k: si no se alcanza, lanza StoreUnavailable (la promoción NO se completa). `clients`: objetos con report(reporter, payload, sig) -> recibo/tupla."""
    def __init__(self, clients, k: int): self.clients, self.k = list(clients), k
    def __call__(self, reporter: str, payload: dict, sig: str) -> list:
        got, errs = [], []
        for c in self.clients:
            try:
                r = c.report(reporter, payload, sig); ok = r.get("ok") if isinstance(r, dict) else (r[0] if isinstance(r, tuple) else False)
                (got if ok else errs).append(r)
            except Exception as e: errs.append(e)
        if len(got) < self.k: raise StoreUnavailable(f"quórum de testigos NO alcanzado al informar ({len(got)}/{self.k}): la promoción no se completa")
        return got
