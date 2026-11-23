"""Failback OCI → AWS: NUNCA automático. Función pura que, dado el estado observado, dice si el retorno está permitido y qué falta. El orquestador de failover no la ejecuta: solo informa al panel.

Principios (por qué es manual):
  · tras una promoción, OCI es el único escritor y sus datos son los vigentes; los de AWS son anteriores o divergentes: NO se fusionan, AWS se RESTAURA desde un respaldo de OCI;
  · AWS no debe poder escribir mientras tanto (vallado verificado) y solo recupera el lease con una época posterior, tras la decisión de una persona;
  · el DNS vuelve a AWS únicamente después de que AWS pase las comprobaciones de salud con los datos restaurados.
Distingue explícitamente los MODOS: recuperación desde respaldo · standby preparado · failover automático · failback (este).
"""
from __future__ import annotations

MODES = ("RECUPERACION_DESDE_RESPALDO", "STANDBY_PREPARADO", "FAILOVER_AUTOMATICO", "FAILBACK")


def plan_failback(*, ledger_state: str, primary_fenced: bool, primary_data_status: str, standby_is_writer: bool, human_approved: bool = False, aws_health_ok: bool = False) -> dict:
    blockers: list[str] = []
    if ledger_state not in ("PROMOTED", "WRITER_ENABLED", "UNCERTAIN_DNS"):
        blockers.append(f"el registro de promoción está en {ledger_state}: no hay una promoción que revertir")
    if not standby_is_writer:
        blockers.append("OCI no es el escritor activo: no hay nada que devolver")
    if not primary_fenced:
        blockers.append("el primario de AWS no está vallado con evidencia: podría escribir durante el retorno")
    if primary_data_status != "REEMPLAZADO_DESDE_OCI":
        blockers.append("los datos de AWS no se han reemplazado desde un respaldo de OCI (no se fusionan: pueden haber divergido)")
    if not aws_health_ok:
        blockers.append("AWS no ha pasado las comprobaciones de salud con los datos restaurados")
    if not human_approved:
        blockers.append("falta la aprobación expresa de una persona (revisión humana obligatoria)")
    steps = ["mantener OCI como único escritor", "vallar y verificar AWS (compuerta cerrada, sin lease)", "restaurar AWS desde un respaldo de OCI y verificar la huella",
             "comprobar salud de AWS (/livez, /ready, API) sin dirigirle tráfico", "decisión humana: ventana de mantenimiento", "OCI cede el lease (época nueva) y AWS lo toma",
             "cambiar el DNS a AWS y verificar", "volver a armar el standby de OCI"]
    return {"automatic": False, "allowed": not blockers, "blockers": blockers, "steps": steps}
