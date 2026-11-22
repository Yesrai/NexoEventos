"""Panel de operación (SOLO LECTURA): estado de servicios, último respaldo y frescura/RPO, lease, compuerta de escritura y failover.

Principios: (1) cada dato dice su ORIGEN (local, simulado, cloud_verificado, sin_datos) y cuándo se actualizó; (2) lo que no tiene evidencia real es «No verificado», nunca «OK» por defecto;
(3) solo se exponen campos en LISTA BLANCA y se depuran URLs, IPs y rutas (nada de PAR, tokens, claves ni rutas del servidor); (4) solo lectura: ningún endpoint escribe ni ejecuta failover;
(5) acceso: rol `organizer` (el rol más alto que existe hoy; NO hay rol de administrador). OPS_ALLOWED_EMAILS (lista separada por comas) es OBLIGATORIA: solo esos correos entran y, si falta o no tiene ningún correo válido, se deniega a todos; OPS_PANEL_ENABLED=0 lo apaga.
Fuentes locales (variables de entorno, rutas solo en el servidor): OPS_BACKUP_STATE_DIR (cycles.jsonl de scripts/multicloud/backup_cycle.py), OPS_BACKUP_MAX_AGE_MIN (90 por defecto),
OPS_FAILOVER_DIR (ledger.json del registro de promoción y last-run.json del orquestador). Una lectura de estos archivos NO prueba el estado del bucket, de OCI ni de AWS.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import AuthContext, require_role
from app.database import get_session

router = APIRouter(prefix="/api/ops", tags=["ops"])
NO_VERIFICADO = "No verificado"
_SECRET_LIKE = re.compile(r"https?://\S+|/p/[A-Za-z0-9_-]{6,}|\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[0-9a-fA-F:]{16,}\b|(?:/Users|/home|/etc|/var|/tmp|/opt)/\S+|ocid1\.\S+|arn:aws:\S+|AKIA[0-9A-Z]{12,}", re.I)


def scrub(value):
    """Depura cualquier cadena que parezca URL/IP/ruta/identificador de nube; recorta longitudes."""
    if isinstance(value, str):
        return _SECRET_LIKE.sub("[oculto]", value)[:160]
    if isinstance(value, dict):
        return {str(k)[:60]: scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in list(value)[:40]]
    return value


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sec(estado: str, origen: str, detalle: str, **extra) -> dict:
    return {"estado": estado, "origen": origen, "detalle": detalle, "actualizado": _now(), **scrub(extra)}


def _read_json(path: Path):
    try:
        if path.is_file() and path.stat().st_size < 1_000_000:
            return json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return None


def _parse_t(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def services_section(session: Session) -> dict:
    try:
        session.execute(text("SELECT 1")); db = {"estado": "OK", "origen": "local", "detalle": "la API alcanza PostgreSQL"}
    except Exception:  # noqa: BLE001
        db = {"estado": "ERROR", "origen": "local", "detalle": "la API no alcanza PostgreSQL"}
    items = {"api": {"estado": "OK", "origen": "local", "detalle": "este proceso responde"}, "base_de_datos": db}
    for name in ("balanceador_aws", "rds_aws", "oci_recuperacion", "azure_monitoreo"):
        items[name] = {"estado": NO_VERIFICADO, "origen": "sin_datos", "detalle": "no hay evidencia verificada desde esta API"}
    worst = "ERROR" if db["estado"] == "ERROR" else "OK"
    return _sec(worst if worst == "ERROR" else "ADVERTENCIA", "local", "solo la API y la base local están verificadas; los servicios cloud NO", servicios=items)


def backup_section() -> dict:
    d = os.getenv("OPS_BACKUP_STATE_DIR")
    max_age = float(os.getenv("OPS_BACKUP_MAX_AGE_MIN", "90") or 90)
    if not d:
        return _sec(NO_VERIFICADO, "sin_datos", "OPS_BACKUP_STATE_DIR no está configurado: no hay registro de respaldos en este servidor", max_age_min=max_age)
    p = Path(d) / "cycles.jsonl"
    try:
        recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    except (OSError, ValueError):
        return _sec(NO_VERIFICADO, "sin_datos", "no hay un registro legible de ciclos de respaldo", max_age_min=max_age)
    ok = [r for r in recs if isinstance(r, dict) and r.get("ok") and _parse_t(r.get("finished_at"))]
    failed_after = bool(recs) and isinstance(recs[-1], dict) and not recs[-1].get("ok")
    if not ok:
        return _sec("ERROR" if recs else NO_VERIFICADO, "local", "no hay ningún ciclo de respaldo correcto registrado", max_age_min=max_age, ciclos_fallidos=len([r for r in recs if not r.get("ok")]))
    last = ok[-1]; age = (datetime.now(timezone.utc) - _parse_t(last["finished_at"])).total_seconds() / 60
    rpo = "dentro" if age <= max_age else "vencido"
    estado = "OK" if rpo == "dentro" and not failed_after else ("ADVERTENCIA" if rpo == "dentro" else "ERROR")
    return _sec(estado, "local", f"último respaldo correcto hace {age:.0f} min (umbral {max_age:g} min)" + ("; el último intento falló" if failed_after else ""),
                ultimo={"nombre": Path(str(last.get("name", ""))).name, "entorno": last.get("env"), "terminado": last.get("finished_at"), "duracion_s": last.get("duration_s"), "bytes": last.get("cms_bytes")},
                edad_min=round(age, 1), max_age_min=max_age, rpo=rpo, ultimo_intento_fallo=failed_after, objeto_en_el_destino=NO_VERIFICADO)


def gate_and_lease(request: Request) -> tuple[dict, dict]:
    gate = getattr(request.app.state, "write_gate", None)
    if gate is None:
        gate_s = _sec(NO_VERIFICADO, "local", "WRITE_GATE_MODE=off (valor por defecto): la API NO está protegida por la compuerta; el failover automático no es seguro", modo="off")
        lease_s = _sec(NO_VERIFICADO, "sin_datos", "sin compuerta no hay lease que consultar en este proceso", almacen_remoto=NO_VERIFICADO)
        return gate_s, lease_s
    s = gate.status()
    dbf = s.get("db_fence") if isinstance(s.get("db_fence"), dict) else None
    # Vallado EN LA BASE (pg_fence): solo se informa lo que el proceso SABE (última sincronización con la base); no se afirma que la base esté vallada si nunca se sincronizó.
    vallado = ({"activo": True, "ultima_sincronizacion_ok": dbf.get("last_sync_ok"), "errores_de_sincronizacion": int(dbf.get("sync_errors") or 0)} if dbf else {"activo": False})
    detalle = "compuerta activa (enforce)" + ("" if s["holds_lease"] else ": SIN lease, las escrituras se rechazan") + ("; vallado en la base ACTIVO" if dbf else "; SIN vallado en la base (WRITE_GATE_DB_FENCE=off)")
    estado = "OK" if (s["holds_lease"] and (not dbf or dbf.get("last_sync_ok") is not False)) else "ADVERTENCIA"
    gate_s = _sec(estado, "local", detalle, modo="enforce", rol=s["role"], bloqueos=s["blocked"], vallado_en_base=vallado)
    lease_s = _sec("OK" if s["holds_lease"] else "ADVERTENCIA", "local", "estado local del lease de este proceso (plazo calculado con su reloj; no consulta el almacén remoto)", titular_local=bool(s["holds_lease"]),
                   epoca=s["epoch"], segundos_restantes=s["remaining_s"], perdido=bool(s["lost"]), almacen_remoto=NO_VERIFICADO)
    return gate_s, lease_s


def failover_section() -> dict:
    d = os.getenv("OPS_FAILOVER_DIR")
    if not d:
        return _sec(NO_VERIFICADO, "sin_datos", "OPS_FAILOVER_DIR no está configurado: no hay estado de failover en este servidor; el failover real AWS–OCI NO está validado")
    base = Path(d); ledger = _read_json(base / "ledger.json"); last = _read_json(base / "last-run.json")
    if ledger is None and last is None:
        return _sec(NO_VERIFICADO, "sin_datos", "no hay registro de promoción ni de ejecuciones del orquestador")
    state = (ledger or {}).get("state", "NONE")
    estado = "OK" if state == "NONE" else "ADVERTENCIA"
    if isinstance(last, dict) and last.get("outcome") == "ABORTED" and state != "NONE":
        estado = "ERROR"
    alerts = [{"severidad": str(a.get("severity"))[:12], "mensaje": scrub(str(a.get("message"))[:160])} for a in ((last or {}).get("alerts") or [])[:5] if isinstance(a, dict)] if isinstance(last, dict) else []
    if any(a["severidad"] == "critical" for a in alerts):
        estado = "ERROR"
    origen = (last or {}).get("origen") if (last or {}).get("origen") in ("local", "simulado", "cloud_verificado") else "local"
    return _sec(estado, origen, "estado del registro de promoción" + (": hay una promoción que requiere revisión humana" if state not in ("NONE",) else ": sin promoción en curso"), registro={"estado": state, "epoca": (ledger or {}).get("epoch")},
                ultima_ejecucion={"resultado": (last or {}).get("outcome"), "estado_seguro": (last or {}).get("safe_state"), "etapas": [t[0] for t in (last or {}).get("timeline", []) if isinstance(t, list) and t][:10], "alertas": alerts,
                                                                       "incidente": _incident(last.get("incident")), "vallado": _fencing(last.get("fencing"))} if last else None,
                modo=(last or {}).get("modo") if (last or {}).get("modo") in ("RECUPERACION_DESDE_RESPALDO", "STANDBY_PREPARADO", "FAILOVER_AUTOMATICO", "FAILBACK") else "RECUPERACION_DESDE_RESPALDO",
                recuperacion_aislada=_recovery_run(base), failover_real_validado=False)


def _incident(d):
    if not isinstance(d, dict):
        return None
    return {"clase": scrub(str(d.get("kind"))[:24]), "promovible": bool(d.get("promotable")), "motivos": [scrub(str(x)[:140]) for x in (d.get("reasons") or [])[:3]],
            "senales": {str(k)[:16]: (v if isinstance(v, bool) or v is None else scrub(str(v))[:24]) for k, v in list((d.get("signals") or {}).items())[:8]}}


def _fencing(d):
    if not isinstance(d, dict):
        return None
    return {"veredicto": d.get("verdict") if d.get("verdict") in ("FENCED", "CAN_WRITE", "UNKNOWN") else "UNKNOWN",
            "evidencia": [{"tipo": scrub(str(e.get("kind"))[:24]), "fuerza": e.get("strength") if e.get("strength") in ("verified", "inferred") else "inferred", "detalle": scrub(str(e.get("detail"))[:120])}
                          for e in (d.get("evidence") or [])[:6] if isinstance(e, dict)]}


def _recovery_run(base: Path):
    """`recovery-run.json` (scripts/multicloud/recovery_status.py): tiempos REALES por etapa de la última recuperación aislada/de aplicación. Solo campos de una lista blanca; no es un failover."""
    d = _read_json(base / "recovery-run.json")
    if not isinstance(d, dict):
        return None
    st = d.get("etapas") if isinstance(d.get("etapas"), dict) else {}
    return {"respaldo": scrub(str(d.get("respaldo"))[:64]), "origen": d.get("origen") if d.get("origen") in ("local", "simulado", "cloud_verificado") else "local",
            "resultado": d.get("resultado") if d.get("resultado") in ("OK", "FALLO") else "FALLO", "etapa_fallida": scrub(str(d.get("etapa_fallida") or ""))[:32] or None,
            "etapas_s": {str(k)[:24]: v for k, v in list(st.items())[:16] if isinstance(v, (int, float)) and not isinstance(v, bool)},
            "total_s": d.get("total_s") if isinstance(d.get("total_s"), (int, float)) and not isinstance(d.get("total_s"), bool) else None,
            "nota": "tiempo observado de recuperación de datos/aplicación; NO es el RTO de un failover AWS–OCI"}


def require_ops(context: AuthContext = Depends(require_role("organizer"))) -> AuthContext:
    if os.getenv("OPS_PANEL_ENABLED", "1") == "0":
        raise HTTPException(status_code=404, detail="No encontrado")
    # Lista blanca OBLIGATORIA: vacía, ausente o sin ningún correo bien formado ⇒ se deniega a todos (falla cerrada).
    allowed = {e.strip().lower() for e in os.getenv("OPS_ALLOWED_EMAILS", "").split(",") if e.strip() and "@" in e.strip()}
    if not allowed or context.user.email.lower() not in allowed:
        raise HTTPException(status_code=403, detail="Permiso insuficiente")
    return context


@router.get("/overview")
def overview(request: Request, context: AuthContext = Depends(require_ops), session: Session = Depends(get_session)) -> dict:
    gate_s, lease_s = gate_and_lease(request)
    return {"generado": _now(), "solo_lectura": True,
            "secciones": {"servicios": services_section(session), "respaldo": backup_section(), "lease": lease_s, "compuerta": gate_s, "failover": failover_section()}}
