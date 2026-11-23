"""OCI y Azure: se alimentan de lo que YA existe y es real — la instantánea del recolector T4 (sondas TLS verificadas desde Azure), el registro de evidencias del centro de operaciones y el autodiagnóstico
de Azure —. No hay SDK de OCI cableado en NexoOps: el estado de OCI es «alcanzabilidad/espera» según el recolector (pendiente: consulta directa con el SDK de OCI de solo lectura)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import envelope

SRC = "Recolector T4 (sondas desde Azure)"
STALE_S = 600
STATES = {"OK", "ADVERTENCIA", "ERROR", "No verificado"}
ORIGINS = {"cloud_verificado", "local", "sin_datos"}


def operational_state(state: str, detail: str = "") -> str:
    """Taxonomía estable para la UI sin reinterpretar una sonda como éxito."""
    if state == "OK":
        return "operativo"
    if state == "ERROR":
        return "fuera_de_servicio"
    if state == "ADVERTENCIA":
        return "en_espera" if "en espera" in detail.lower() else "degradado"
    return "no_verificado"


def _clouds(value) -> dict:
    out = {}
    for name in ("aws", "oci", "azure"):
        row = value.get(name) if isinstance(value, dict) else None
        if not isinstance(row, dict):
            continue
        state = str(row.get("estado", "No verificado"))
        detail = str(row.get("detalle", ""))[:500]
        if state not in STATES:
            state, detail = "No verificado", "estado del recolector no reconocido"
        origin = str(row.get("origen", "sin_datos"))
        if origin not in ORIGINS:
            origin = "sin_datos"
        out[name] = {"estado": state, "estado_operativo": operational_state(state, detail), "origen": origin, "detalle": detail}
    return out


def snapshot(state_dir, now=None):
    now = now or datetime.now(timezone.utc)
    p = Path(state_dir) / "status" / "cloud-status.json"
    try:
        d = json.loads(p.read_text()); obs = datetime.strptime(d["observed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (OSError, ValueError, KeyError, TypeError):
        return envelope(SRC, "unavailable", detail="sin instantánea legible del recolector", now=now)
    age = (now - obs).total_seconds()
    if age > STALE_S:
        env = envelope(SRC, "unavailable", detail=f"instantánea obsoleta ({int(age // 60)} min)", now=now); env["observed_at"] = d["observed_at"]; return env
    env = envelope(SRC, "ok", {"clouds": _clouds(d.get("clouds", {}))}, now=now); env["observed_at"] = d["observed_at"]; env["age_s"] = int(age)
    return env


def history(state_dir, n=60):
    p = Path(state_dir) / "status" / "probe-history.jsonl"
    try:
        lines = p.read_text().splitlines()[-n:]
        return [json.loads(l) for l in lines if l.strip()]
    except (OSError, ValueError):
        return []
