"""Sonda rápida (T5): GET /livez cada 5–10 s con marca UTC en milisegundos, para capturar incidentes de MENOS de 30 s que el recolector de 60 s no ve (T5, 1.er intento: 22 s de 502 sin rastro).
Solo GET; TLS verificado (CA del sistema/certificado fijado; `verify_as` valida contra el dominio del certificado); sin credenciales; añade una línea JSON por muestra a un archivo 0600 de solo adición.
Pensada para correr SOLO durante una ventana de prueba (unidad ops-fastprobe.service, que se detiene al cerrar). Las muestras se programan por reloj (sin deriva acumulada) y un fallo de la sonda se registra como muestra fallida, nunca se omite."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import collector as C


def utc_ms(t: float | None = None) -> str:
    d = datetime.fromtimestamp(time.time() if t is None else t, timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def sample(base: str, path: str, *, cafile=None, verify_as=None, timeout=3.0, fetch=C.probe_http, burst: int = 1) -> dict:
    """Una muestra = `burst` solicitudes SIMULTÁNEAS (conexión nueva cada una). Con N destinos balanceados un destino muerto recibe 1/N de las solicitudes: una ráfaga de ≈ N hace que cada muestra tenga ≈ 63 % de
    probabilidad de tocarlo (con 1 sola solicitud, solo 1/N). El código de la muestra es 200 solo si TODAS las solicitudes de la ráfaga dieron 200; `fallos` cuenta las que fallaron."""
    t = time.time(); kw = {"verify_as": verify_as} if verify_as else {}
    res = [None] * burst
    def one(i):
        res[i] = fetch(base, path, cafile=cafile, timeout=timeout, **kw)
    if burst == 1:
        one(0)
    else:
        th = [threading.Thread(target=one, args=(i,)) for i in range(burst)]
        [x.start() for x in th]; [x.join() for x in th]
    bad = [r for r in res if r["code"] != 200]
    out = {"t": utc_ms(t), "code": 200 if not bad else bad[0]["code"], "ms": max(r["ms"] for r in res)}
    if burst > 1:
        out.update({"burst": burst, "fallos": len(bad), "codes": sorted(r["code"] for r in res)})
    if bad and bad[0].get("error"):
        out["error"] = bad[0]["error"]
    return out


def run(out: Path, base: str, *, path="/livez", cafile=None, verify_as=None, interval=5.0, timeout=3.0, duration=None, fetch=C.probe_http, sleep=time.sleep, clock=time.time, burst=1):
    if not 1 <= interval <= 10:
        raise ValueError("el intervalo debe estar entre 1 y 10 s")
    if timeout >= interval:
        raise ValueError("el timeout debe ser menor que el intervalo")
    if not 1 <= burst <= 10:
        raise ValueError("la ráfaga debe estar entre 1 y 10 solicitudes")
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    t0 = clock(); k = 0; n = 0
    with os.fdopen(fd, "a") as f:
        while duration is None or clock() - t0 < duration:
            s = sample(base, path, cafile=cafile, verify_as=verify_as, timeout=timeout, fetch=fetch, burst=burst)
            f.write(json.dumps(s, separators=(",", ":")) + "\n"); f.flush(); n += 1; k += 1
            wait = t0 + k * interval - clock()
            if wait > 0:
                sleep(wait)
            elif wait < -interval:          # nos atrasamos más de un intervalo: se re-sincroniza (sin ráfagas de recuperación)
                k = int((clock() - t0) / interval) + 1
    return n


def from_targets(targets_file, cloud="aws"):
    spec = C.load_targets(targets_file).get(cloud) or {}
    if not spec.get("base"):
        raise ValueError(f"el destino «{cloud}» no tiene base")
    return spec["base"], spec.get("verify_as"), spec.get("cafile")
