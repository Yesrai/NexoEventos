"""GUARDIA DE REINICIO del primario tras la promoción de OCI. Corre en el lado de OCI (orquestador/servicio) mientras OCI sea el escritor: cada `step()` mira el estado de la RDS del primario por el plano de control
y, si dejó de estar `stopped`/`stopping` (se reinició sola a los 7 días o la encendió alguien), la VALLA otra vez con la mejor herramienta disponible:
  1) base alcanzable → `hard_fence` (cerrojo persistente + sesiones terminadas + prueba): cierra el hueco que no se pudo cerrar mientras la RDS estaba detenida;
  2) si no se alcanza y `allow_stop_rds` → ordena `stop-db-instance` otra vez.
Además informa si el sello sigue vigente. Nada aquí concede autoridad a nadie: el failback es manual (cerrojo + sello)."""
from __future__ import annotations

import time

RUNNING_STATES = {"starting", "available", "backing-up", "modifying", "rebooting", "configuring-enhanced-monitoring", "storage-optimization", "maintenance", "upgrading", "resetting-master-credentials"}


class RestartGuard:
    def __init__(self, *, aws_read, hard_fence=None, proof_ok=None, stop_rds=None, allow_stop_rds=False, seal_check=None, alert=lambda sev, msg: None, now=time.time, ratchet=None):
        self.aws_read, self.hard_fence, self.stop_rds, self.allow_stop_rds, self.seal_check, self.alert, self.now, self.ratchet = aws_read, hard_fence, stop_rds, allow_stop_rds, seal_check, alert, now, ratchet
        self.proof_ok = proof_ok or (lambda p: bool(p) and p.get("latched") is True and p.get("authority_revoked") is True and p.get("app_sessions_left") == 0 and p.get("prepared_xacts") == 0)
        self.latched = False; self.events: list[dict] = []

    def step(self) -> dict:
        out = {"t": self.now(), "rds": None, "acciones": [], "latched": self.latched}
        try:
            rds = (self.aws_read() or {}).get("rds")
        except Exception:  # noqa: BLE001
            rds = None
        out["rds"] = rds
        if self.seal_check is not None:
            try:
                ok, why = self.seal_check(None); out["sello_vigente"] = (not ok)
                if ok: self.alert("critical", f"el SELLO de promoción NO está vigente ({why}): AWS podría recuperar el lease"); out["acciones"].append("alerta: sello no vigente")
            except Exception:  # noqa: BLE001
                out["sello_vigente"] = None
        if rds is None:
            self.alert("warning", "no se pudo leer el estado de la RDS del primario (plano de control)"); out["acciones"].append("alerta: estado desconocido")
        elif rds in RUNNING_STATES:
            self.alert("critical", f"la RDS del primario volvió a estar `{rds}` tras la promoción de OCI")
            if self.hard_fence is not None:
                try:
                    p = self.hard_fence()
                    if self.proof_ok(p): self.latched = True; out["acciones"].append("cerrojo y vallado fuerte aplicados (prueba completa)")
                    else: out["acciones"].append(f"vallado fuerte sin prueba completa (sesiones={p.get('app_sessions_left') if p else '?'})")
                except Exception as e:  # noqa: BLE001
                    out["acciones"].append(f"base no alcanzable todavía ({type(e).__name__})")
            if self.ratchet is not None:                                   # sube el TRINQUETE del sello en la base que acaba de volver (si el sello se escribió con la RDS detenida, aquí se anota)
                try: out["acciones"].append(f"trinquete del sello = {self.ratchet()}")
                except Exception as e:  # noqa: BLE001
                    out["acciones"].append(f"trinquete no actualizado todavía ({type(e).__name__})")
            if not self.latched and self.allow_stop_rds and self.stop_rds is not None and rds != "stopping":
                try: self.stop_rds(); out["acciones"].append("stop-db-instance ordenado de nuevo")
                except Exception as e:  # noqa: BLE001
                    out["acciones"].append(f"no se pudo ordenar la parada ({type(e).__name__})")
            if not out["acciones"] or (not self.latched and "stop-db-instance ordenado de nuevo" not in out["acciones"]):
                self.alert("critical", "RDS del primario encendida SIN cerrojo ni parada: solo el sello y la ausencia de lease impiden que escriba")
        out["latched"] = self.latched; self.events.append(out); return out
