"""NexoOps AI — diagnóstico DETERMINISTA sobre datos de monitoreo autorizados. NO es un modelo de lenguaje: la integración de IA (NEXOOPS_LLM_PROVIDER) está PENDIENTE y se declara así.
Separa hechos observados (con fuente y hora), hipótesis (reglas, con confianza) y recomendaciones. No ejecuta acciones: solo puede PREPARAR el borrador de una solicitud."""
from __future__ import annotations

from .integrations import utc

TOPICS = {"recuperacion": ("recuper", "failover", "oci", "lease", "fencing", "respaldo"), "incidentes": ("incident", "alerta", "problema", "zabbix"), "latencia": ("latenc", "lent", "disponib", "metric")}


def _topic(q: str):
    q = (q or "").lower()
    return [t for t, kws in TOPICS.items() if any(k in q for k in kws)] or list(TOPICS)


def diagnose(question: str, overview: dict, recovery: dict, problems: dict, llm_provider: str = "") -> dict:
    topics = _topic(question)
    facts, hyp, rec, evid = [], [], [], []
    def fact(text, source, at):
        facts.append({"text": text, "source": source, "observed_at": at}); evid.append({"source": source, "observed_at": at})
    col = overview["collector"]
    if col["status"] != "ok":
        fact(f"El recolector de sondas no entrega datos vigentes: {col['detail']}.", "Recolector T4", col["observed_at"])
        hyp.append({"text": "El recolector o el temporizador en la VM de Azure podría estar detenido, o la instantánea es obsoleta.", "confidence": "media"})
        rec.append({"text": "Comprobar `ops-collector.timer` en la VM de Azure y ejecutar la acción «Ejecutar comprobación de salud».", "action": "health.check"})
    if "incidentes" in topics or "latencia" in topics:
        for n, c in overview["clouds"].items():
            if c["estado"] in ("ERROR", "ADVERTENCIA"):
                fact(f"{n.upper()} en estado {c['estado']}: {c['detalle']}", "Recolector T4", c["observed_at"])
        if overview["clouds"]["aws"]["estado"] == "ERROR":
            hyp.append({"text": "La entrada pública de AWS no responde: posible caída del ALB, de las instancias del ASG o de la base de datos.", "confidence": "media"})
            rec.append({"text": "Revisar actividades del ASG y alarmas de CloudWatch; confirmar con Zabbix antes de intervenir.", "action": "aws.asg_activities"})
        if problems["status"] == "ok":
            ps = problems["data"]["problems"]
            hi = [p for p in ps if p["severity_n"] >= 4]
            fact(f"Zabbix reporta {len(ps)} problemas activos ({len(hi)} de severidad alta o superior).", "Zabbix API", problems["observed_at"])
            for p in hi[:5]:
                fact(f"[{p['severity']}] {p['name']} desde {p['since']}", "Zabbix API", problems["observed_at"])
            if len(hi) >= 2:
                hyp.append({"text": "Varias alertas altas simultáneas sugieren una causa común (red, base de datos o un servicio compartido); correlacionar por hora de inicio.", "confidence": "baja"})
        else:
            fact(f"Zabbix no aporta datos: {problems['detail']}.", "Zabbix API", None)
    if "recuperacion" in topics:
        b = recovery["barreras"]
        failed = [x["id"] for x in b["barriers"] if not x["ok"]]
        fact(f"{len(failed)} de {len(b['barriers'])} barreras de failover no se cumplen: {', '.join(failed[:6]) or 'ninguna'}.", "ops_center · barreras", recovery["generated_at"])
        fact(f"Fencing: {(recovery['fencing'] or {}).get('veredicto', 'UNKNOWN')}; epoch: {recovery['epoch_autorizado']}.", "ops_center · registro de failover", recovery["generated_at"])
        rec.append({"text": "No iniciar failover: está bloqueado por diseño hasta demostrar las barreras. Documentar evidencias pendientes (T5/T6).", "action": None})
    if not facts:
        facts.append({"text": "Sin hallazgos: no hay datos suficientes o todo está en estado normal en las fuentes consultadas.", "source": "NexoOps", "observed_at": utc()})
    draft = None
    if overview["clouds"]["aws"]["estado"] == "ERROR":
        draft = {"action": "service.restart.request", "params": {"service": "nexoeventos-api", "reason": "AWS en ERROR según el recolector; solicitud preparada, requiere aprobación independiente"}, "nota": "Borrador: NO se envió. Queda bloqueada hasta tener aprobación independiente."}
    return {"generated_at": utc(), "engine": "determinista (reglas)", "llm": {"estado": "pendiente" if not llm_provider else "configurado pero no integrado", "detalle": "Sin modelo de IA conectado; no se simula inteligencia artificial."},
            "pregunta": (question or "")[:300], "temas": topics, "hechos": facts, "hipotesis": hyp, "recomendaciones": rec, "evidencias": evid, "borrador_solicitud": draft}
