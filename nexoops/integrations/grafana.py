"""Grafana: el backend consulta la API con un token de cuenta de servicio de rol Viewer (variable GRAFANA_TOKEN; nunca llega al navegador). Se respetan los permisos de Grafana:
solo se listan los dashboards que ese token puede ver. Los paneles se muestran por iframe `d-solo` SOLO si Grafana permite incrustación (NEXOOPS_GRAFANA_EMBED=1 y allow_embedding=true
en Grafana); si no, se ofrece el enlace autenticado de Grafana. La edición se hace en Grafana (enlace «Abrir/Editar»)."""
from __future__ import annotations

import re
import urllib.parse

from . import envelope, http_json

SRC = "Grafana API"
RANGES = {"15m": "now-15m", "1h": "now-1h", "6h": "now-6h", "24h": "now-24h", "7d": "now-7d"}
UID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class Grafana:
    def __init__(self, cfg, fetch=http_json):
        self.c, self.fetch = cfg, fetch

    def _get(self, path):
        return self.fetch(self.c.grafana_url + path, headers={"Authorization": f"Bearer {self.c.grafana_token}"})

    def configured(self):
        return bool(self.c.grafana_url and self.c.grafana_token)

    def dashboards(self) -> dict:
        if not self.configured():
            return envelope(SRC, "not_configured", detail="GRAFANA_URL / GRAFANA_TOKEN sin definir")
        try:
            rows = self._get("/api/search?type=dash-db&limit=100")
        except Exception as e:  # noqa: BLE001
            return envelope(SRC, "unavailable", detail=f"Grafana no respondió ({type(e).__name__})")
        out = [{"uid": r["uid"], "title": str(r.get("title"))[:120], "folder": str(r.get("folderTitle", "General"))[:80], "tags": r.get("tags", [])[:6], "open_url": self.c.grafana_url + str(r.get("url", ""))}
               for r in rows if isinstance(r, dict) and UID.match(str(r.get("uid", "")))]
        return envelope(SRC, "ok", {"dashboards": out})

    def panels(self, uid: str, range_key: str = "1h") -> dict:
        if not self.configured():
            return envelope(SRC, "not_configured", detail="GRAFANA_URL / GRAFANA_TOKEN sin definir")
        if not UID.match(uid) or range_key not in RANGES:
            return envelope(SRC, "error", detail="parámetros inválidos")
        try:
            d = self._get(f"/api/dashboards/uid/{uid}")
        except Exception as e:  # noqa: BLE001
            return envelope(SRC, "unavailable", detail=f"Grafana no respondió ({type(e).__name__})")
        dash = d.get("dashboard", {})
        base = self.c.grafana_url
        panels = []
        for p in dash.get("panels", []):
            if not isinstance(p, dict) or p.get("type") == "row" or not isinstance(p.get("id"), int):
                continue
            q = urllib.parse.urlencode({"orgId": 1, "panelId": p["id"], "from": RANGES[range_key], "to": "now", "theme": "light"})
            panels.append({"id": p["id"], "title": str(p.get("title", ""))[:120], "type": str(p.get("type"))[:24],
                           "embed_url": f"{base}/d-solo/{uid}/_?{q}" if self.c.grafana_embed else None,
                           "open_url": f"{base}/d/{uid}/_?viewPanel={p['id']}&from={RANGES[range_key]}&to=now", "edit_url": f"{base}/d/{uid}/_?editPanel={p['id']}"})
        return envelope(SRC, "ok", {"uid": uid, "title": str(dash.get("title"))[:120], "range": range_key, "embed_allowed": bool(self.c.grafana_embed), "panels": panels})
