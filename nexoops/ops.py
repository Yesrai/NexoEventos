"""Agregación de estado para el panel (solo lectura) y vista de recuperación AWS→OCI. Reutiliza el centro de operaciones existente (`ops_center`) sin modificarlo ni escribir en su estado."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .integrations import envelope, utc
from .integrations import oci_azure as OA


def _ocs(cfg):
    from ops_center.settings import Settings
    env = dict(cfg.env_raw); env["OPS_CENTER_STATE_DIR"] = str(cfg.ops_state_dir)
    return Settings.from_env(env)


def _metric(value, source, observed_at, max_age_s=600, now=None):
    now = now or datetime.now(timezone.utc)
    fresh = False
    if observed_at:
        try:
            fresh = (now - datetime.strptime(observed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() <= max_age_s
        except ValueError:
            pass
    return {"value": value if observed_at else "No verificado", "source": source, "observed_at": observed_at, "fresh": fresh}


def _probe_code(snap_row, path):
    for s in snap_row or []:
        if s.get("path") == path:
            return s
    return None


def cloud_overview(cfg, aws, zbx, now=None):
    now = now or datetime.now(timezone.utc)
    snap = OA.snapshot(cfg.ops_state_dir, now)
    obs = snap["observed_at"]
    clouds = (snap["data"] or {}).get("clouds", {})
    hist = OA.history(cfg.ops_state_dir)
    last_probes = (hist[-1].get("sondas", {}) if hist else {}) if snap["status"] == "ok" else {}
    problems = zbx.problems()
    zp = problems["data"]["problems"] if problems["status"] == "ok" else None
    awsr = aws.summary()
    def cloud(n):
        c = clouds.get(n)
        return {"estado": c["estado"] if c else "No verificado", "estado_operativo": c["estado_operativo"] if c else "no_verificado", "detalle": c["detalle"] if c else snap["detail"], "origen": c["origen"] if c else "sin_datos", "observed_at": obs if c else None}
    aws_alarms = len(awsr["data"]["alarms_in_alarm"]) if awsr["status"] == "ok" else None
    primary = cloud("aws")
    aw_probes = last_probes.get("aws", [])
    ready = _probe_code(aw_probes, "/ready"); live = _probe_code(aw_probes, "/livez")
    ok_hist = [h for h in hist if h.get("aws")]
    avail = round(100 * sum(1 for h in ok_hist if h["aws"] == "OK") / len(ok_hist), 1) if ok_hist else None
    lat = [{"t": h["t"], "ms": max((s["ms"] for s in h.get("sondas", {}).get("aws", []) if s.get("code") == 200), default=None)} for h in hist[-40:]]
    return {"generated_at": utc(now), "collector": {"status": snap["status"], "detail": snap["detail"], "observed_at": obs},
            "service": {"estado": _metric(primary["estado"], snap["source"], obs, now=now), "nube_primaria": _metric("AWS (V2)" if primary["estado"] != "No verificado" else "No verificado", "configuración del despliegue", obs, now=now),
                        "disponibilidad": _metric(f"{avail} %" if avail is not None else None, f"historial de sondas ({len(ok_hist)} muestras)", obs, now=now),
                        "api": _metric(("200" if live and live["code"] == 200 else "sin respuesta") if live else None, "sonda /livez", obs, now=now),
                        "base_datos": _metric(("lista" if ready and ready["code"] == 200 else "no lista") if ready else None, "sonda /ready (incluye la base de datos)", obs, now=now),
                        "ultima_comprobacion": _metric(obs, snap["source"], obs, now=now)},
            "clouds": {"aws": {**cloud("aws"), "alarmas": aws_alarms}, "oci": cloud("oci"), "azure": cloud("azure")},
            "zabbix": {"status": problems["status"], "detail": problems["detail"], "activos": None if zp is None else len(zp), "altos": None if zp is None else sum(1 for p in zp if p["severity_n"] >= 4)},
            "aws_status": {"status": awsr["status"], "detail": awsr["detail"]},
            "latency": {"source": "historial de sondas del recolector (máx. ms por ciclo, AWS)", "series": lat, "observed_at": obs}}


def _read(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def recovery_view(cfg, now=None):
    now = now or datetime.now(timezone.utc)
    from ops_center import barriers as B, status as ST
    from ops_center.audit import AuditLog
    s = _ocs(cfg)
    ap = Path(cfg.ops_state_dir) / "audit.jsonl"
    audit = AuditLog(ap) if ap.exists() else type("NoAudit", (), {"verify": lambda self: {"ok": False}})()
    ov = ST.overview(s, now)
    fo, bk = ov.get("failover", {}), ov.get("respaldo", {})
    bar = B.summarize(B.barrier_list(s, audit, store=None, tipo="failover_aws_a_oci", now=now, execution=True))
    ledger = _read(Path(s.failover_dir) / "ledger.json") if s.failover_dir else None
    lease = _read(Path(s.failover_dir) / "lease.json") if s.failover_dir else None
    rr = (fo.get("recuperacion_aislada") or {}) if isinstance(fo, dict) else {}
    etapas = rr.get("etapas_s") or {}
    rto = round(sum(etapas.values()), 1) if etapas else None
    nv = "No verificado"
    reqs = []
    for p in sorted((Path(cfg.ops_state_dir) / "requests").glob("rq-*.json")) if (Path(cfg.ops_state_dir) / "requests").is_dir() else []:
        r = _read(p)
        if r:
            reqs.append({"id": r["id"], "tipo": r["tipo"], "estado": r["state"], "solicitada_por": r["requested_by"], "creada": r["created_at"], "decision": r.get("decision")})
    cs = ov["nubes"]["nubes"]
    return {"generated_at": utc(now), "source": "ops_center (lectura) · registro de failover · evidencias",
            "aws": cs["aws"], "oci": cs["oci"], "fuente_de_verdad": {"valor": nv if not ledger else f"registro de promoción: {ledger.get('state')}", "detalle": "ledger.json del orquestador de failover"},
            "lease": {"estado": nv if not lease else str(lease.get("state", nv))[:24], "detalle": "lease.json" if lease else "sin archivo de lease en este servidor"},
            "fencing": (fo.get("ultima_ejecucion") or {}).get("vallado") if isinstance(fo, dict) and fo.get("ultima_ejecucion") else {"veredicto": "UNKNOWN", "evidencia": []},
            "epoch_autorizado": (ledger or {}).get("epoch", nv), "ultima_copia_validada": {"estado": bk.get("estado", nv), "detalle": bk.get("detalle", "")},
            "rto_observado_s": rto if rto is not None else nv, "rpo_observado": {"valor": nv, "detalle": "RPO = antigüedad de la última copia validada; ver 'ultima_copia_validada'"},
            "barreras": bar, "failover_real_habilitado": False, "failback_real_habilitado": False,
            "operaciones_pendientes": [r for r in reqs if r["estado"] in ("SOLICITADA", "VALIDADA", "APROBADA")], "historial_aprobaciones": [r for r in reqs if r["decision"]][-20:],
            "nota": "El failover real AWS→OCI permanece BLOQUEADO hasta demostrar sus barreras; NexoOps no ejecuta failover ni failback."}
