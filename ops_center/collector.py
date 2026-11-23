"""Recolector de estado (T4): sondas REALES de solo lectura desde la VM de Azure hacia AWS y OCI, más el autodiagnóstico de Azure. Escribe `status/cloud-status.json` (lo que lee el panel) y añade una línea por
ciclo a `status/probe-history.jsonl` (evidencia con marcas UTC de T5 y T6).

Garantías: solo GET; sin credenciales de ninguna nube (sondas HTTPS públicas); TLS siempre verificado (CA del sistema o certificado FIJADO por destino; nunca verify=False); un destino caído no impide sondear los demás
ni escribir la instantánea (el panel y el recolector NO dependen de AWS); sin datos ⇒ «No verificado», nunca «OK» por defecto; la instantánea se reemplaza de forma atómica (0600).
No ejecuta ni habilita ninguna acción de recuperación."""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import socket
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PATHS = ("/livez", "/ready", "/api/events")
SLOW_S = 3.0
TIMEOUT_S = 6.0
MIN_FREE_GB = 5.0
CLOUDS = ("aws", "oci", "azure")


def utc(now=None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _context(cafile: str | None) -> ssl.SSLContext:
    if cafile:
        ctx = ssl.create_default_context(cafile=cafile)          # certificado FIJADO: solo ese certificado es de confianza para este destino
    else:
        try:
            from app.failover.tlsctx import verified_ssl_context
            ctx = verified_ssl_context()
        except Exception:  # noqa: BLE001
            ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _get_verified_as(base: str, path: str, verify_as: str, cafile, timeout: float):
    """GET a `base` (p. ej. el DNS del ALB) validando el certificado contra OTRO nombre (`verify_as`, el dominio del certificado ACM): SNI, validación de nombre y cabecera Host usan `verify_as`.
    La verificación sigue siendo OBLIGATORIA (CA del sistema o certificado fijado); solo cambia el nombre contra el que se valida."""
    pu = urllib.parse.urlparse(base)
    ctx = _context(cafile)
    class _Conn(http.client.HTTPSConnection):
        def connect(self):
            raw = socket.create_connection((self.host, self.port), self.timeout)
            self.sock = self._context.wrap_socket(raw, server_hostname=verify_as)
    conn = _Conn(pu.hostname, pu.port or 443, timeout=timeout, context=ctx)
    try:
        conn.request("GET", path, headers={"Host": verify_as, "User-Agent": "nexoeventos-ops-collector/1", "Accept": "application/json"})
        r = conn.getresponse()
        return r.status, r.read(65536)
    finally:
        conn.close()


def probe_http(base: str, path: str, *, cafile: str | None = None, timeout: float = TIMEOUT_S, verify_as: str | None = None) -> dict:
    """Una sonda GET. Devuelve {path, code (0 = sin respuesta), ms, error?}. Nunca lanza."""
    url = base.rstrip("/") + path
    t0 = time.monotonic()
    pu = urllib.parse.urlparse(url)
    if pu.scheme != "https" and not (pu.scheme == "http" and pu.hostname in ("127.0.0.1", "localhost", "::1")):      # http SOLO a loopback (servicios de la propia VM detrás de Nginx)
        return {"path": path, "code": 0, "ms": 0, "error": "solo https"}
    try:
        if verify_as:
            code, body = _get_verified_as(base, path, verify_as, cafile, timeout)
            if code >= 400:
                return {"path": path, "code": code, "ms": round((time.monotonic() - t0) * 1000), "error": f"HTTP {code}"}
        else:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": "nexoeventos-ops-collector/1", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout, context=_context(cafile)) as r:     # noqa: S310 (esquema https verificado arriba)
                body = r.read(65536)
                code = r.status
        out = {"path": path, "code": code, "ms": round((time.monotonic() - t0) * 1000)}
        if path == "/api/events":
            try:
                out["eventos"] = len(json.loads(body)) if body else 0
            except ValueError:
                out["code"] = 0
                out["error"] = "respuesta no JSON"
        return out
    except urllib.error.HTTPError as e:
        return {"path": path, "code": e.code, "ms": round((time.monotonic() - t0) * 1000), "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001  (DNS, TCP, TLS, timeout)
        return {"path": path, "code": 0, "ms": round((time.monotonic() - t0) * 1000), "error": type(e).__name__}


def classify(results: list[dict], esperado: str = "activo") -> tuple[str, str]:
    """(estado, detalle). `esperado`: «activo» (producción) o «standby» (OCI en espera: que no responda es lo normal)."""
    ok = [r for r in results if r["code"] == 200]
    if not results:
        return "ERROR", "sin sondas"
    if len(ok) == len(results):
        lento = [r for r in ok if r["ms"] > SLOW_S * 1000]
        if lento:
            return "ADVERTENCIA", f"responde pero lento ({max(r['ms'] for r in lento)} ms)"
        return "OK", f"{len(ok)}/{len(results)} sondas 200 (máx {max(r['ms'] for r in ok)} ms)"
    if not ok:
        errs = sorted({r.get("error", "?") for r in results})
        if esperado == "standby":
            return "ADVERTENCIA", "en espera (sin entrada pública activa): " + ", ".join(errs)
        return "ERROR", "sin respuesta: " + ", ".join(errs)
    return "ADVERTENCIA", f"{len(ok)}/{len(results)} sondas 200; fallan: " + ", ".join(r["path"] for r in results if r["code"] != 200)


def probe_reachability(spec: dict, fetch=probe_http) -> dict:
    """Modo «alcanzabilidad» (OCI en espera, fuera de T3/T6): la aplicación NO existe, así que solo se mide si el endpoint regional de OCI responde por TLS verificado. Cualquier respuesta HTTP (aun 4xx)
    prueba alcanzabilidad y NO prueba que NexoEventos esté activo: se informa como ADVERTENCIA (en espera), nunca como OK. Sin respuesta: ERROR."""
    r = fetch(spec["base"], spec.get("path", "/"), cafile=spec.get("cafile"))
    if r["code"] > 0:
        return {"estado": "ADVERTENCIA", "origen": "cloud_verificado", "detalle": f"en espera: endpoint regional de OCI alcanzable (HTTP {r['code']}, {r['ms']} ms); NO hay aplicación activa que verificar", "sondas": [r]}
    return {"estado": "ERROR", "origen": "cloud_verificado", "detalle": f"endpoint regional de OCI inalcanzable: {r.get('error', '?')}", "sondas": [r]}


def probe_target(spec: dict, fetch=probe_http) -> dict:
    base = spec.get("base") or ""
    if not base:
        return {"estado": "No verificado", "origen": "sin_datos", "detalle": "destino sin configurar", "sondas": []}
    if spec.get("modo") == "alcanzabilidad":
        return probe_reachability(spec, fetch)
    res = [fetch(base, p, cafile=spec.get("cafile"), **({"verify_as": spec["verify_as"]} if spec.get("verify_as") else {})) for p in PATHS]
    estado, det = classify(res, spec.get("esperado", "activo"))
    return {"estado": estado, "origen": "cloud_verificado", "detalle": det, "sondas": res}


def self_check(settings, spec: dict, fetch=probe_http, free_gb=None) -> dict:
    """Autodiagnóstico de Azure: el propio centro (local), disco y testigo (opcional). Origen «local»."""
    fallos, partes = [], []
    if spec.get("self_url"):
        r = fetch(spec["self_url"], spec.get("self_path", "/ops/healthz"), cafile=spec.get("self_cafile"))
        (partes if r["code"] == 200 else fallos).append("panel")
    gb = free_gb if free_gb is not None else shutil.disk_usage(settings.state_dir if Path(settings.state_dir).exists() else ".").free / 2**30
    (partes if gb >= MIN_FREE_GB else fallos).append(f"disco {gb:.0f} GB")
    if spec.get("witness_url"):
        r = fetch(spec["witness_url"], spec.get("witness_path", "/healthz"), cafile=spec.get("witness_cafile"))
        (partes if r["code"] == 200 else fallos).append("testigo")
    if fallos:
        return {"estado": "ERROR", "origen": "local", "detalle": "fallan: " + ", ".join(fallos)}
    return {"estado": "OK", "origen": "local", "detalle": "ok: " + ", ".join(partes)}


def collect(settings, targets: dict, now=None, fetch=probe_http, free_gb=None) -> dict:
    """Un ciclo. Cada destino se sondea de forma independiente: la caída de uno nunca impide los demás."""
    clouds, detail = {}, {}
    for n in ("aws", "oci"):
        try:
            r = probe_target(targets.get(n) or {}, fetch)
        except Exception as e:  # noqa: BLE001
            r = {"estado": "ERROR", "origen": "cloud_verificado", "detalle": f"fallo del recolector: {type(e).__name__}", "sondas": []}
        clouds[n] = {k: r[k] for k in ("estado", "origen", "detalle")}
        detail[n] = r.get("sondas", [])
    clouds["azure"] = self_check(settings, targets.get("azure") or {}, fetch, free_gb)
    return {"observed_at": utc(now), "clouds": clouds, "sondas": detail}


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    os.chmod(tmp, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_snapshot(settings, snap: dict):
    d = Path(settings.state_dir) / "status"
    _atomic_write(d / "cloud-status.json", json.dumps({"observed_at": snap["observed_at"], "clouds": snap["clouds"]}, ensure_ascii=False, indent=1) + "\n")
    line = json.dumps({"t": snap["observed_at"], **{n: snap["clouds"][n]["estado"] for n in CLOUDS}, "sondas": snap["sondas"]}, ensure_ascii=False, separators=(",", ":"))
    fd = os.open(d / "probe-history.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(line + "\n")


def load_targets(path) -> dict:
    t = json.loads(Path(path).read_text())
    for n, spec in t.items():
        if n not in CLOUDS or not isinstance(spec, dict):
            raise ValueError(f"destino desconocido: {n}")
        if spec.get("base") and not str(spec["base"]).startswith("https://"):
            raise ValueError(f"{n}: la base debe ser https")
        for k in ("self_url", "witness_url"):
            u = urllib.parse.urlparse(str(spec.get(k, "https://x")))
            if u.scheme != "https" and not (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")):
                raise ValueError(f"{n}: {k} debe ser https (http solo a 127.0.0.1)")
        if spec.get("verify_as") and not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", str(spec["verify_as"])):
            raise ValueError(f"{n}: «verify_as» inválido")
        if spec.get("modo", "aplicacion") not in ("aplicacion", "alcanzabilidad"):
            raise ValueError(f"{n}: «modo» inválido")
        if spec.get("esperado", "activo") not in ("activo", "standby"):
            raise ValueError(f"{n}: «esperado» inválido")
    return t


def run(settings, targets_file, once=True, interval=60, fetch=probe_http):
    while True:
        snap = collect(settings, load_targets(targets_file), fetch=fetch)
        write_snapshot(settings, snap)
        if once:
            return snap
        time.sleep(interval)
