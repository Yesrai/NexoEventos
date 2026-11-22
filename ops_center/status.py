"""Estado de solo lectura para el panel. Reutiliza las secciones de `app.ops` (respaldo y failover) y añade el estado de las tres nubes a partir de una
instantánea local (`status/cloud-status.json`) que escribirá el recolector (sondas desde Azure, T4). Sin instantánea reciente ⇒ «No verificado»; nunca «OK» por defecto."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

NO_VERIFICADO = "No verificado"
STALE_S = 600


def _scrub(v):
    try:
        from app.ops import scrub
        return scrub(v)
    except Exception:  # noqa: BLE001
        return str(v)[:160] if isinstance(v, str) else v


def _with_env(settings, fn):
    saved = {k: os.environ.get(k) for k in ("OPS_BACKUP_STATE_DIR", "OPS_FAILOVER_DIR")}
    try:
        for k, v in (("OPS_BACKUP_STATE_DIR", settings.backup_state_dir), ("OPS_FAILOVER_DIR", settings.failover_dir)):
            if v: os.environ[k] = str(v)
            else: os.environ.pop(k, None)
        return fn()
    finally:
        for k, v in saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


def cloud_status(settings, now=None):
    now = now or datetime.now(timezone.utc)
    base = {n: {"estado": NO_VERIFICADO, "origen": "sin_datos", "detalle": "sin instantánea reciente del recolector"} for n in ("aws", "oci", "azure")}
    p = Path(settings.state_dir) / "status" / "cloud-status.json"
    try:
        d = json.loads(p.read_text()); obs = datetime.strptime(d["observed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (OSError, ValueError, KeyError, TypeError):
        return {"observado": None, "nubes": base, "nota": "no hay instantánea legible; el recolector (T4) aún no está desplegado"}
    if (now - obs).total_seconds() > STALE_S:
        return {"observado": d["observed_at"], "nubes": base, "nota": f"instantánea de hace más de {STALE_S // 60} min: se considera no verificada"}
    nubes = dict(base)
    for n, v in (d.get("clouds") or {}).items():
        if n in nubes and isinstance(v, dict):
            est = v.get("estado") if v.get("estado") in ("OK", "ADVERTENCIA", "ERROR") else NO_VERIFICADO
            nubes[n] = {"estado": est, "origen": v.get("origen") if v.get("origen") in ("cloud_verificado", "simulado", "local") else "sin_datos", "detalle": _scrub(str(v.get("detalle", ""))[:160])}
    return {"observado": d["observed_at"], "nubes": nubes, "nota": "datos de la instantánea del recolector"}


def overview(settings, now=None):
    try:
        from app import ops as _ops
        resp = _with_env(settings, _ops.backup_section); fo = _with_env(settings, _ops.failover_section)
    except Exception as exc:  # noqa: BLE001
        resp = fo = {"estado": NO_VERIFICADO, "origen": "sin_datos", "detalle": f"no evaluable ({type(exc).__name__})"}
    return {"generado": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"), "solo_lectura_para_ejecucion": True,
            "independencia": {"depende_de_aws": False, "depende_de_la_base_de_la_aplicacion": False, "fuente": "archivos locales del centro de operaciones"},
            "nubes": cloud_status(settings, now), "respaldo": resp, "failover": fo}
