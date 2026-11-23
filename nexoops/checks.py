"""Verificación de integraciones de SOLO LECTURA (`python -m nexoops check-integrations`). Cada comprobación devuelve PASS / FAIL / NOT_CONFIGURED con marca UTC; nunca inventa un resultado ni incluye secretos.
El correo NO se prueba aquí (enviaría un mensaje): usa `send-test-mail`. El resultado se guarda en DATA_DIR/integration-check.json como evidencia."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .integrations import utc


def _r(name, env, extra=""):
    st = {"ok": "PASS", "not_configured": "NOT_CONFIGURED"}.get(env["status"], "FAIL")
    return {"check": name, "result": st, "detail": (extra or env.get("detail") or "")[:200], "at": utc()}


def run(cfg, grafana, zabbix, aws, write=True) -> dict:
    out = []
    h = grafana.health(); out.append(_r("grafana.health", h, f"Grafana {h['data']['version']}" if h["status"] == "ok" else ""))
    d = grafana.dashboards(); out.append(_r("grafana.dashboards (token Viewer)", d, f"{len(d['data']['dashboards'])} dashboards visibles" if d["status"] == "ok" else ""))
    v = zabbix.version(); out.append(_r("zabbix.apiinfo.version", v, f"Zabbix API {v['data']['version']}" if v["status"] == "ok" else ""))
    hs = zabbix.hosts(); out.append(_r("zabbix.host.get (token solo lectura)", hs, f"{len(hs['data']['hosts'])} hosts" if hs["status"] == "ok" else ""))
    pr = zabbix.problems(); out.append(_r("zabbix.problem.get", pr, f"{len(pr['data']['problems'])} problemas activos" if pr["status"] == "ok" else ""))
    a = aws.summary(); out.append(_r("aws.describe_* (solo lectura)", a, "consultas describe_* correctas" if a["status"] == "ok" else ""))
    mail = {"check": "correo.smtp", "result": "NOT_CONFIGURED" if not (cfg.smtp_host and cfg.smtp_from) and cfg.mail_mode == "smtp" else "NOT_TESTED", "detail": "ejecuta `send-test-mail` para enviar un mensaje real y confirma la recepción", "at": utc()}
    out.append(mail)
    res = {"generated_at": utc(), "results": out, "summary": {k: sum(1 for x in out if x["result"] == k) for k in ("PASS", "FAIL", "NOT_CONFIGURED", "NOT_TESTED")}}
    if write:
        p = Path(cfg.data_dir) / "integration-check.json"; p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return res
