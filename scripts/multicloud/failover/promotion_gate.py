"""PUERTA DE PROMOCIÓN CONSERVADORA: OCI solo empieza a escribir con EVIDENCIA FUERTE y RECIENTE de que el primario ya NO puede confirmar ningún commit, ni antiguo ni nuevo.

Por qué: la espera `ttl+margen` del lease es un argumento de TIEMPO. Un servidor de base que se congela entre la comprobación de autoridad y el final del COMMIT puede terminar un commit después de que OCI
empiece (contraejemplo demostrado en test_two_db_pauses.py / test_two_db_ack_barrier.py). Ningún tiempo, ninguna atestación y ninguna barrera HTTP lo descartan: la barrera solo evita RECONOCER el commit.

Evidencia FUERTE (cualquiera de las dos, y reciente ≤ max_age_s):
  db_hard_fenced         la base del primario es ALCANZABLE y se la vallo con fuerza (PgFence.hard_fence): cerrojo + revocación CONFIRMADA + todas las sesiones de la aplicación TERMINADAS (0 restantes) +
                         0 transacciones preparadas. Un backend congelado que no muere deja sesiones restantes → NO hay prueba (y mientras exista, no hay promoción).
  rds_stopped_confirmed  el PLANO DE CONTROL de AWS (independiente del camino de datos) informa la RDS del primario `stopped` (no `stopping`): sin servidor no hay commit posible. Opcionalmente (`allow_stop_rds`)
                         se ORDENA la parada y se espera a `stopped` (STONITH); sin esa opción solo se acepta una parada ya existente.
NO es evidencia (se enumera en `insufficient` y NUNCA basta): atestación del vallado (por reciente que sea), caducidad del lease, timeout/ausencia de respuesta, la barrera HTTP de reconocimiento, la
compuerta HTTP del primario, EC2 detenida (la RDS podría seguir con un commit en curso), cualquier dato con más de max_age_s.
AWS «confirmadamente detenida» (clasificación CONFIRMED_FENCED) ≠ AWS «incomunicada» (UNREACHABLE: no se sabe nada fiable → NO promovible: modo seguro y alerta).
"""
from __future__ import annotations

import time

NOT_EVIDENCE = ("atestacion_del_vallado", "caducidad_del_lease", "timeout_o_silencio", "barrera_http_de_reconocimiento", "compuerta_http_del_primario", "ec2_detenida", "dato_caducado")


class StrongFence:
    def __init__(self, *, hard_fence=None, proof_ok=None, aws_read=None, stop_rds=None, allow_stop_rds: bool = False, disable_primary=None,
                 now=time.time, sleep=time.sleep, max_age_s: float = 60.0, stop_wait_s: float = 900.0, poll_s: float = 15.0):
        self.hard_fence, self.aws_read, self.stop_rds, self.allow_stop_rds, self.disable_primary = hard_fence, aws_read, stop_rds, allow_stop_rds, disable_primary
        self.proof_ok = proof_ok or (lambda p: bool(p) and p.get("latched") is True and p.get("authority_revoked") is True and p.get("app_sessions_left") == 0 and p.get("prepared_xacts") == 0)
        self.now, self.sleep, self.max_age_s, self.stop_wait_s, self.poll_s = now, sleep, max_age_s, stop_wait_s, poll_s

    def _read_aws(self):
        if self.aws_read is None:
            return None, None
        try:
            st = self.aws_read()
            return (st if isinstance(st, dict) else None), self.now()
        except Exception:  # noqa: BLE001
            return None, None

    def establish(self) -> dict:
        ev: list[dict] = []; insufficient: list[str] = []; actions: list[str] = []
        # 1) vallado fuerte por la base (si es alcanzable)
        if self.hard_fence is not None:
            try:
                proof = self.hard_fence()
                if self.proof_ok(proof):
                    ev.append({"kind": "db_hard_fenced", "strength": "strong", "observed_at": self.now(), "detail": "cerrojo + revocación confirmada + 0 sesiones de la aplicación + 0 preparadas"})
                else:
                    insufficient.append(f"vallado por la base sin prueba completa (sesiones restantes={(proof or {}).get('app_sessions_left')}, preparadas={(proof or {}).get('prepared_xacts')})")
            except Exception as e:  # noqa: BLE001
                insufficient.append(f"base del primario inalcanzable o sin permiso para vallarla ({type(e).__name__})")
        else:
            insufficient.append("sin vallado por la base configurado")
        # 2) plano de control: RDS detenida
        aws, t_aws = self._read_aws()
        rds = (aws or {}).get("rds")
        if not ev:
            if rds == "stopped":
                ev.append({"kind": "rds_stopped_confirmed", "strength": "strong", "observed_at": t_aws, "detail": "RDS `stopped` según el plano de control de AWS"})
            elif self.allow_stop_rds and self.stop_rds is not None and rds in ("available", "stopping", "starting", "backing-up", "modifying", "rebooting", "configuring-enhanced-monitoring", "storage-optimization", "maintenance"):
                try:
                    if rds != "stopping":
                        self.stop_rds(); actions.append("stop-db-instance ordenado")
                    end = self.now() + self.stop_wait_s
                    while self.now() < end:
                        aws, t_aws = self._read_aws()
                        if (aws or {}).get("rds") == "stopped":
                            ev.append({"kind": "rds_stopped_confirmed", "strength": "strong", "observed_at": t_aws, "detail": "RDS `stopped` tras ordenar la parada (plano de control de AWS)"}); break
                        self.sleep(self.poll_s)
                    if not ev: insufficient.append("la RDS no llegó a `stopped` en el plazo")
                except Exception as e:  # noqa: BLE001
                    insufficient.append(f"no se pudo ordenar/confirmar la parada de la RDS ({type(e).__name__})")
            elif aws is None:
                insufficient.append("plano de control de AWS inalcanzable: estado de la RDS desconocido")
            else:
                insufficient.append(f"RDS en estado `{rds}`: no es parada confirmada")
        if (aws or {}).get("ec2") in ("stopped", "terminated"): insufficient.append("EC2 detenida (insuficiente por sí sola: la RDS podría tener un commit en curso)")
        # 3) frescura
        t = self.now(); fresh = [e for e in ev if e.get("observed_at") is not None and 0 <= t - e["observed_at"] <= self.max_age_s]
        for e in ev:
            if e not in fresh: insufficient.append(f"{e['kind']}: dato caducado (> {self.max_age_s:g} s)")
        strong = bool(fresh)
        if strong and self.disable_primary is not None:
            try: self.disable_primary(); actions.append("aplicación del primario deshabilitada (sin reinicio automático)")
            except Exception as e:  # noqa: BLE001
                actions.append(f"no se pudo deshabilitar la aplicación del primario ({type(e).__name__}): el cerrojo/parada de la base sigue impidiendo escribir")
        cls = "CONFIRMED_FENCED" if strong else ("UNREACHABLE" if (aws is None and not ev) else "RUNNING_OR_UNKNOWN")
        return {"strong": strong, "classification": cls, "evidence": fresh, "insufficient": insufficient[:8], "actions": actions, "not_evidence": list(NOT_EVIDENCE)}
