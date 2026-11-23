"""Detector de incidentes del primario con señales INDEPENDIENTES y protección contra falsos positivos. Lógica pura (las señales llegan por llamadas inyectadas; sin red propia).

Familias independientes de señales:
  http   desde el sitio de recuperación: /livez (proceso), /ready (proceso + BD), /write-gate (compuerta) y un sondeo de CONTROL (¿puede este sondeador ver Internet?)
  aws    plano de control de AWS (solo lectura): estado de la EC2 y de la RDS del primario
Un solo tipo de señal NO basta para declarar una caída: «INSTANCE_DOWN» exige que /livez falle Y que AWS diga que la instancia está parada/terminada. Si el sondeador no puede ver su
control, no se concluye nada. Las rondas consecutivas y el quórum los aplica el orquestador (DECIDE); aquí se clasifica cada observación.

Clases (kind) y si son candidatas a promoción (promotable; el vallado se exige después, en FENCE_CHECK):
  HEALTHY             el primario responde y puede atender: no se actúa
  SONDEADOR_AISLADO   el control del sondeador falla/desconocido: no se concluye (podría ser NUESTRA red)
  INSTANCE_DOWN       /livez falla y la EC2 está stopped/terminated (dos familias coinciden): candidata
  DB_DOWN             /livez ok, /ready falla y la RDS no está available: candidata SOLO con vallado (la aplicación sigue viva y escribiría al volver la base)
  NETWORK_ISOLATION   /livez falla pero AWS dice que la EC2 corre y la RDS está bien (o es desconocido): ambigua; candidata únicamente si la compuerta del primario está atestiguada
  TRANSIENT           señales contradictorias o parciales: no se actúa
"""
from __future__ import annotations

STOPPED = {"stopped", "terminated"}


def classify(sig: dict, *, gate_attested: bool | None = None) -> dict:
    livez, ready, control = sig.get("livez"), sig.get("ready"), sig.get("control")
    ec2, rds, gate = sig.get("ec2"), sig.get("rds"), sig.get("write_gate")
    reasons: list[str] = []

    def out(kind, promotable):
        return {"kind": kind, "promotable": promotable, "reasons": reasons, "signals": {k: (v if isinstance(v, (bool, str)) or v is None else str(v)) for k, v in sig.items()}}
    if control is not True:
        reasons.append("el sondeo de control del sondeador no responde: no se concluye nada sobre el primario")
        return out("SONDEADOR_AISLADO", False)
    if livez is True and ready is True and gate != "vallado":
        reasons.append("el primario responde (/livez y /ready)")
        return out("HEALTHY", False)
    if livez is False:
        if ec2 in STOPPED:
            reasons.append(f"/livez falla y AWS confirma la EC2 {ec2}: dos familias de señales coinciden")
            return out("INSTANCE_DOWN", True)
        if ec2 is None:
            reasons.append("/livez falla pero el estado de la EC2 es desconocido: una sola familia no basta")
            return out("TRANSIENT", False)
        reasons.append(f"/livez falla pero AWS dice que la EC2 está {ec2}: aislamiento de red o fallo de la aplicación")
        ok = gate_attested is True
        if not ok:
            reasons.append("sin atestación de la compuerta del primario no hay garantía de que se vallara solo")
        return out("NETWORK_ISOLATION", ok)
    if livez is True and ready is False:
        if rds is not None and rds != "available":
            reasons.append(f"/livez ok, /ready falla y la RDS está {rds}: la aplicación sigue viva sin base; exige vallado antes de promover")
            return out("DB_DOWN", True)
        reasons.append("/ready falla pero la RDS figura disponible o desconocida: señales contradictorias")
        return out("TRANSIENT", False)
    reasons.append("señales incompletas o contradictorias")
    return out("TRANSIENT", False)


class IncidentDetector:
    """Observa las señales (callables inyectados) y las clasifica. `observe()` no tiene efectos: solo lee."""
    def __init__(self, *, livez, ready, control, gate=lambda: None, aws=lambda: {"ec2": None, "rds": None}, gate_attested=None):
        self.livez, self.ready, self.control, self.gate, self.aws, self._att = livez, ready, control, gate, aws, gate_attested

    def _safe(self, f):
        try:
            return f()
        except Exception:  # noqa: BLE001 — una señal que falla es DESCONOCIDA, nunca «sana» ni «caída»
            return None

    def observe(self) -> dict:
        aws = self._safe(self.aws) or {}
        sig = {"livez": self._safe(self.livez), "ready": self._safe(self.ready), "control": self._safe(self.control), "write_gate": self._safe(self.gate),
               "ec2": aws.get("ec2"), "rds": aws.get("rds")}
        att = self._safe(self._att) if callable(self._att) else self._att
        return classify(sig, gate_attested=att)
