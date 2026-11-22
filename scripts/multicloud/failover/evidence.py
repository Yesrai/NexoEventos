"""Evidencia de VALLADO del primario (¿puede seguir escribiendo?) y lectura de solo lectura del estado de AWS. Lógica pura y comprobable: sin red por sí misma (el lector de AWS recibe un ejecutor).

Veredictos:  CAN_WRITE → bloquea la promoción · UNKNOWN → bloquea y alerta · FENCED → puede promoverse.
Evidencia (tipo, fuerza):
  write_gate   verificada  el primario responde en /write-gate: «escribe» (CAN_WRITE) o «vallado» (FENCED: sin lease no escribe)
  aws_instance verificada  EC2 del primario `stopped`/`terminated` por la API de AWS: el proceso no existe, no puede escribir (FENCED). `running`/`pending` = ninguna evidencia
  db_fence     verificada  el vallado EXTERNO de la base del primario (lo hace cumplir el servidor) quedó confirmado
  lease_expiry inferida    el primario es inalcanzable PERO su compuerta está atestiguada en enforce, la atestación VIGENTE del vallado en su BASE (pg_fence) es completa y este standby ya TOMÓ el lease
Una caída solo de RDS NO es vallado: la aplicación seguiría viva y escribiría al volver la base. Sin compuerta atestiguada ni vallado de BD, esa caída no es promovible.
"""
from __future__ import annotations

import json
import subprocess

STOPPED_EC2 = {"stopped", "terminated"}


def assess_fencing(*, gate: str | None, aws: dict | None = None, db_fence: bool | None = None, gate_attested: bool | None = None, lease_held: bool = False, db_attested: bool | None = None,
                   strong: dict | None = None, require_strong: bool = False) -> dict:
    """gate: 'escribe' | 'vallado' | None (inalcanzable). aws: {"ec2": estado|None, "rds": estado|None}.
    require_strong=True (modo de promoción AUTOMÁTICA): SOLO la evidencia fuerte de promotion_gate (base vallada con fuerza o RDS detenida por el plano de control, reciente) permite FENCED. La compuerta, la EC2
    detenida, la atestación y la caducidad del lease dejan de ser suficientes: no excluyen un commit antiguo pendiente en un servidor de base congelado."""
    if require_strong:
        if strong and strong.get("strong"):
            return {"verdict": "FENCED", "evidence": [{"kind": e["kind"], "strength": "verified", "detail": e.get("detail", "")} for e in strong.get("evidence", [])], "classification": strong.get("classification")}
        why = "; ".join((strong or {}).get("insufficient", [])[:3]) or "sin evidencia fuerte"
        return {"verdict": "CAN_WRITE" if gate == "escribe" else "UNKNOWN", "evidence": [{"kind": "sin_evidencia_fuerte", "strength": "none", "detail": why[:120]}], "classification": (strong or {}).get("classification", "UNREACHABLE")}
    ev: list[dict] = []
    if gate == "escribe" and db_fence is not True:
        return {"verdict": "CAN_WRITE", "evidence": [{"kind": "write_gate", "strength": "verified", "detail": "el primario acepta escrituras"}]}
    if gate == "escribe":   # la compuerta HTTP dice «escribe», pero el vallado EXTERNO de su base (lo hace cumplir el servidor) rechaza sus commits: es la evidencia que manda
        return {"verdict": "FENCED", "evidence": [{"kind": "db_fence", "strength": "verified", "detail": "vallado de la base del primario confirmado (el servidor rechaza sus escrituras) aunque su compuerta HTTP escriba"}]}
    if gate == "vallado":
        ev.append({"kind": "write_gate", "strength": "verified", "detail": "el primario informa que no tiene lease (compuerta cerrada)"})
    ec2 = (aws or {}).get("ec2")
    if ec2 in STOPPED_EC2:
        ev.append({"kind": "aws_instance", "strength": "verified", "detail": f"la instancia del primario está {ec2} (API de AWS)"})
    if db_fence is True:
        ev.append({"kind": "db_fence", "strength": "verified", "detail": "vallado de la base del primario confirmado"})
    # Evidencia INFERIDA (primario inalcanzable): NO basta la compuerta de la aplicación. Exige además la atestación VIGENTE del vallado EN LA BASE del primario (pg_fence: triggers al COMMIT con el reloj
    # de la base, caducidad sola): es la garantía comprobable de que sin renovar el lease ese primario no puede confirmar escrituras. Sin ella no hay evidencia suficiente.
    if not ev and gate is None and gate_attested is True and db_attested is True and lease_held:
        ev.append({"kind": "lease_expiry", "strength": "inferred", "detail": "primario inalcanzable; su base rechaza commits sin autoridad (atestación vigente) y su lease caducó: este standby lo tomó"})
    return {"verdict": "FENCED" if ev else "UNKNOWN", "evidence": ev}


class AwsState:
    """Lee (SOLO LECTURA) el estado de la EC2 y de la RDS del primario con la AWS CLI. `run(cmd) -> str` es inyectable (pruebas). Cualquier error = None (desconocido, nunca «parado»)."""
    def __init__(self, *, instance_tag: str = "nexoeventos-academy-app", db_id: str = "nexoeventos-academy-postgres", run=None, profile: str | None = None, region: str | None = None):
        self.tag, self.db, self.profile, self.region = instance_tag, db_id, profile, region
        self.run = run or self._run

    def _base(self):
        return ["aws", *(["--profile", self.profile] if self.profile else []), *(["--region", self.region] if self.region else [])]

    @staticmethod
    def _run(cmd: list[str]) -> str:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise OSError("aws falló")
        return r.stdout

    def read(self) -> dict:
        out = {"ec2": None, "rds": None}
        try:
            d = json.loads(self.run([*self._base(), "ec2", "describe-instances", "--filters", f"Name=tag:Name,Values={self.tag}", "--query", "Reservations[].Instances[].State.Name", "--output", "json"]))
            if isinstance(d, list) and d and all(isinstance(x, str) for x in d):
                out["ec2"] = d[0] if len(set(d)) == 1 else None       # estados mezclados = desconocido
        except Exception:  # noqa: BLE001
            pass
        try:
            d = json.loads(self.run([*self._base(), "rds", "describe-db-instances", "--db-instance-identifier", self.db, "--query", "DBInstances[].DBInstanceStatus", "--output", "json"]))
            if isinstance(d, list) and len(d) == 1 and isinstance(d[0], str):
                out["rds"] = d[0]
        except Exception:  # noqa: BLE001
            pass
        return out
