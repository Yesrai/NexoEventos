"""Acciones EXPLÍCITAMENTE permitidas. No hay ejecución arbitraria ni comandos desde el navegador. Cada acción: lista blanca, parámetros validados, límite de frecuencia, confirmación si procede y auditoría
con identificador de solicitud y de ejecución. Las operaciones mutantes quedan SOLO como solicitudes bloqueadas que exigen aprobación independiente (no simulada con el mismo usuario)."""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path

from .integrations import utc
from .auth import ROLE_ADMIN

BLOCKED = {
    "failover.execute": "Failover real AWS→OCI bloqueado hasta demostrar sus barreras (T6). NexoOps no lo ejecuta.",
    "failback.execute": "Failback real bloqueado: requiere vallado del escritor de OCI y aprobación independiente.",
}
CATALOG = {
    "status.refresh": {"risk": "lectura", "label": "Consultar estado multicloud"},
    "health.check": {"risk": "lectura", "label": "Ejecutar comprobación de salud (GET)"},
    "aws.asg_activities": {"risk": "lectura", "label": "Consultar actividades del ASG", "params": ["asg"]},
    "recovery.verify": {"risk": "lectura", "label": "Verificar barreras de recuperación"},
    "evidence.list": {"risk": "lectura", "label": "Consultar evidencia"},
    "service.restart.request": {"risk": "solicitud", "label": "Solicitar reinicio controlado de un servicio", "params": ["service", "reason"], "confirm": True},
    **{k: {"risk": "bloqueada", "label": v} for k, v in BLOCKED.items()},
}
SERVICES = {"nexoeventos-api", "grafana-server", "zabbix-server", "ops-center"}
RATE = {"lectura": (20, 60), "solicitud": (3, 600)}      # (máx., ventana s)


class ActionError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg); self.code = code


class Actions:
    def __init__(self, cfg, audit, deps, clock=time.time):
        self.cfg, self.audit, self.deps, self.clock = cfg, audit, deps, clock
        self.hits: dict[str, list[float]] = {}
        self.dir = Path(cfg.data_dir) / "intervention-requests"; self.dir.mkdir(parents=True, exist_ok=True)

    def catalog(self):
        return [{"name": k, **v} for k, v in CATALOG.items()]

    def _rate(self, name, risk):
        mx, win = RATE[risk]; now = self.clock()
        h = [t for t in self.hits.get(name, []) if now - t < win]
        if len(h) >= mx:
            raise ActionError("límite de frecuencia alcanzado para esta acción", 429)
        h.append(now); self.hits[name] = h

    def run(self, user: dict, name: str, params: dict | None, confirm: bool, request_id: str) -> dict:
        params = params or {}
        exec_id = "ex-" + secrets.token_hex(5)
        meta = CATALOG.get(name)
        def done(result, **ev):
            self.audit.append(user["email"], name, rol=user["role"], operacion=name, recurso=str(params.get("asg") or params.get("service") or "-"), resultado=result, request_id=request_id, execution_id=exec_id, evidencia=ev or None)
        if user.get("role") != ROLE_ADMIN:
            done("rechazada_rol")
            raise ActionError("rol no autorizado para operaciones de TI", 403)
        if not meta:
            done("rechazada_no_permitida"); raise ActionError("acción no permitida", 404)
        if meta["risk"] == "bloqueada":
            done("bloqueada"); raise ActionError(BLOCKED[name], 423)
        allowed_params = set(meta.get("params", ()))
        if set(params) - allowed_params:
            done("rechazada_parametros", campos_no_permitidos=sorted(set(params) - allowed_params))
            raise ActionError("la acción contiene parámetros no permitidos")
        try:
            self._rate(name, meta["risk"])
        except ActionError:
            done("rechazada_limite")
            raise
        if meta.get("confirm") and not confirm:
            done("rechazada_sin_confirmacion"); raise ActionError("la acción exige confirmación explícita", 400)
        try:
            out = getattr(self, "_" + name.replace(".", "_"))(params)
        except ActionError:
            done("rechazada_parametros"); raise
        except Exception:
            done("error_interno")
            raise ActionError("la acción no está disponible temporalmente", 502) from None
        done("ok" if out.get("status", "ok") in ("ok", "not_configured", "unavailable", "pendiente") else "error", estado=out.get("status"))
        return {"execution_id": exec_id, "request_id": request_id, "action": name, "executed_at": utc(), "result": out}

    # ---- lecturas ----
    def _status_refresh(self, p):
        return self.deps["cloud_overview"]()

    def _health_check(self, p):
        tf = self.cfg.env_raw.get("NEXOOPS_TARGETS_FILE")
        if not tf:
            return {"status": "not_configured", "detail": "NEXOOPS_TARGETS_FILE sin definir (mismo formato que targets.example.json del recolector)"}
        from ops_center import collector as C
        res = C.collect(self.deps["ocs"](), C.load_targets(tf))
        return {"status": "ok", "observed_at": res["observed_at"], "clouds": res["clouds"], "note": "solo GET, TLS verificado; no se escribió ninguna instantánea"}

    def _aws_asg_activities(self, p):
        name = str(p.get("asg", ""))
        allowed = self.cfg.aws_asg_names
        if not allowed:
            raise ActionError("lista blanca de ASG sin configurar", 409)
        if not re.fullmatch(r"[\w.-]{1,255}", name) or name not in allowed:
            raise ActionError("ASG no permitido")
        return self.deps["aws"].asg_activities(name)

    def _recovery_verify(self, p):
        v = self.deps["recovery_view"]()
        return {"status": "ok", "ok": v["barreras"]["ok"], "barreras": v["barreras"]["barriers"], "failover_real_habilitado": False}

    def _evidence_list(self, p):
        d = Path(self.deps["ocs"]().evidence_dir)
        items = []
        for f in sorted(d.glob("T*.json")) if d.is_dir() else []:
            try:
                j = json.loads(f.read_text()); items.append({"etapa": j.get("etapa"), "resultado": j.get("resultado"), "at": j.get("at"), "report_sha256": str(j.get("report_sha256", ""))[:16]})
            except (OSError, ValueError):
                pass
        return {"status": "ok", "evidencias": items}

    # ---- solicitud (nunca ejecuta) ----
    def _service_restart_request(self, p):
        svc, reason = str(p.get("service", "")), str(p.get("reason", "")).strip()
        if svc not in SERVICES:
            raise ActionError("servicio no permitido")
        if not 10 <= len(reason) <= 300:
            raise ActionError("justificación de 10–300 caracteres obligatoria")
        rid = "ir-" + secrets.token_hex(5)
        rec = {"id": rid, "service": svc, "reason": reason, "created_at": utc(), "state": "BLOQUEADA_REQUIERE_APROBACION_INDEPENDIENTE",
               "detail": "Hay un único usuario TI: no se simula una segunda aprobación. La solicitud queda registrada; no se ejecuta nada."}
        path = self.dir / f"{rid}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
            f.write("\n")
        return {"status": "pendiente", **rec}

    def list_requests(self):
        out = []
        for f in sorted(self.dir.glob("ir-*.json")):
            try:
                if f.is_file() and not f.is_symlink():
                    out.append(json.loads(f.read_text()))
            except (OSError, ValueError):
                continue
        return out[-50:]
