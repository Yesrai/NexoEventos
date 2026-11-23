"""Zabbix: JSON-RPC desde el backend con un token de API de un usuario Zabbix de solo lectura (ZABBIX_TOKEN). Solo métodos *.get. El navegador nunca ve el token."""
from __future__ import annotations

from datetime import datetime, timezone

from . import envelope, http_json

SRC = "Zabbix API"
SEV = {"0": "No clasificada", "1": "Información", "2": "Advertencia", "3": "Media", "4": "Alta", "5": "Desastre"}
READ_ONLY = ("host.get", "problem.get", "event.get", "apiinfo.version")


def _iso(ts):
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


class Zabbix:
    def __init__(self, cfg, fetch=http_json):
        self.c, self.fetch = cfg, fetch

    def configured(self):
        return bool(self.c.zabbix_url and self.c.zabbix_token)

    def _rpc(self, method, params):
        if method not in READ_ONLY:
            raise PermissionError("método Zabbix no permitido")
        body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        headers = {"Content-Type": "application/json-rpc"}
        if method != "apiinfo.version":                       # apiinfo.version no admite autenticación
            if self.c.zabbix_auth == "body":
                body["auth"] = self.c.zabbix_token
            else:
                headers["Authorization"] = f"Bearer {self.c.zabbix_token}"
        r = self.fetch(self.c.zabbix_url + "/api_jsonrpc.php", method="POST", headers=headers, body=body, **({"cafile": self.c.zabbix_cafile} if self.c.zabbix_cafile else {}))
        if isinstance(r, dict) and r.get("error"):
            raise RuntimeError("error de la API de Zabbix")
        return r["result"]

    def _wrap(self, fn):
        if not self.configured():
            return envelope(SRC, "not_configured", detail="ZABBIX_URL / ZABBIX_TOKEN sin definir")
        try:
            return envelope(SRC, "ok", fn())
        except Exception as e:  # noqa: BLE001
            return envelope(SRC, "unavailable", detail=f"Zabbix no respondió ({type(e).__name__})")

    def version(self):
        def f():
            return {"version": str(self._rpc("apiinfo.version", {}))[:20]}
        return self._wrap(f)

    def hosts(self):
        def f():
            rows = self._rpc("host.get", {"output": ["hostid", "name", "status", "available"], "limit": 200})
            return {"hosts": [{"id": h["hostid"], "name": str(h["name"])[:80], "monitored": h.get("status") == "0", "available": {"0": "desconocido", "1": "disponible", "2": "no disponible"}.get(str(h.get("available")), "desconocido")} for h in rows]}
        return self._wrap(f)

    def problems(self):
        def f():
            # Zabbix 7.0: problem.get NO admite selectHosts (devuelve error de API); los hosts se piden con event.get sobre los mismos eventos (también de solo lectura).
            rows = self._rpc("problem.get", {"output": ["eventid", "name", "severity", "clock", "acknowledged"], "recent": False, "sortfield": ["eventid"], "sortorder": "DESC", "limit": 50})
            ids = [str(p["eventid"]) for p in rows]
            hosts = {}
            if ids:
                for ev in self._rpc("event.get", {"output": ["eventid"], "eventids": ids, "selectHosts": ["hostid", "name"]}):
                    hosts[str(ev.get("eventid"))] = [{"id": str(h.get("hostid", ""))[:32], "name": str(h.get("name", ""))[:80]} for h in (ev.get("hosts") or [])[:20] if isinstance(h, dict)]
            return {"problems": [{"event_id": p["eventid"], "name": str(p["name"])[:160], "severity": SEV.get(str(p["severity"]), "?"), "severity_n": int(p["severity"]), "since": _iso(p["clock"]), "acknowledged": p.get("acknowledged") == "1",
                                   "hosts": hosts.get(str(p["eventid"]), [])} for p in rows]}
        return self._wrap(f)

    def history(self):
        """Historial de incidentes con su estado de recuperación (r_eventid ≠ 0 ⇒ resuelto)."""
        def f():
            rows = self._rpc("event.get", {"output": ["eventid", "name", "severity", "clock", "r_eventid"], "source": 0, "object": 0, "value": 1, "sortfield": ["eventid"], "sortorder": "DESC", "limit": 50})
            return {"events": [{"event_id": e["eventid"], "name": str(e["name"])[:160], "severity": SEV.get(str(e["severity"]), "?"), "at": _iso(e["clock"]), "recovered": str(e.get("r_eventid", "0")) != "0"} for e in rows]}
        return self._wrap(f)
