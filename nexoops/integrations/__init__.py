"""Adaptadores de SOLO LECTURA. Cada resultado lleva fuente, marca UTC y estado; sin configuración ⇒ «not_configured», nunca datos inventados."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def utc(now=None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def envelope(source: str, status: str, data=None, detail: str = "", origin: str = "cloud_verificado", now=None) -> dict:
    """status: ok | not_configured | unavailable | error. origin: cloud_verificado | local | sin_datos."""
    return {"source": source, "status": status, "observed_at": utc(now) if status == "ok" else None, "checked_at": utc(now), "origin": origin if status == "ok" else "sin_datos", "detail": detail, "data": data}


def http_json(url: str, *, method="GET", headers=None, body=None, timeout=8.0):
    pu = urllib.parse.urlparse(url)
    if pu.scheme != "https" and not (pu.scheme == "http" and pu.hostname in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("solo https (http únicamente a loopback)")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Accept": "application/json", **({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:    # noqa: S310 (esquema validado)
        return json.loads(r.read(2_000_000) or b"null")
