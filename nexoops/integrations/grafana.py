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
MAX_METRIC_POINTS = 300


class Grafana:
    def __init__(self, cfg, fetch=http_json):
        self.c, self.fetch = cfg, fetch

    def _get(self, path):
        return self.fetch(self.c.grafana_url + path, headers={"Authorization": f"Bearer {self.c.grafana_token}"}, **({"cafile": self.c.grafana_cafile} if self.c.grafana_cafile else {}))

    def _abs(self, url: str) -> str:
        """Grafana detrás de un subpath (p. ej. /grafana): la URL de búsqueda ya lo incluye; no se duplica."""
        pu = urllib.parse.urlparse(self.c.grafana_url)
        origin = f"{pu.scheme}://{pu.netloc}"
        return origin + url if url.startswith(pu.path.rstrip("/") + "/") or not pu.path.strip("/") else self.c.grafana_url + url

    def health(self):
        if not self.configured():
            return envelope(SRC, "not_configured", detail="GRAFANA_URL / GRAFANA_TOKEN sin definir")
        try:
            h = self.fetch(self.c.grafana_url + "/api/health", **({"cafile": self.c.grafana_cafile} if self.c.grafana_cafile else {}))
            return envelope(SRC, "ok", {"version": str(h.get("version", "?"))[:20], "database": str(h.get("database", "?"))[:10]})
        except Exception as e:  # noqa: BLE001
            return envelope(SRC, "unavailable", detail=f"Grafana no respondió ({type(e).__name__})")

    def configured(self):
        return bool(self.c.grafana_url and self.c.grafana_token)

    def dashboards(self) -> dict:
        if not self.configured():
            return envelope(SRC, "not_configured", detail="GRAFANA_URL / GRAFANA_TOKEN sin definir")
        try:
            rows = self._get("/api/search?type=dash-db&limit=100")
        except Exception as e:  # noqa: BLE001
            return envelope(SRC, "unavailable", detail=f"Grafana no respondió ({type(e).__name__})")
        out = [{"uid": r["uid"], "title": str(r.get("title"))[:120], "folder": str(r.get("folderTitle", "General"))[:80], "tags": r.get("tags", [])[:6], "open_url": self._abs(str(r.get("url", "")))}
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

    def metrics(self, uid: str, panel_id: int, range_key: str = "1h") -> dict:
        """Consulta las series del panel mediante ``/api/ds/query``.

        La consulta se obtiene del dashboard que el token Viewer ya puede ver.
        La respuesta se reduce a valores escalares de tipo métrico y nunca
        devuelve metadatos del datasource, consultas, cabeceras ni tokens.
        """
        if not self.configured():
            return envelope(SRC, "not_configured", detail="GRAFANA_URL / GRAFANA_TOKEN sin definir")
        if not UID.match(uid) or not isinstance(panel_id, int) or isinstance(panel_id, bool) or panel_id <= 0 or range_key not in RANGES:
            return envelope(SRC, "error", detail="parámetros inválidos")
        try:
            doc = self._get(f"/api/dashboards/uid/{uid}")
            dashboard = doc.get("dashboard") if isinstance(doc, dict) else None
            panel = next((p for p in (dashboard or {}).get("panels", []) if isinstance(p, dict) and p.get("id") == panel_id), None)
            if not panel:
                return envelope(SRC, "error", detail="panel no encontrado")
            queries = []
            for target in panel.get("targets", []):
                if not isinstance(target, dict) or target.get("hide") is True:
                    continue
                q = dict(target)
                q["refId"] = str(q.get("refId", ""))[:12]
                q["datasource"] = q.get("datasource") or panel.get("datasource")
                q["maxDataPoints"], q["intervalMs"] = MAX_METRIC_POINTS, 20_000
                queries.append(q)
            if not queries:
                return envelope(SRC, "ok", {"uid": uid, "panel_id": panel_id, "title": str(panel.get("title", ""))[:120], "range": range_key, "series": []})
            raw = self.fetch(
                self.c.grafana_url + "/api/ds/query",
                method="POST",
                headers={"Authorization": f"Bearer {self.c.grafana_token}"},
                body={"queries": queries, "from": RANGES[range_key], "to": "now"},
                **({"cafile": self.c.grafana_cafile} if self.c.grafana_cafile else {}),
            )
        except Exception as e:  # noqa: BLE001
            return envelope(SRC, "unavailable", detail=f"Grafana no respondió ({type(e).__name__})")
        return envelope(SRC, "ok", {"uid": uid, "panel_id": panel_id, "title": str(panel.get("title", ""))[:120], "range": range_key,
                                     "series": self._metric_series(raw)})

    @staticmethod
    def _metric_series(raw) -> list[dict]:
        """Extrae solo campos time/number/boolean, hasta un máximo estricto."""
        out = []
        results = raw.get("results", {}) if isinstance(raw, dict) else {}
        for ref_id, result in list(results.items())[:20]:
            for frame in (result.get("frames", []) if isinstance(result, dict) else [])[:20]:
                schema = frame.get("schema", {}) if isinstance(frame, dict) else {}
                data = frame.get("data", {}) if isinstance(frame, dict) else {}
                fields, values = schema.get("fields", []), data.get("values", [])
                keep = [(i, str(f.get("name", ""))[:80], str(f.get("type", ""))) for i, f in enumerate(fields)
                        if isinstance(f, dict) and f.get("type") in ("time", "number", "boolean") and i < len(values)]
                if not keep:
                    continue
                n = min(MAX_METRIC_POINTS, *(len(values[i]) for i, _, _ in keep if isinstance(values[i], list))) if all(isinstance(values[i], list) for i, _, _ in keep) else 0
                out.append({"ref_id": str(ref_id)[:12], "fields": [{"name": name, "type": typ, "values": values[i][:n]} for i, name, typ in keep]})
        return out
