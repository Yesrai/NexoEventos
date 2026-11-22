#!/usr/bin/env python3
"""Adaptador de LECTURA de OCI Object Storage para `restore_latest()` del orquestador (B-13 ↔ B-14 ↔ S-01). Solo biblioteca estándar (+ openssl).

Qué hace: lista los manifiestos del bucket, descarga el más reciente cuyo manifiesto, firma y objeto son válidos, lo deja en un directorio temporal 0700 y llama a
`backup_source.restore_latest()` (la misma verificación local que ya existía: SHA-256 del cifrado, descifrado con clave posiblemente protegida, SHA-256 del volcado,
restauración aislada y huella). El resultado tiene el mismo formato que el adaptador local: {fingerprint_ok, backup_age_s, backup, reason, ...}.

Dos lectores intercambiables (interfaz `list_stems()` / `get(name, max_bytes, sink, expected_size)`):
  - ParHttpReader: PAR de SOLO LECTURA (https). La URL es un secreto de acceso: se lee de un archivo 0600 (nunca en código, argumentos, registros ni pruebas) y nunca aparece
    en excepciones. Sin redirecciones, solo hosts de oraclecloud.com (salvo localhost en pruebas), límites de tamaño, reintentos limitados solo ante fallos transitorios.
  - OciCliReader: la CLI `oci` con el perfil existente (el mecanismo que ya usan run-from-mac.sh y app-recovery.sh); argumentos como lista (sin shell). Limitación: el tope de
    tamaño solo se puede comprobar al terminar de descargar.
Garantías (las prueba tests/test_oci_source.py contra un servidor HTTP falso, sin OCI real):
  - nombres de objeto estrictos (^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$, sin «..» ni «/»), el manifiesto solo puede apuntar a <nombre>.cms o <nombre>.oci.cms del MISMO nombre;
  - descarga a un directorio de cuarentena `incoming/` con O_EXCL|O_NOFOLLOW y permisos 0600: nunca se sobrescribe ni se sigue un enlace simbólico; un fallo borra el parcial;
  - tamaño y SHA-256 del objeto se comprueban contra el manifiesto ANTES de moverlo a `verified/`; solo lo de `verified/` llega a restore_latest();
  - respuestas HTTP incorrectas (403, 404, 429, 503, 3xx, cuerpos enormes, truncados) terminan en rechazo con un motivo fijo, nunca en un respaldo «medio válido»;
  - INTEGRIDAD ≠ PROCEDENCIA: un SHA-256 dentro del manifiesto solo detecta corrupción; quien pueda escribir en el bucket puede reemplazar manifiesto y objeto a la vez. Por eso la
    procedencia se prueba con una FIRMA del manifiesto (`<nombre>.manifest.json.sig`, la crea backup_cycle.py con una clave de firma dedicada) verificada contra una clave pública
    FIJADA por quien recupera. Sin clave de firmante el adaptador FALLA CERRADO («procedencia no verificable») salvo `allow_unsigned=True` (solo laboratorio, queda anotado en el resultado).
    Una firma válida tampoco prueba frescura: un respaldo firmado y viejo se rechaza por la antigüedad (RPO), que sale del `created_utc` firmado.
  - el adaptador nunca lanza por datos malos ni devuelve fingerprint_ok=True sin haber restaurado y comparado la huella.
Límites que NO se pueden probar sin OCI real: el formato exacto de la lista de un PAR (se asume {"objects":[{"name":..}], "nextStartWith":..} de la API de OCI), la caducidad
real del PAR y la cuota/latencia. Esto no es una validación contra OCI.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import backup_source as bs  # noqa: E402
from orchestrator import Adapters  # noqa: E402

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_SUFFIX = ".manifest.json"
SIG_SUFFIX = ".manifest.json.sig"
MAX_RETRY_AFTER = 30.0


class FetchError(Exception):
    def __init__(self, msg: str, transient: bool = False):
        super().__init__(msg)
        self.transient = transient


def valid_object_name(n: str) -> bool:
    return isinstance(n, str) and bool(NAME_RE.match(n)) and ".." not in n


def _parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # una redirección podría llevar la petición (y el secreto del PAR) a otro host
        return None


# ───────────────────────────── lector por PAR (HTTPS) ─────────────────────────────
class ParHttpReader:
    def __init__(self, par_url_file, prefix: str = "", timeout: int = 30, retries: int = 3, backoff: float = 2.0,
                 allowed_host_suffixes=("oraclecloud.com",), allow_http_localhost: bool = False, sleep=time.sleep,
                 max_listing_bytes: int = 4 << 20, max_pages: int = 20):
        p = Path(par_url_file)
        try:
            mode = p.stat().st_mode
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise FetchError("el archivo con la URL del PAR debe tener permisos 0600 (sin acceso de grupo/otros).")
            url = p.read_text().strip()
        except OSError:
            raise FetchError("no se pudo leer el archivo con la URL del PAR.")
        u = urllib.parse.urlparse(url)
        local = u.hostname in ("127.0.0.1", "localhost", "::1")
        if u.scheme != "https" and not (allow_http_localhost and u.scheme == "http" and local):
            raise FetchError("la URL del PAR debe ser HTTPS.")
        if not u.hostname or u.username or u.password or u.query or u.fragment:
            raise FetchError("URL del PAR inválida (sin credenciales, consulta ni fragmento).")
        if not local and not any(u.hostname == s or u.hostname.endswith("." + s) for s in allowed_host_suffixes):
            raise FetchError("el host del PAR no está en la lista permitida.")
        if prefix and not re.fullmatch(r"[A-Za-z0-9._/-]{0,100}", prefix):
            raise FetchError("prefijo inválido.")
        self._base = url if url.endswith("/") else url + "/"  # secreto: no se imprime nunca
        self.prefix, self.timeout, self.retries, self.backoff, self._sleep = prefix, timeout, retries, backoff, sleep
        self.max_listing_bytes, self.max_pages = max_listing_bytes, max_pages
        from app.failover.tlsctx import verified_ssl_context
        self._opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=verified_ssl_context()))

    def __repr__(self):
        return "ParHttpReader(<url oculta>)"

    # -- núcleo HTTP
    def _get_once(self, url: str, max_bytes: int, sink: Path | None, expected_size: int | None):
        try:
            with self._opener.open(urllib.request.Request(url, headers={"Accept": "*/*"}), timeout=self.timeout) as r:
                if r.status != 200:
                    raise FetchError(f"respuesta HTTP inesperada ({r.status}).")
                cl = r.headers.get("Content-Length")
                if cl is not None and cl.isdigit() and int(cl) > max_bytes:
                    raise FetchError("el objeto excede el tamaño máximo permitido.")
                n, chunks = 0, []
                fd = None
                if sink is not None:
                    try:
                        fd = os.open(sink, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                    except FileExistsError:
                        raise FetchError("el destino ya existe: no se sobrescribe.")
                try:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        n += len(b)
                        if n > max_bytes:
                            raise FetchError("el objeto excede el tamaño máximo permitido.")
                        if fd is not None:
                            os.write(fd, b)
                        else:
                            chunks.append(b)
                    if fd is not None:
                        os.fsync(fd)
                except BaseException:
                    if fd is not None:
                        os.close(fd); fd = None
                        sink.unlink(missing_ok=True)
                    raise
                finally:
                    if fd is not None:
                        os.close(fd)
                truncated = (cl is not None and cl.isdigit() and n < int(cl)) or (expected_size is not None and n < expected_size)
                if truncated or (expected_size is not None and n != expected_size):
                    if sink is not None:
                        sink.unlink(missing_ok=True)
                    # menos bytes de los anunciados/esperados = la conexión se cortó a mitad: transitorio (se reintenta de forma limitada); más bytes = permanente
                    raise FetchError("descarga truncada o de tamaño distinto al esperado.", transient=bool(truncated))
                return n if sink is not None else b"".join(chunks)
        except FetchError:
            raise
        except urllib.error.HTTPError as e:
            c = e.code
            if c in (408, 429) or 500 <= c <= 599:
                ra = e.headers.get("Retry-After") if e.headers else None
                raise FetchError(f"el servidor respondió HTTP {c} (transitorio).", transient=True) from (None if ra is None else _RetryAfter(ra))
            if c in (401, 403):
                raise FetchError(f"acceso denegado (HTTP {c}): PAR caducado, revocado o sin permiso.")
            if c == 404:
                raise FetchError("no existe (HTTP 404).")
            if 300 <= c <= 399:
                raise FetchError(f"redirección rechazada (HTTP {c}).")
            raise FetchError(f"error HTTP {c}.")
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException):
            raise FetchError("fallo de red o de conexión.", transient=True)

    def _get(self, url: str, max_bytes: int, sink: Path | None = None, expected_size: int | None = None):
        for attempt in range(1, self.retries + 2):
            try:
                return self._get_once(url, max_bytes, sink, expected_size)
            except FetchError as e:
                if not e.transient or attempt > self.retries:
                    raise
                wait = self.backoff * attempt
                if isinstance(e.__cause__, _RetryAfter):
                    wait = max(wait, min(e.__cause__.seconds, MAX_RETRY_AFTER))
                self._sleep(min(wait, MAX_RETRY_AFTER))
        raise FetchError("reintentos agotados.")  # inalcanzable

    # -- interfaz del lector
    def list_stems(self) -> list[str]:
        stems, start = [], None
        for _ in range(self.max_pages):
            q = {"prefix": self.prefix, "limit": "1000"}
            if start:
                q["start"] = start
            raw = self._get(self._base + "?" + urllib.parse.urlencode(q), self.max_listing_bytes)
            try:
                d = json.loads(raw)
                objs = d["objects"]
                start = d.get("nextStartWith")
            except (ValueError, KeyError, TypeError):
                raise FetchError("respuesta de listado inválida.")
            for o in objs if isinstance(objs, list) else []:
                name = o.get("name") if isinstance(o, dict) else None
                if not isinstance(name, str) or not name.startswith(self.prefix):
                    continue
                rel = name[len(self.prefix):]
                if rel.endswith(MANIFEST_SUFFIX) and valid_object_name(rel):
                    stems.append(rel[: -len(MANIFEST_SUFFIX)])
            if not start:
                return sorted(set(stems), reverse=True)
        raise FetchError("el listado tiene demasiadas páginas.")

    def get(self, name: str, max_bytes: int, sink: Path | None = None, expected_size: int | None = None):
        if not valid_object_name(name):
            raise FetchError("nombre de objeto no permitido.")
        return self._get(self._base + urllib.parse.quote(self.prefix + name), max_bytes, sink, expected_size)


class _RetryAfter(Exception):
    def __init__(self, v: str):
        try:
            self.seconds = float(v)
        except ValueError:
            self.seconds = 0.0


# ───────────────────────────── lector por la CLI de OCI (perfil existente) ─────────────────────────────
class OciCliReader:
    """Mecanismo ya usado por run-from-mac.sh/app-recovery.sh: `oci os object get/list --profile P`. Sin shell; argumentos como lista; nombres validados."""

    def __init__(self, namespace: str, bucket: str, profile: str, prefix: str = "", oci_bin: str = "oci", timeout: int = 300, retries: int = 2,
                 backoff: float = 2.0, sleep=time.sleep):
        for v in (namespace, bucket, profile):
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", v or ""):
                raise FetchError("namespace, bucket o perfil inválidos.")
        if prefix and not re.fullmatch(r"[A-Za-z0-9._/-]{0,100}", prefix):
            raise FetchError("prefijo inválido.")
        self.ns, self.bucket, self.profile, self.prefix, self.bin = namespace, bucket, profile, prefix, oci_bin
        self.timeout, self.retries, self.backoff, self._sleep = timeout, retries, backoff, sleep

    def _run(self, args):
        try:
            return subprocess.run([self.bin, "os", "object", *args, "--profile", self.profile, "-ns", self.ns, "--bucket-name", self.bucket],
                                  capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            raise FetchError("la CLI de OCI no respondió.", transient=True)

    def list_stems(self) -> list[str]:
        r = self._run(["list", "--prefix", self.prefix, "--all"])
        if r.returncode != 0:
            raise FetchError("la CLI de OCI no pudo listar el bucket.")
        try:
            names = [o["name"] for o in json.loads(r.stdout or "{}").get("data", [])]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise FetchError("listado de la CLI inválido.")
        out = []
        for name in names:
            if isinstance(name, str) and name.startswith(self.prefix):
                rel = name[len(self.prefix):]
                if rel.endswith(MANIFEST_SUFFIX) and valid_object_name(rel):
                    out.append(rel[: -len(MANIFEST_SUFFIX)])
        return sorted(set(out), reverse=True)

    def get(self, name: str, max_bytes: int, sink: Path | None = None, expected_size: int | None = None):
        if not valid_object_name(name):
            raise FetchError("nombre de objeto no permitido.")
        tmpdir = Path(tempfile.mkdtemp(prefix="oci-get-"))
        os.chmod(tmpdir, 0o700)
        dest = tmpdir / "obj"  # la CLI escribe aquí (no existe, no es un enlace); luego se mueve sin sobrescribir
        try:
            for attempt in range(1, self.retries + 2):
                dest.unlink(missing_ok=True)
                try:
                    r = self._run(["get", "--name", self.prefix + name, "--file", str(dest)])
                    ok = r.returncode == 0 and dest.is_file() and not dest.is_symlink()
                    err = None if ok else FetchError("la CLI de OCI no pudo descargar el objeto.", transient=True)
                except FetchError as e:
                    ok, err = False, e
                if ok:
                    size = dest.stat().st_size
                    if size > max_bytes:
                        raise FetchError("el objeto excede el tamaño máximo permitido.")
                    if expected_size is not None and size != expected_size:
                        raise FetchError("el tamaño recibido no coincide con el esperado.")
                    if sink is None:
                        return dest.read_bytes()
                    fd = os.open(sink, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(dest.read_bytes())
                    return size
                if attempt > self.retries:
                    raise err
                self._sleep(min(self.backoff * attempt, MAX_RETRY_AFTER))
            raise FetchError("reintentos agotados.")
        finally:
            for p in tmpdir.glob("*"):
                p.unlink(missing_ok=True)
            tmpdir.rmdir()


# ───────────────────────────── procedencia (firma del manifiesto) ─────────────────────────────
def verify_signature(pub_path, data: bytes, sig: bytes, workdir: Path) -> bool:
    """openssl dgst -sha256 -verify <clave pública fijada> sobre los bytes EXACTOS del manifiesto descargado."""
    pub = Path(pub_path)
    if "PRIVATE" in pub.read_text(errors="replace"):
        raise FetchError("la clave del firmante debe ser PÚBLICA.")
    sigfile = workdir / "sig.tmp"
    fd = os.open(sigfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(sig)
    try:
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(sigfile)], input=data, capture_output=True, timeout=30)
        return r.returncode == 0 and b"Verified OK" in r.stdout
    finally:
        sigfile.unlink(missing_ok=True)


# ───────────────────────────── selección y descarga segura ─────────────────────────────
def _validate_manifest(m, stem: str, max_object_bytes: int) -> str | None:
    """Devuelve un motivo de rechazo o None."""
    if not isinstance(m, dict):
        return "manifiesto no es un objeto JSON"
    missing = [k for k in bs.REQUIRED if k not in m]
    if missing:
        return "manifiesto incompleto"
    if m["name"] != stem:
        return "el nombre del manifiesto no coincide con el del objeto (posible sustitución)"
    obj = m["object_name"]
    if not isinstance(obj, str) or Path(obj).name not in (stem + ".cms", stem + ".oci.cms"):
        return "object_name no corresponde a este respaldo"
    if not isinstance(m["oci_cms_sha256"], str) or not HEX64.match(m["oci_cms_sha256"]) or not isinstance(m["plaintext_dump_sha256"], str) or not HEX64.match(m["plaintext_dump_sha256"]):
        return "hash inválido en el manifiesto"
    n = m["oci_cms_bytes"]
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= max_object_bytes:
        return "tamaño inválido o excesivo en el manifiesto"
    try:
        _parse_utc(m["created_utc"])
    except (ValueError, TypeError):
        return "created_utc inválido"
    return None


def fetch_latest(reader, workdir, *, now: datetime | None = None, env: str | None = None, max_candidates: int = 5, max_age_s: float | None = None,
                 signer_pub=None, allow_unsigned: bool = False, max_manifest_bytes: int = 65536, max_object_bytes: int = 8 << 30,
                 expect_cert_sha256: str | None = None) -> dict:
    """Deja en <workdir>/verified/ el respaldo admisible más reciente (manifiesto + objeto íntegros y con procedencia) y devuelve un informe. Nunca lanza por datos malos."""
    now = now or datetime.now(timezone.utc)
    work = Path(workdir)
    incoming, verified = work / "incoming", work / "verified"
    for d in (incoming, verified):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    rep = {"selected": None, "skipped": [], "provenance": None, "error": None, "provenance_mode": "signed" if signer_pub else ("UNSIGNED-LAB-ONLY" if allow_unsigned else None)}
    if not signer_pub and not allow_unsigned:
        rep["error"] = "procedencia no verificable: falta la clave pública del firmante (el hash del manifiesto prueba integridad, no origen); no se descarga nada"
        return rep
    skip = lambda stem, why: rep["skipped"].append({"stem": stem, "reason": why})
    try:
        stems = reader.list_stems()
    except FetchError as e:
        rep["error"] = f"no se pudo listar el bucket: {e}"
        return rep
    cands = []
    for stem in stems[:max_candidates]:
        try:
            mb = reader.get(stem + MANIFEST_SUFFIX, max_manifest_bytes)
            m = json.loads(mb)
        except FetchError as e:
            skip(stem, f"manifiesto no disponible: {e}"); continue
        except (ValueError, UnicodeDecodeError):
            skip(stem, "manifiesto corrupto (no es JSON)"); continue
        why = _validate_manifest(m, stem, max_object_bytes)
        if why:
            skip(stem, why); continue
        if env is not None and m.get("env") != env:
            skip(stem, f"entorno distinto ({m.get('env')})"); continue
        if expect_cert_sha256:   # identidad del certificado destinatario (C-04): un respaldo cifrado para OTRO certificado o sin esa declaración no es admisible
            got = str(m.get("recipient_cert_sha256") or "").replace(":", "").lower()
            if got != expect_cert_sha256.replace(":", "").lower():
                skip(stem, "certificado destinatario distinto del fijado" if got else "el manifiesto no declara el certificado destinatario"); continue
        created = _parse_utc(m["created_utc"])
        age = (now - created).total_seconds()
        if age < -300:
            skip(stem, "created_utc en el futuro"); continue
        if max_age_s is not None and age > max_age_s:
            skip(stem, "respaldo vencido (RPO)"); continue
        sig = None
        if signer_pub:
            try:
                sig = reader.get(stem + SIG_SUFFIX, 4096)
                if not verify_signature(signer_pub, mb, sig, incoming):
                    skip(stem, "firma del manifiesto inválida (procedencia no demostrada)"); continue
            except FetchError as e:
                skip(stem, f"firma no disponible: {e}"); continue
        cands.append((created, stem, m, mb, sig))
    cands.sort(key=lambda c: c[0], reverse=True)
    for created, stem, m, mb, sig in cands:
        obj_name = Path(m["object_name"]).name
        part = incoming / obj_name
        try:
            reader.get(obj_name, m["oci_cms_bytes"], sink=part, expected_size=m["oci_cms_bytes"])
        except FetchError as e:
            skip(stem, f"objeto no disponible: {e}"); part.unlink(missing_ok=True); continue
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != m["oci_cms_sha256"]:
            skip(stem, "el SHA-256 del objeto no coincide con el manifiesto"); part.unlink(missing_ok=True); continue
        try:  # sin sobrescritura: el destino no debe existir
            fd = os.open(verified / (stem + MANIFEST_SUFFIX), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(mb)
            os.link(part, verified / obj_name)
        except FileExistsError:
            skip(stem, "el destino verificado ya existe: no se sobrescribe"); continue
        finally:
            part.unlink(missing_ok=True)
        rep["selected"] = {"stem": stem, "created_utc": m["created_utc"], "age_s": (now - created).total_seconds()}
        rep["provenance"] = "signed" if sig is not None else "unsigned"
        return rep
    rep["error"] = "no hay ningún respaldo admisible (manifiesto, procedencia, antigüedad, tamaño y SHA-256)"
    return rep


def restore_latest_from_oci(reader, key, passin: str = "", *, now: datetime | None = None, env: str | None = None, max_age_s: float | None = None,
                            signer_pub=None, allow_unsigned: bool = False, mode: str = "local", restore_env: dict | None = None,
                            workdir_parent=None, **fetch_kw) -> dict:
    """Adaptador `restore_latest` del orquestador con lectura desde OCI. Falla CERRADO: cualquier error → fingerprint_ok=False con un motivo; nunca lanza."""
    fail = {"fingerprint_ok": False, "backup_age_s": 1e12, "backup": None, "reason": None, "skipped": [], "provenance": None}
    try:
        with tempfile.TemporaryDirectory(prefix="nexo-recovery-", dir=workdir_parent) as td:
            os.chmod(td, 0o700)
            rep = fetch_latest(reader, td, now=now, env=env, max_age_s=max_age_s, signer_pub=signer_pub, allow_unsigned=allow_unsigned, **fetch_kw)
            fail["skipped"] = rep["skipped"]
            if not rep["selected"]:
                fail["reason"] = rep["error"]
                return fail
            out = bs.restore_latest(Path(td) / "verified", key, passin, env=env, now=now, mode=mode, restore_env=restore_env)
            out["provenance"], out["provenance_mode"] = rep["provenance"], rep["provenance_mode"]
            out["fetch_skipped"] = rep["skipped"]
            if out.get("fingerprint_ok") and rep["provenance"] is None:  # defensa en profundidad
                out["fingerprint_ok"], out["reason"] = False, "procedencia no establecida"
            return out
    except Exception as e:  # noqa: BLE001 — el orquestador no debe recibir excepciones por datos malos
        fail["reason"] = f"error inesperado en la recuperación ({type(e).__name__})"
        return fail


class OciRecoveryAdapters(Adapters):
    """Adaptador del orquestador: SOLO `restore_latest` es real (lectura de OCI); todo lo demás sigue lanzando NotAuthorized (falla cerrada) hasta que existan los otros adaptadores
    reales. Componer con los demás: subclasear y sobrescribir lo que se implemente."""

    def __init__(self, reader, key, passin: str = "", **kw):
        self.reader, self.key, self.passin, self.kw = reader, key, passin, kw

    def restore_latest(self) -> dict:
        return restore_latest_from_oci(self.reader, self.key, self.passin, **self.kw)
