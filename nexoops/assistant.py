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
        fid = f"H{len(facts) + 1}"
        facts.append({"id": fid, "type": "hecho", "text": text, "source": source, "observed_at": at})
        marker = {"source": source, "observed_at": at}
        if marker not in evid:
            evid.append(marker)
        return fid
    def hypothesis(text, confidence, based_on):
        hyp.append({"type": "hipotesis", "text": text, "confidence": confidence, "based_on": list(based_on)})
    def recommend(text, action=None):
        rec.append({"text": text, "action": action, "execution": "no_ejecutada"})

    col = overview.get("collector") or {"status": "unavailable", "detail": "sin estado del recolector", "observed_at": None}
    if col.get("status") != "ok":
        fid = fact(f"El recolector de sondas no entrega datos vigentes: {col.get('detail', 'sin detalle')}.", "Recolector T4", col.get("observed_at"))
        hypothesis("El recolector o el temporizador en la VM de Azure podría estar detenido, o la instantánea es obsoleta.", "media", [fid])
        recommend("Comprobar `ops-collector.timer` en la VM de Azure y ejecutar la acción «Ejecutar comprobación de salud».", "health.check")
    if "incidentes" in topics or "latencia" in topics:
        cloud_facts = {}
        clouds = overview.get("clouds") or {}
        for n, c in clouds.items():
            if c.get("estado") in ("ERROR", "ADVERTENCIA"):
                cloud_facts[n] = fact(f"{n.upper()} en estado {c.get('estado')}: {c.get('detalle', 'sin detalle')}", "Recolector T4", c.get("observed_at"))
        if (clouds.get("aws") or {}).get("estado") == "ERROR":
            hypothesis("La entrada pública de AWS no responde: posible caída del ALB, de las instancias del ASG o de la base de datos.", "media", [cloud_facts["aws"]])
            recommend("Revisar actividades del ASG y alarmas de CloudWatch; confirmar con Zabbix antes de intervenir.", "aws.asg_activities")
        if problems.get("status") == "ok":
            ps = ((problems.get("data") or {}).get("problems") or [])
            hi = [p for p in ps if isinstance(p, dict) and isinstance(p.get("severity_n"), (int, float)) and p["severity_n"] >= 4]
            zfid = fact(f"Zabbix reporta {len(ps)} problemas activos ({len(hi)} de severidad alta o superior).", "Zabbix API", problems.get("observed_at"))
            for p in hi[:5]:
                fact(f"[{p['severity']}] {p['name']} desde {p['since']}", "Zabbix API", problems.get("observed_at"))
            if len(hi) >= 2:
                hypothesis("Varias alertas altas simultáneas sugieren una causa común (red, base de datos o un servicio compartido); correlacionar por hora de inicio.", "baja", [zfid])
        else:
            fact(f"Zabbix no aporta datos: {problems.get('detail', 'sin detalle')}.", "Zabbix API", problems.get("observed_at"))
    if "recuperacion" in topics:
        b = recovery.get("barreras") or {"barriers": []}
        barriers = b.get("barriers") or []
        failed = [str(x.get("id", "desconocida")) for x in barriers if not x.get("ok")]
        fact(f"{len(failed)} de {len(barriers)} barreras de failover no se cumplen: {', '.join(failed[:6]) or 'ninguna'}.", "ops_center · barreras", recovery.get("generated_at"))
        fact(f"Fencing: {(recovery.get('fencing') or {}).get('veredicto', 'UNKNOWN')}; epoch: {recovery.get('epoch_autorizado', 'no verificado')}.", "ops_center · registro de failover", recovery.get("generated_at"))
        recommend("No iniciar failover: está bloqueado por diseño hasta demostrar las barreras. Documentar evidencias pendientes (T5/T6).")
    if not facts:
        fact("Sin hallazgos: no hay datos suficientes o todo está en estado normal en las fuentes consultadas.", "NexoOps", utc())
    draft = None
    if ((overview.get("clouds") or {}).get("aws") or {}).get("estado") == "ERROR":
        draft = {"action": "service.restart.request", "params": {"service": "nexoeventos-api", "reason": "AWS en ERROR según el recolector; solicitud preparada, requiere aprobación independiente"}, "nota": "Borrador: NO se envió. Queda bloqueada hasta tener aprobación independiente."}
    return {"generated_at": utc(), "engine": "determinista (reglas)", "llm": {"estado": "pendiente" if not llm_provider else "configurado pero no integrado", "detalle": "Sin modelo de IA conectado; no se simula inteligencia artificial."},
            "pregunta": (question or "")[:300], "temas": topics, "hechos": facts, "hipotesis": hyp, "recomendaciones": rec, "evidencias": evid, "borrador_solicitud": draft}
