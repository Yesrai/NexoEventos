"""Barreras de seguridad: cada una devuelve {id, ok, detalle}. Todas deben pasar para que una solicitud sea VALIDADA (barreras de solicitud) y,
además, para considerar LISTA una ejecución (barreras de ejecución). Fallan cerradas: ausencia de dato = no pasa. Esta capa NO ejecuta nada.
`REAL_EXECUTION_WIRED` es una constante deliberada: aunque todas pasen, el centro NO tiene cableado ningún adaptador real; cablearlo exige un cambio de código revisado."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .settings import FAILOVER_PHRASE

REAL_EXECUTION_WIRED = False
_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "backend", _ROOT / "scripts" / "multicloud" / "failover"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PROD_DOMAINS = {"nexoeventos-demo"}
EVIDENCE_MAX_AGE_H = {"T1": 72, "T2": 72, "T3": 24, "T4": 24}
EVIDENCE_NAMES = {"T1": "lease real en OCI (If-Match, 20 rondas)", "T2": "cambio de DNS de pruebas con rollback", "T3": "VM de OCI con respaldo restaurado y entrada pública", "T4": "sondas en vivo desde Azure a V2 y OCI"}


def _b(id_, ok, detalle):
    return {"id": id_, "ok": bool(ok), "detalle": detalle}


def _t(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def read_evidence(settings, stage, now):
    p = Path(settings.evidence_dir) / f"{stage}.json"
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return None, "sin registro de evidencia"
    at = _t(d.get("at"))
    if d.get("etapa") != stage or d.get("resultado") != "PASS" or not at or len(str(d.get("report_sha256", ""))) != 64:
        return None, "registro incompleto o con resultado distinto de PASS"
    if now - at > timedelta(hours=EVIDENCE_MAX_AGE_H[stage]):
        return None, f"evidencia de hace más de {EVIDENCE_MAX_AGE_H[stage]} h"
    return d, "PASS registrado " + d["at"]


def _backup_ok(settings):
    try:
        from app import ops as _ops
        old = os.environ.get("OPS_BACKUP_STATE_DIR")
        if settings.backup_state_dir:
            os.environ["OPS_BACKUP_STATE_DIR"] = str(settings.backup_state_dir)
        try:
            sec = _ops.backup_section()
        finally:
            if old is None: os.environ.pop("OPS_BACKUP_STATE_DIR", None)
            else: os.environ["OPS_BACKUP_STATE_DIR"] = old
        return sec.get("estado") == "OK", f"{sec.get('estado')}: {sec.get('detalle')}"
    except Exception as exc:  # noqa: BLE001
        return False, f"no evaluable ({type(exc).__name__})"


def _config_ok(settings):
    if not settings.failover_config:
        return False, "OPS_CENTER_FAILOVER_CONFIG no definido"
    try:
        import failover_config as FC
        v = FC.validate(FC.load(settings.failover_config))
        cfg = json.loads(Path(settings.failover_config).read_text())
        doms = set(((cfg.get("dns") or {}).get("allowed_domains")) or [])
        if doms & PROD_DOMAINS:
            return False, "la configuración permite el dominio de producción; las pruebas usan solo un dominio de PRUEBAS"
        return bool(v["ok"]), "configuración válida" if v["ok"] else f"{len(v['errors'])} errores de validación (p. ej. {str(v['errors'][0])[:120]})"
    except Exception as exc:  # noqa: BLE001
        return False, f"no se pudo validar ({type(exc).__name__})"


def _read_authorization(settings, now):
    p = Path(settings.state_dir) / "autorizacion-T6.json"
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return "archivo ausente"
    exp = _t(d.get("expires_at"))
    if d.get("frase") != FAILOVER_PHRASE:
        return "frase distinta"
    if not exp or now >= exp or exp - now > timedelta(hours=6):
        return "vigencia ausente, vencida o mayor de 6 h"
    return True


def barrier_list(settings, audit, store=None, tipo="failover_aws_a_oci", now=None, execution=False):
    now = now or datetime.now(timezone.utc)
    chain = audit.verify()
    out = [_b("B01_kill_switch", not settings.kill_switch.exists(), "interruptor de emergencia " + ("ACTIVO" if settings.kill_switch.exists() else "apagado")),
           _b("B02_auditoria_integra", chain["ok"], "cadena de auditoría " + ("íntegra" if chain["ok"] else "ROTA"))]
    dl = _t(settings.deadline)
    out.append(_b("B03_plazo_academy", bool(dl) and now < dl - timedelta(hours=settings.deadline_margin_h),
                  f"vencimiento reportado {settings.deadline} (margen {settings.deadline_margin_h:g} h); confirmar la fecha real en la consola" if dl else "fecha de vencimiento no válida"))
    state = None
    if settings.failover_dir:
        try:
            state = json.loads((Path(settings.failover_dir) / "ledger.json").read_text()).get("state", "NONE")
        except (OSError, ValueError):
            state = None
    if tipo == "failback_manual":
        out.append(_b("B04_registro_de_promocion", state == "PROMOTED", f"registro de promoción: {state or 'ilegible o ausente'} (el failback exige PROMOTED)"))
    else:
        out.append(_b("B04_registro_de_promocion", state == "NONE", f"registro de promoción: {state or 'ilegible o ausente'} (se exige NONE: nada pendiente de revisión humana)"))
        out.append(_b("B05_respaldo_dentro_del_RPO", *_backup_ok(settings)))
    if tipo == "failover_aws_a_oci":
        for st, name in EVIDENCE_NAMES.items():
            d, det = read_evidence(settings, st, now)
            out.append(_b(f"B06_{st}", d is not None, f"{st} · {name}: {det}"))
        out.append(_b("B07_configuracion_failover", *_config_ok(settings)))
    if execution:
        out.append(_b("B08_variable_de_ejecucion", settings.env.get("NEXO_ALLOW_FAILOVER_EXECUTE") == "YES", "NEXO_ALLOW_FAILOVER_EXECUTE=YES en el entorno del ejecutor (no en este servicio)"))
        auth = _read_authorization(settings, now)
        out.append(_b("B09_autorizacion_humana_especifica", auth is True, "archivo de autorización de la propietaria con frase exacta y vigencia" if auth is True else f"ausente o inválida ({auth})"))
        appr = store.approved_valid(tipo) if store else None
        out.append(_b("B10_solicitud_aprobada_vigente", appr is not None, f"solicitud {appr['id']} aprobada por {appr['decision']['by']}" if appr else "no hay solicitud aprobada y vigente de este tipo"))
        out.append(_b("B11_adaptadores_reales_cableados", REAL_EXECUTION_WIRED, "REAL_EXECUTION_WIRED=False: el centro no ejecuta; la ejecución real exige un cambio de código revisado"))
    return out


def summarize(barriers):
    return {"ok": all(b["ok"] for b in barriers), "barriers": barriers}
