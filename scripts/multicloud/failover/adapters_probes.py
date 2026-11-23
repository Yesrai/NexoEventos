"""Sondas y precheck del orquestador (B-13). Solo biblioteca estándar. Sin red externa por defecto: las URL las configura quien despliega (en pruebas, servidores 127.0.0.1).

Estados EXPLÍCITOS de una sonda (el orquestador ya exige quórum y rondas consecutivas; aquí se evita que UNA falla transitoria cuente):
  True   el objetivo está sano (200 y, si se pide, el JSON cumple la condición)
  False  el objetivo falla de forma CONCLUYENTE tras `attempts` intentos separados (conexión rechazada, tiempo agotado, 5xx)
  None   DESCONOCIDO: la sonda no puede concluir (4xx distinto de 429, 429, 3xx, cuerpo ilegible, URL inválida, o el propio sondeador está aislado). El orquestador no actúa con None.
Un solo intento fallido seguido de uno correcto = True. El sondeador se «autocomprueba» con una URL de control (p. ej. un tercer sitio): si el control falla, TODAS las sondas
devuelven None (probablemente es el sondeador el que perdió la red, no el primario).
"""
from __future__ import annotations

import http.client
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import oci_source as oc  # noqa: E402


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _verified_ctx():
    """Contexto TLS verificado (copia de app.failover.tlsctx; este módulo solo usa la biblioteca estándar): almacén del sistema y, si no hay CA cargada, certifi. Nunca desactiva la verificación."""
    import ssl
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
    return ctx


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_verified_ctx()))


class TlsPolicy:
    """G9 — TLS de un extremo cuyo certificado NO coincide con el nombre de la URL (el ALB sirve el certificado del dominio de NexoEventos pero se sondea por su DNS; la VM de OCI usa un certificado efímero autofirmado).
    `verify_as`: nombre contra el que se VALIDA el certificado (SNI, validación del nombre y cabecera Host); `cafile`: certificado/CA FIJADO (solo él es de confianza para este extremo).
    La verificación NUNCA se desactiva: no existe ninguna opción para ello, y sin `cafile` se usan las CA públicas (almacén del sistema o certifi)."""
    HOST = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

    def __init__(self, verify_as: str | None = None, cafile=None, *, check_files: bool = True):
        if verify_as is not None and not self.HOST.match(str(verify_as)):
            raise ValueError("tls.verify_as inválido (un nombre de host)")
        if cafile is not None:
            cafile = Path(cafile)
            if not cafile.is_absolute():
                raise ValueError("tls.cafile: ruta absoluta")
            if check_files and not cafile.is_file():
                raise ValueError("tls.cafile: el certificado fijado no existe")
        if verify_as is None and cafile is None:
            raise ValueError("TlsPolicy vacía: no aporta nada (omítala)")
        self.verify_as, self.cafile = verify_as, cafile

    def __repr__(self):
        return "TlsPolicy(<fijada>)" if self.cafile else "TlsPolicy(verify_as)"

    @classmethod
    def from_config(cls, d, *, check_files: bool = True):
        if d is None:
            return None
        if not isinstance(d, dict) or set(d) - {"verify_as", "cafile"}:
            raise ValueError("tls: solo se admiten verify_as y cafile (la verificación no se puede desactivar)")
        return cls(d.get("verify_as"), d.get("cafile"), check_files=check_files)

    def context(self):
        import ssl
        if self.cafile is not None:
            ctx = ssl.create_default_context(cafile=str(self.cafile))
        else:
            ctx = _verified_ctx()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx


def _fetch_tls(url: str, timeout: float, max_bytes: int, tls: "TlsPolicy"):
    u = urllib.parse.urlparse(url)
    name = tls.verify_as or u.hostname
    ctx = tls.context()

    class _Conn(http.client.HTTPSConnection):
        def connect(self):
            raw = socket.create_connection((self.host, self.port), self.timeout)
            self.sock = self._context.wrap_socket(raw, server_hostname=name)
    conn = _Conn(u.hostname, u.port or 443, timeout=timeout, context=ctx)
    try:
        conn.request("GET", (u.path or "/") + ("?" + u.query if u.query else ""), headers={"Host": name, "User-Agent": "nexoeventos-failover/1"})
        r = conn.getresponse()
        return r.status, r.read(max_bytes)           # sin redirecciones: un 3xx se devuelve tal cual (la sonda lo trata como no concluyente)
    finally:
        conn.close()


def _fetch(url: str, timeout: float, max_bytes: int = 65536, tls: "TlsPolicy | None" = None):
    """Devuelve (código, cuerpo) o lanza OSError/HTTPException/TimeoutError. Sin redirecciones. Con `tls` valida el certificado contra `verify_as`/el certificado fijado (G9)."""
    if tls is not None:
        return _fetch_tls(url, timeout, max_bytes, tls)
    try:
        with _OPENER.open(urllib.request.Request(url), timeout=timeout) as r:
            return r.status, r.read(max_bytes)
    except urllib.error.HTTPError as e:
        return e.code, b""


class HttpProbe:
    def __init__(self, url: str, *, timeout: float = 3.0, attempts: int = 2, spacing_s: float = 1.0, json_ok=None, sleep=time.sleep, allow_http_localhost: bool = False, tls: "TlsPolicy | None" = None):
        u = urllib.parse.urlparse(url)
        local = u.hostname in ("127.0.0.1", "localhost", "::1")
        self.valid = bool(u.hostname) and (u.scheme == "https" or (allow_http_localhost and u.scheme == "http" and local)) and not u.username
        self.url, self.timeout, self.attempts, self.spacing_s = url, timeout, max(1, attempts), spacing_s
        self.json_ok, self._sleep, self.tls = json_ok, sleep, tls

    def __repr__(self):
        return "HttpProbe(<url>)"

    def _once(self):
        """True / False / None para UN intento."""
        try:
            code, body = _fetch(self.url, self.timeout, **({"tls": self.tls} if self.tls is not None else {}))
        except (OSError, TimeoutError, http.client.HTTPException):
            return False                                   # sin conexión / tiempo agotado: fallo del objetivo (o de la red; el control lo distingue)
        if code == 200:
            if self.json_ok is None:
                return True
            try:
                return bool(self.json_ok(json.loads(body)))
            except (ValueError, KeyError, TypeError):
                return None                                # cuerpo ilegible: no se puede concluir
        if 500 <= code <= 599:
            return False
        return None                                        # 3xx, 4xx, 429: no concluyente

    def run(self):
        if not self.valid:
            return None
        saw_none = False
        for i in range(self.attempts):
            r = self._once()
            if r is True:
                return True                                 # un acierto tras un fallo transitorio sigue siendo «sano»
            saw_none = saw_none or r is None
            if r is None:
                return None
            if i < self.attempts - 1:
                self._sleep(self.spacing_s)
        return None if saw_none else False


class ProbeSet:
    def __init__(self, probes: list, control: HttpProbe | None = None):
        if not probes:
            raise ValueError("se necesita al menos una sonda")
        self.probes, self.control = probes, control

    def probe_all(self) -> list:
        if self.control is not None and self.control.run() is not True:
            return [None] * len(self.probes)                # el sondeador está aislado: no se concluye nada sobre el primario
        return [p.run() for p in self.probes]


def gate_status(probe_url: str, timeout: float = 3.0, allow_http_localhost: bool = False, tls: "TlsPolicy | None" = None):
    """Lee /write-gate (backend/app/failover/gate.py). Devuelve 'escribe' | 'vallado' | None (inalcanzable o ilegible). Para old_can_write()."""
    p = HttpProbe(probe_url, timeout=timeout, allow_http_localhost=allow_http_localhost)
    if not p.valid:
        return None
    try:
        code, body = _fetch(probe_url, timeout, **({"tls": tls} if tls is not None else {}))
    except (OSError, TimeoutError, http.client.HTTPException):
        return None
    if code != 200:
        return None
    try:
        d = json.loads(body)
    except ValueError:
        return None
    mode = d.get("mode")
    if mode == "off":
        return "escribe"                                    # sin compuerta: el sitio acepta escrituras
    if mode == "enforce":
        return "escribe" if d.get("holds_lease") is True else ("vallado" if d.get("holds_lease") is False else None)
    return None


def peek_backup_meets_rpo(reader, *, now: datetime, max_age_s: float, signer_pub, env: str | None = None, max_candidates: int = 5) -> dict:
    """Precheck de RPO: ¿existe un respaldo cuyo manifiesto es válido, FIRMADO y no vencido? Solo lee manifiestos y firmas (no descarga el objeto ni restaura)."""
    out = {"ok": False, "reason": None, "age_s": None}
    if not signer_pub:
        out["reason"] = "sin clave del firmante: no hay procedencia"
        return out
    try:
        stems = reader.list_stems()
    except oc.FetchError as e:
        out["reason"] = f"no se pudo listar: {e}"
        return out
    import tempfile
    with tempfile.TemporaryDirectory(prefix="nexo-peek-") as td:
        for stem in stems[:max_candidates]:
            try:
                mb = reader.get(stem + oc.MANIFEST_SUFFIX, 65536)
                m = json.loads(mb)
                if oc._validate_manifest(m, stem, 8 << 30) or (env is not None and m.get("env") != env):
                    continue
                age = (now - oc._parse_utc(m["created_utc"])).total_seconds()
                if age > max_age_s or age < -300:
                    continue
                if not oc.verify_signature(signer_pub, mb, reader.get(stem + oc.SIG_SUFFIX, 4096), Path(td)):
                    continue
                out.update(ok=True, age_s=age, reason=None)
                return out
            except (oc.FetchError, ValueError, UnicodeDecodeError):
                continue
    out["reason"] = "ningún manifiesto firmado, íntegro y dentro del RPO"
    return out


def detector_from_http(*, livez_url: str, ready_url: str, control_url: str, gate_url: str | None = None, aws=None, gate_attested=None, allow_http_localhost: bool = False,
                       attempts: int = 2, spacing_s: float = 1.0, sleep=time.sleep):
    """IncidentDetector con sondas HTTP REALES (/livez, /ready, control del sondeador, /write-gate) y, opcionalmente, el estado de AWS en solo lectura (`aws` = evidence.AwsState o callable).
    Cada sonda devuelve True/False/None (None = desconocido). Las señales de las dos familias (HTTP y AWS) son independientes."""
    import detector as D
    mk = lambda u, **kw: HttpProbe(u, attempts=attempts, spacing_s=spacing_s, sleep=sleep, allow_http_localhost=allow_http_localhost, **kw)
    livez, ready, control = mk(livez_url), mk(ready_url), mk(control_url)
    gate = (lambda: gate_status(gate_url, allow_http_localhost=allow_http_localhost)) if gate_url else (lambda: None)
    read_aws = (aws.read if hasattr(aws, "read") else aws) if aws is not None else (lambda: {"ec2": None, "rds": None})
    # el control se evalúa una vez por observación; si falla, las demás señales no se usan (D.classify devuelve SONDEADOR_AISLADO)
    return D.IncidentDetector(livez=livez.run, ready=ready.run, control=control.run, gate=gate, aws=read_aws, gate_attested=gate_attested)
