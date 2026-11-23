#!/usr/bin/env python3
"""Ciclo de respaldo periódico (B-14): volcado -> cifrado CMS con el certificado PÚBLICO de recuperación -> subida sin sobrescritura a un bucket por PAR,
más un manifiesto verificable que `restore-drill.sh` / `verify-transfer.sh` aceptan tal cual.

Pensado para ejecutarse en la EC2 desde un temporizador de systemd (deploy/systemd/nexoeventos-backup.{service,timer}). Garantías que comprueba
scripts/multicloud/test_backup_cycle.py:
  - el volcado nunca toca el disco en claro (Python lo pasa por una tubería a `openssl cms -encrypt`; el único archivo es el .cms, 0600, borrado al terminar);
  - exige cabecera PGDMP (formato custom de pg_dump): un volcado vacío, truncado o de otro tipo NO se sube;
  - la URL del PAR (secreto) se lee de un archivo, se exige HTTPS y NUNCA se imprime ni se guarda en el registro;
  - nombre único por ciclo y `If-None-Match: *`: un objeto existente no se sobrescribe (412 = error permanente, sin reintento);
  - reintentos con espera solo ante fallos transitorios (red, 429/5xx); cada ciclo se anota en cycles.jsonl (sin secretos) con su entorno, intento y tiempos;
  - un bloqueo por directorio de estado impide ciclos solapados (dos volcados simultáneos);
  - configuración separada por entorno (`--config` JSON + `--env`): el registro lleva el entorno y la frescura se evalúa por entorno.
Manifiesto (`<objeto>.manifest.json`, mismos campos que prepare-oci-transfer.sh): SHA-256 y tamaño del cifrado y SHA-256 del volcado en claro, para que
la restauración sea verificable de extremo a extremo sin confiar en el nombre del archivo.
Códigos de salida: 0 ciclo correcto · 1 fallo del ciclo · 2 uso o configuración inválidos · 3 otro ciclo en curso (no se hace nada).
Este script NO crea ni modifica recursos cloud por sí mismo: solo sube objetos cuando se ejecuta con un PAR real (acción de la usuaria).
"""
from __future__ import annotations  # Amazon Linux 2023 trae `python3` = 3.9: las anotaciones `X | None` no deben evaluarse en tiempo de ejecución

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DUMP_CMD = 'pg_dump "$DATABASE_URL" -Fc --no-owner --no-acl'
PERMANENT_HTTP = {400, 401, 403, 404, 409, 412}  # no se reintentan: reintentar no cambia el resultado
CONFIG_KEYS = {"env", "cert", "par_url_file", "state_dir", "dump_cmd", "fingerprint_cmd", "sign_key_file", "prefix", "object_prefix", "cert_sha256", "retries", "backoff", "timeout", "max_age_min"}
ENV_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
MAX_BACKOFF = 300.0


class CycleError(Exception):
    pass


class Busy(Exception):
    pass


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] {msg}", file=sys.stderr)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(path: str) -> dict:
    """Perfil de un entorno (JSON). Solo rutas y parámetros: se rechaza cualquier clave desconocida o que parezca un secreto (p. ej. `par_url` en línea)."""
    try:
        cfg = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise CycleError("no se pudo leer el archivo --config (JSON inválido).")
    if not isinstance(cfg, dict):
        raise CycleError("--config debe ser un objeto JSON.")
    unknown = set(cfg) - CONFIG_KEYS
    if unknown:
        raise CycleError("claves no admitidas en --config: " + ", ".join(sorted(unknown)) + " (la URL del PAR solo puede ir en un archivo: par_url_file).")
    return cfg


def read_par_url(path: Path, allow_http_localhost: bool) -> str:
    url = path.read_text().strip()
    p = urllib.parse.urlparse(url)
    local = p.hostname in ("127.0.0.1", "localhost", "::1")
    if p.scheme != "https" and not (allow_http_localhost and p.scheme == "http" and local):
        raise CycleError("La URL del PAR debe ser HTTPS (archivo --par-url-file).")
    if not p.hostname or p.username or p.password:
        raise CycleError("URL del PAR inválida.")
    return url if url.endswith("/") else url + "/"


def dump_and_encrypt(dump_cmd: str, cert: Path, out: Path, require_pgdmp: bool = True) -> dict:
    """dump | openssl cms -encrypt -> out. El volcado en claro solo vive en la tubería: Python lo lee en bloques, calcula su SHA-256 y lo pasa a openssl.
    Devuelve sha256/bytes del .cms y sha256/bytes del volcado en claro."""
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    enc = ["openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-outform", "DER", "-out", str(out), str(cert)]
    plain_h, plain_n, magic = hashlib.sha256(), 0, b""
    with tempfile.TemporaryFile() as dump_err:  # stderr a archivo: evita bloqueos por tuberías llenas; no se imprime (podría contener datos)
        dump = subprocess.Popen(["bash", "-c", "set -o pipefail; " + dump_cmd], stdout=subprocess.PIPE, stderr=dump_err)
        ossl = subprocess.Popen(enc, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for chunk in iter(lambda: dump.stdout.read(1 << 20), b""):
                if len(magic) < 5:
                    magic = (magic + chunk)[:5]
                plain_h.update(chunk)
                plain_n += len(chunk)
                ossl.stdin.write(chunk)
        except BrokenPipeError:
            pass  # openssl murió: se informa abajo con su código
        finally:
            dump.stdout.close()
            try:
                ossl.stdin.close()
            except (BrokenPipeError, ValueError):
                pass
        ossl_err = ossl.stderr.read()
        ossl.stderr.close()
        ossl.wait()
        dump.wait()
    if dump.returncode != 0:
        raise CycleError(f"el volcado falló (código {dump.returncode}).")
    if ossl.returncode != 0:
        raise CycleError("el cifrado CMS falló: " + ossl_err.decode(errors="replace")[:200])
    if require_pgdmp and magic != b"PGDMP":
        raise CycleError("el volcado no tiene cabecera PGDMP (vacío, truncado o no es formato custom de pg_dump); no se sube.")
    size = out.stat().st_size
    if size < 64:
        raise CycleError("el objeto cifrado es sospechosamente pequeño.")
    h = hashlib.sha256()
    with open(out, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"cms_sha256": h.hexdigest(), "cms_bytes": size, "plain_sha256": plain_h.hexdigest(), "plain_bytes": plain_n}


SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def normalize_fingerprint(value: str) -> str:
    """Huella SHA-256 con o sin «:» y en cualquier caja → 64 hex en minúsculas ('' si no tiene esa forma)."""
    v = str(value or "").replace(":", "").strip().lower()
    return v if SHA256_HEX_RE.match(v) else ""


def cert_fingerprint(cert_path: str) -> str:
    """SHA-256 del certificado en DER (la misma huella que `openssl x509 -fingerprint -sha256`). Identifica el certificado por su contenido, no por el nombre del archivo."""
    r = subprocess.run(["openssl", "x509", "-in", str(cert_path), "-outform", "DER"], capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not r.stdout:
        raise CycleError("--cert no es un certificado X.509 legible.")
    return hashlib.sha256(r.stdout).hexdigest()


OBJECT_PREFIX_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*/)+$")


def put_bytes(par_url: str, name: str, data: bytes, ctype: str, sha: str, timeout: int, object_prefix: str = "") -> None:
    # `object_prefix` = prefijo del PAR cuando la URL devuelta por OCI termina en `/o/` (el prefijo lo impone el servidor sobre el nombre del objeto). Solo afecta a la URL de subida;
    # el nombre registrado en el manifiesto y en el estado local no cambia.
    req = urllib.request.Request(par_url + urllib.parse.quote(object_prefix + name), data=data, method="PUT")
    req.add_header("If-None-Match", "*")  # sin sobrescritura
    req.add_header("Content-Type", ctype)
    req.add_header("opc-meta-sha256", sha)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status not in (200, 201):
            raise CycleError(f"respuesta inesperada de la subida: {r.status}")


def upload_with_retries(a, par: str, name: str, data: bytes, ctype: str, sha: str, sleep) -> int:
    """Sube un objeto con reintentos controlados. Devuelve el nº de intentos usados."""
    last = None
    for attempt in range(1, a.retries + 2):
        try:
            put_bytes(par, name, data, ctype, sha, a.timeout, getattr(a, "object_prefix", "") or "")
            return attempt
        except urllib.error.HTTPError as e:
            if e.code in PERMANENT_HTTP:
                raise CycleError(f"la subida fue rechazada de forma permanente (HTTP {e.code}).")
            last = f"HTTP {e.code}"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last = type(e).__name__
        log(f"subida fallida de {name.rsplit('.', 1)[-1]} (intento {attempt}): {last}")
        if attempt <= a.retries:
            sleep(min(a.backoff * attempt, MAX_BACKOFF))
    raise CycleError(f"la subida falló tras {a.retries + 1} intentos ({last}).")


def run_fingerprint(cmd: str) -> dict:
    """Huella de datos (líneas clave=valor, p. ej. psql -At -f fingerprint.sql). Falla si el comando falla o no devuelve claves: una huella vacía no verifica nada."""
    r = subprocess.run(["bash", "-c", "set -o pipefail; " + cmd], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
    if r.returncode != 0:
        raise CycleError(f"el comando de huella falló (código {r.returncode}).")
    fp = dict(l.strip().split("=", 1) for l in r.stdout.splitlines() if "=" in l)
    if not fp:
        raise CycleError("el comando de huella no devolvió ninguna clave=valor.")
    return fp


def build_manifest(env: str, name: str, t0: datetime, info: dict, fp_before: dict | None = None, fp_after: dict | None = None, recipient_cert_sha256: str | None = None) -> dict:
    m = {"schema": 1, "name": name[:-4], "env": env, "created_utc": iso(t0), "source_cms_sha256": info["cms_sha256"],
         "source_cms_bytes": info["cms_bytes"], "oci_cms_sha256": info["cms_sha256"], "oci_cms_bytes": info["cms_bytes"],
         "plaintext_dump_sha256": info["plain_sha256"], "plaintext_dump_bytes": info["plain_bytes"],
         "encryption": "CMS/DER AES-256-CBC, certificado público de recuperación", "object_name": name,
         "manifest_note": "oci_cms_* = cifrado subido (compatible con verify-transfer.sh y restore-drill.sh)"}
    if recipient_cert_sha256:
        m["recipient_cert_sha256"] = recipient_cert_sha256  # huella del certificado destinatario: quien restaura sabe QUÉ clave necesita
    if fp_before is not None:
        # Con la aplicación escribiendo, la huella cambia durante el volcado: se guardan la anterior y la posterior; lo restaurado debe quedar entre ambas.
        m["fingerprint_before"], m["fingerprint_after"] = fp_before, fp_after
    return m


def sign_manifest(key_file: str, data: bytes) -> bytes:
    """Firma el manifiesto (openssl dgst -sha256 -sign) con la clave de FIRMA dedicada del escritor (RSA o EC; distinta de las claves de cifrado). La verificación la hace quien recupera
    con la clave pública fijada (oci_source.verify_signature). Esto da PROCEDENCIA frente a quien solo puede escribir en el bucket; si el escritor se compromete, también compromete la firma."""
    kp = Path(key_file)
    if not kp.is_file() or "PRIVATE" not in kp.read_text(errors="replace"):
        raise CycleError("--sign-key debe ser un archivo con una clave privada de firma.")
    if kp.stat().st_mode & 0o077:
        raise CycleError("la clave de firma debe tener permisos 0600.")
    r = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(kp)], input=data, capture_output=True, timeout=30)
    if r.returncode != 0 or not r.stdout:
        raise CycleError("no se pudo firmar el manifiesto (¿clave protegida o inválida?).")
    return r.stdout


def acquire_lock(state: Path):
    fd = os.open(state / "cycle.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise Busy()
    return fd


def run_cycle(a: argparse.Namespace, now=lambda: datetime.now(timezone.utc), sleep=time.sleep) -> dict:
    t0 = now()
    ts = t0.strftime("%Y%m%dT%H%M%SZ")
    name = f"{a.prefix}-{ts}.cms"
    mname = f"{a.prefix}-{ts}.manifest.json"
    state = Path(a.state_dir)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    par = read_par_url(Path(a.par_url_file), a.allow_http_localhost)
    cert_text = Path(a.cert).read_text()
    if "BEGIN CERTIFICATE" not in cert_text or "PRIVATE" in cert_text:
        raise CycleError("--cert debe ser un certificado público (sin clave privada).")
    tmp = state / f".{name}.part"
    fp_before = run_fingerprint(a.fingerprint_cmd) if a.fingerprint_cmd else None
    try:
        info = dump_and_encrypt(a.dump_cmd, Path(a.cert), tmp, require_pgdmp=not a.allow_non_pgdmp)
        attempts = upload_with_retries(a, par, name, tmp.read_bytes(), "application/octet-stream", info["cms_sha256"], sleep)
    finally:
        tmp.unlink(missing_ok=True)  # nunca queda el .cms local; el único respaldo es el remoto
    fp_after = run_fingerprint(a.fingerprint_cmd) if a.fingerprint_cmd else None
    manifest = build_manifest(a.env, name, t0, info, fp_before, fp_after, cert_fingerprint(a.cert))
    try:
        mdata = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()
        attempts_m = upload_with_retries(a, par, mname, mdata, "application/json", hashlib.sha256(mdata).hexdigest(), sleep)
        if getattr(a, "sign_key", None):  # la firma se sube la ÚLTIMA: un ciclo sin firma no es admisible para quien exige procedencia
            sig = sign_manifest(a.sign_key, mdata)
            upload_with_retries(a, par, mname + ".sig", sig, "application/octet-stream", hashlib.sha256(sig).hexdigest(), sleep)
    except CycleError as e:
        raise CycleError(f"el respaldo {name} se subió pero su manifiesto o su firma no: {e}")
    t1 = now()
    return {"ok": True, "env": a.env, "name": name, "manifest": mname, "started_at": iso(t0), "finished_at": iso(t1),
            "duration_s": round((t1 - t0).total_seconds(), 3), "attempts": attempts, "attempts_manifest": attempts_m,
            "cms_bytes": info["cms_bytes"], "cms_sha256": info["cms_sha256"], "plain_sha256": info["plain_sha256"]}


def append_record(state_dir: str, rec: dict) -> None:
    p = Path(state_dir) / "cycles.jsonl"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", help="perfil JSON del entorno (claves: " + ", ".join(sorted(CONFIG_KEYS)) + "); los argumentos de la línea de órdenes tienen prioridad")
    ap.add_argument("--env", help="nombre del entorno (p. ej. aws-academy, oci-recuperacion); se anota en cada registro y en el manifiesto")
    ap.add_argument("--cert", help="certificado PÚBLICO de recuperación (OCI)")
    ap.add_argument("--par-url-file", help="archivo (0600) con la URL del PAR de escritura del bucket; no se imprime")
    ap.add_argument("--state-dir")
    ap.add_argument("--dump-cmd", default=DEFAULT_DUMP_CMD)
    ap.add_argument("--fingerprint-cmd", default=None, help="comando que imprime la huella de datos (clave=valor) antes y después del volcado; la guarda en el manifiesto")
    ap.add_argument("--sign-key", dest="sign_key", default=None, help="clave privada de FIRMA (0600) con la que se firma el manifiesto; sube <manifiesto>.sig")
    ap.add_argument("--cert-sha256", default="", help="huella SHA-256 (DER) esperada del certificado destinatario; se rechaza cualquier otro certificado")
    ap.add_argument("--allow-unpinned-cert", action="store_true", help="solo pruebas/compatibilidad: no exigir --cert-sha256 (el perfil debería fijar la identidad del certificado)")
    ap.add_argument("--prefix", default="nexoeventos-rds")
    ap.add_argument("--object-prefix", default="", help="prefijo de ruta del PAR (p. ej. backups/c04-20261119/) que se antepone al nombre en la URL de subida; vacío si la URL del PAR ya lo trae")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--backoff", type=float, default=5.0)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--allow-non-pgdmp", action="store_true", help="solo pruebas: no exigir la cabecera PGDMP")
    ap.add_argument("--allow-http-localhost", action="store_true", help="solo para pruebas locales con un servidor falso")
    return ap


def parse_args(argv):
    ap = build_parser()
    pre, _ = ap.parse_known_args(argv)
    if pre.config:
        cfg = load_config(pre.config)
        ap.set_defaults(**{("sign_key" if k == "sign_key_file" else k): v for k, v in cfg.items() if k != "max_age_min"})
    a = ap.parse_args(argv)
    for opt in ("env", "cert", "par_url_file", "state_dir"):
        if not getattr(a, opt):
            raise CycleError(f"falta {opt.replace('_', '-')} (en la línea de órdenes o en --config).")
    if not ENV_RE.match(str(a.env)):
        raise CycleError("--env debe ser minúsculas, dígitos y guiones (máx. 31).")
    if a.cert_sha256:
        want = normalize_fingerprint(a.cert_sha256)
        if not want:
            raise CycleError("--cert-sha256 debe ser una huella SHA-256 (64 hex, con o sin «:»).")
        if cert_fingerprint(a.cert) != want:
            raise CycleError("el certificado indicado NO tiene la huella esperada (identidad del certificado distinta de la fijada en el perfil); no se hace el respaldo.")
        a.cert_sha256 = want
    elif not a.allow_unpinned_cert:
        raise CycleError("falta cert_sha256 en el perfil (o --cert-sha256): el certificado destinatario debe fijarse por su huella.")
    if a.object_prefix and (not OBJECT_PREFIX_RE.match(a.object_prefix) or ".." in a.object_prefix):
        raise CycleError("--object-prefix debe ser rutas simples terminadas en «/» (sin «..», «//» ni caracteres especiales).")
    if a.retries < 0 or a.retries > 10 or a.backoff < 0 or a.timeout < 1:
        raise CycleError("retries (0–10), backoff (>= 0) y timeout (>= 1) fuera de rango.")
    return a


def main(argv=None) -> int:
    try:
        a = parse_args(sys.argv[1:] if argv is None else argv)
    except CycleError as e:
        log(f"ERROR de configuración: {e}")
        return 2
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        Path(a.state_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = acquire_lock(Path(a.state_dir))
    except Busy:
        log("otro ciclo está en curso en este directorio de estado: no se hace nada.")
        return 3
    except OSError as e:
        log(f"ERROR de configuración: {type(e).__name__}")
        return 2
    try:
        rec = run_cycle(a)
    except CycleError as e:
        log(f"ERROR: {e}")
        try:
            append_record(a.state_dir, {"ok": False, "env": a.env, "finished_at": iso(datetime.now(timezone.utc)), "error": str(e)})
        except OSError:
            pass
        return 1
    except (OSError, ValueError) as e:
        log(f"ERROR de configuración: {type(e).__name__}")
        return 2
    finally:
        os.close(lock)
    append_record(a.state_dir, rec)
    log(f"ciclo correcto [{rec['env']}]: {rec['name']} ({rec['cms_bytes']} bytes, {rec['duration_s']} s, intentos {rec['attempts']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
