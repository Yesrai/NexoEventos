"""Flujo SOLICITUD → VALIDACIÓN → APROBACIÓN de recuperaciones controladas. Este módulo SOLO registra decisiones: no ejecuta ninguna acción.
Estados: SOLICITADA → VALIDADA | RECHAZADA_VALIDACION → APROBADA | DENEGADA | EXPIRADA | CANCELADA. «APROBADA» significa «un humano distinto autorizó», no «ejecutada».
Reglas: el aprobador debe ser distinto del solicitante; la solicitud caduca (APPROVAL_WINDOW_S) y la aprobación también (GRANT_S); una sola solicitud activa por tipo;
tipos y parámetros en lista blanca; se exige justificación; todo cambio de estado se audita."""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .audit import AuditLog

TIPOS = {
    "restaurar_respaldo_en_oci": "Restaurar el respaldo en la VM de OCI (sin cambiar DNS ni habilitar escritura)",
    "failover_aws_a_oci": "Failover controlado AWS → OCI (T6): lease, habilitar standby y DNS de PRUEBAS",
    "failback_manual": "Retorno manual a AWS tras un failover (vallado del escritor de OCI primero)",
}
ACTIVOS = {"SOLICITADA", "VALIDADA", "APROBADA"}
APPROVAL_WINDOW_S = 30 * 60
GRANT_S = 60 * 60
_REASON = re.compile(r"^[\w\s.,;:()\-/áéíóúñÁÉÍÓÚÑ¿?¡!%+#=]{10,500}$")


class RecoveryError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg); self.code = code


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class RecoveryStore:
    def __init__(self, state_dir, audit: AuditLog, validator, clock=lambda: datetime.now(timezone.utc)):
        self.dir = Path(state_dir) / "requests"; self.dir.mkdir(parents=True, exist_ok=True)
        self.audit, self.validator, self.clock = audit, validator, clock

    # -------- persistencia --------
    def _path(self, rid):
        if not re.fullmatch(r"rq-[0-9a-f]{12}", rid or ""):
            raise RecoveryError("identificador inválido", 404)
        return self.dir / f"{rid}.json"

    def _save(self, r):
        fd, tmp = tempfile.mkstemp(dir=self.dir); os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(r, f, ensure_ascii=False, indent=1); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, self._path(r["id"]))

    def get(self, rid):
        p = self._path(rid)
        if not p.is_file():
            raise RecoveryError("no encontrada", 404)
        r = json.loads(p.read_text()); return self._expire(r)

    def list(self):
        return sorted((self._expire(json.loads(p.read_text())) for p in self.dir.glob("rq-*.json")), key=lambda r: r["created_at"], reverse=True)

    def _expire(self, r):
        now = self.clock()
        if r["state"] in ("SOLICITADA", "VALIDADA") and now > _parse(r["expires_at"]):
            r["state"] = "EXPIRADA"; self._save(r); self.audit.append("sistema", "expirada", id=r["id"])
        elif r["state"] == "APROBADA" and now > _parse(r["decision"]["grant_expires_at"]):
            r["state"] = "EXPIRADA"; self._save(r); self.audit.append("sistema", "aprobacion_expirada", id=r["id"])
        return r

    # -------- transiciones --------
    def create(self, actor: str, tipo: str, reason: str, idem_key: str | None = None) -> dict:
        if tipo not in TIPOS:
            raise RecoveryError("tipo de recuperación no permitido")
        if not _REASON.match(reason or ""):
            raise RecoveryError("justificación obligatoria (10–500 caracteres, sin símbolos extraños)")
        existing = self.list()
        if idem_key:
            for r in existing:
                if r.get("idem_key") == idem_key and r["requested_by"] == actor:
                    return r
        if any(r["tipo"] == tipo and r["state"] in ACTIVOS for r in existing):
            raise RecoveryError("ya existe una solicitud activa de ese tipo", 409)
        now = self.clock()
        r = {"id": "rq-" + secrets.token_hex(6), "tipo": tipo, "descripcion": TIPOS[tipo], "reason": reason.strip(), "requested_by": actor, "created_at": _ts(now),
             "expires_at": _ts(now + timedelta(seconds=APPROVAL_WINDOW_S)), "state": "SOLICITADA", "idem_key": (idem_key or "")[:64] or None, "validation": None, "decision": None}
        self._save(r); self.audit.append(actor, "solicitada", id=r["id"], tipo=tipo, reason=r["reason"])
        v = self.validator(r)
        r["validation"] = {"at": _ts(self.clock()), "ok": v["ok"], "barriers": v["barriers"]}
        r["state"] = "VALIDADA" if v["ok"] else "RECHAZADA_VALIDACION"
        self._save(r); self.audit.append("sistema", "validada" if v["ok"] else "rechazada_validacion", id=r["id"], fallidas=[b["id"] for b in v["barriers"] if not b["ok"]])
        return r

    def decide(self, rid: str, actor: str, approve: bool, comment: str = "") -> dict:
        r = self.get(rid)
        if r["state"] != "VALIDADA":
            raise RecoveryError(f"solo se decide una solicitud VALIDADA (estado actual: {r['state']})", 409)
        if actor == r["requested_by"]:
            self.audit.append(actor, "decision_rechazada_mismo_actor", id=rid)
            raise RecoveryError("quien solicita no puede aprobar su propia solicitud", 403)
        now = self.clock()
        r["decision"] = {"by": actor, "at": _ts(now), "approved": bool(approve), "comment": (comment or "")[:300], "grant_expires_at": _ts(now + timedelta(seconds=GRANT_S)) if approve else None}
        r["state"] = "APROBADA" if approve else "DENEGADA"
        self._save(r); self.audit.append(actor, "aprobada" if approve else "denegada", id=rid, comment=r["decision"]["comment"])
        return r

    def cancel(self, rid: str, actor: str, is_approver: bool) -> dict:
        r = self.get(rid)
        if r["state"] not in ACTIVOS:
            raise RecoveryError(f"no se puede cancelar en estado {r['state']}", 409)
        if actor != r["requested_by"] and not is_approver:
            raise RecoveryError("solo el solicitante o un aprobador pueden cancelar", 403)
        r["state"] = "CANCELADA"; self._save(r); self.audit.append(actor, "cancelada", id=rid)
        return r

    def approved_valid(self, tipo: str | None = None):
        """Solicitud APROBADA y vigente (para la barrera B11). No ejecuta nada."""
        for r in self.list():
            if r["state"] == "APROBADA" and (tipo is None or r["tipo"] == tipo):
                return r
        return None
