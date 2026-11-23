import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from nexoops.app import create_app
from nexoops.integrations.grafana import Grafana, MAX_METRIC_POINTS
from nexoops.integrations.oci_azure import operational_state, snapshot
from nexoops.integrations.zabbix import Zabbix
from nexoops.mailer import CaptureMailer
from .conftest import EMAIL, PW


def test_grafana_consulta_metricas_y_sanea_salida(cfg):
    cfg.grafana_url, cfg.grafana_token = "https://grafana.test", "TOKEN-PRIVADO"
    calls = []

    def fetch(url, **kw):
        calls.append((url, kw))
        if url.endswith("/api/dashboards/uid/aws"):
            return {"dashboard": {"panels": [{"id": 7, "title": "Latencia", "datasource": {"uid": "prom"},
                                                "targets": [{"refId": "A", "expr": "latency_ms"}]}]}}
        assert url.endswith("/api/ds/query") and kw["method"] == "POST"
        return {"results": {"A": {"frames": [{"schema": {"fields": [
            {"name": "Time", "type": "time"}, {"name": "latency", "type": "number"}, {"name": "mensaje", "type": "string"}]},
            "data": {"values": [[1, 2], [12.5, 20.0], ["TOKEN-PRIVADO", "otro"]]}}]}}}

    result = Grafana(cfg, fetch).metrics("aws", 7, "1h")
    assert result["status"] == "ok" and result["data"]["panel_id"] == 7
    assert [f["name"] for f in result["data"]["series"][0]["fields"]] == ["Time", "latency"]
    assert "TOKEN-PRIVADO" not in json.dumps(result)
    query = calls[1][1]
    assert query["headers"]["Authorization"] == "Bearer TOKEN-PRIVADO"
    assert query["body"]["from"] == "now-1h" and query["body"]["to"] == "now"
    assert query["body"]["queries"][0]["maxDataPoints"] == MAX_METRIC_POINTS


def test_grafana_metricas_limita_puntos_y_rechaza_parametros(cfg):
    cfg.grafana_url, cfg.grafana_token = "https://grafana.test", "T"

    def fetch(url, **kw):
        if "dashboards" in url:
            return {"dashboard": {"panels": [{"id": 1, "targets": [{"refId": "A", "datasource": {"uid": "x"}}]}]}}
        values = list(range(MAX_METRIC_POINTS + 50))
        return {"results": {"A": {"frames": [{"schema": {"fields": [{"name": "v", "type": "number"}]}, "data": {"values": [values]}}]}}}

    g = Grafana(cfg, fetch)
    assert len(g.metrics("ok", 1)["data"]["series"][0]["fields"][0]["values"]) == MAX_METRIC_POINTS
    assert g.metrics("../escape", 1)["status"] == "error"
    assert g.metrics("ok", True)["status"] == "error"
    assert g.metrics("ok", 999)["detail"] == "panel no encontrado"


def test_endpoint_metricas_protegido_e_integrado(cfg, mail, clock):
    cfg.grafana_url, cfg.grafana_token = "https://grafana.test", "T"

    def fetch(url, **kw):
        if "dashboards" in url:
            return {"dashboard": {"panels": [{"id": 3, "title": "CPU", "targets": []}]}}
        raise AssertionError("sin consulta al datasource para panel sin targets")

    app = create_app(cfg, mailer=mail, grafana=Grafana(cfg, fetch), clock=clock)
    app.state.auth.create_user(EMAIL, PW)
    client = TestClient(app)
    path = "/api/monitoring/grafana/abc/panels/3/metrics?range=6h"
    assert client.get(path).status_code == 401
    client.post("/api/auth/login", json={"email": EMAIL, "password": PW})
    client.post("/api/auth/verify", json={"code": mail.sent[-1][1]})
    result = client.get(path)
    assert result.status_code == 200 and result.json()["data"]["range"] == "6h"
    assert client.get(path.replace("6h", "90d")).status_code == 400


def test_zabbix_problemas_incluye_hosts_y_marca_utc(cfg):
    """Como la API real de Zabbix 7.0 (verificado en la VM de Azure el 23-nov): problem.get con selectHosts es un ERROR; los hosts llegan por event.get."""
    cfg.zabbix_url, cfg.zabbix_token = "https://zabbix.test", "T"
    methods = []

    def fetch(url, **kw):
        m, p = kw["body"]["method"], kw["body"]["params"]; methods.append(m)
        if m == "problem.get":
            if "selectHosts" in p: return {"error": {"code": -32602, "message": "Invalid params.", "data": 'Invalid parameter "/": unexpected parameter "selectHosts".'}}
            return {"result": [{"eventid": "1", "name": "CPU alta", "severity": "4", "clock": "1790000000", "acknowledged": "0"}]}
        assert m == "event.get" and p["eventids"] == ["1"] and p["selectHosts"] == ["hostid", "name"]
        return {"result": [{"eventid": "1", "hosts": [{"hostid": "10", "name": "api-aws"}]}]}

    result = Zabbix(cfg, fetch).problems()
    assert result["status"] == "ok", result
    problem = result["data"]["problems"][0]
    assert problem["hosts"] == [{"id": "10", "name": "api-aws"}] and methods == ["problem.get", "event.get"]
    assert problem["since"].endswith("Z") and result["observed_at"].endswith("Z")


def test_recolector_normaliza_taxonomia_y_estados_desconocidos(cfg):
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    state = cfg.ops_state_dir / "status"
    state.mkdir(parents=True)
    (state / "cloud-status.json").write_text(json.dumps({"observed_at": "2026-11-23T12:00:00Z", "clouds": {
        "aws": {"estado": "OK", "origen": "cloud_verificado", "detalle": "3/3"},
        "oci": {"estado": "ADVERTENCIA", "origen": "cloud_verificado", "detalle": "en espera: endpoint alcanzable"},
        "azure": {"estado": "COMPROMETIDO", "origen": "inventado", "detalle": "dato no confiable"},
        "otra": {"estado": "OK", "origen": "cloud_verificado", "detalle": "no permitida"}}}))
    result = snapshot(cfg.ops_state_dir, now)
    clouds = result["data"]["clouds"]
    assert clouds["aws"]["estado_operativo"] == "operativo"
    assert clouds["oci"]["estado_operativo"] == "en_espera"
    assert clouds["azure"] == {"estado": "No verificado", "estado_operativo": "no_verificado", "origen": "sin_datos", "detalle": "estado del recolector no reconocido"}
    assert "otra" not in clouds
    assert operational_state("ADVERTENCIA", "latencia alta") == "degradado"
    assert operational_state("ERROR") == "fuera_de_servicio"
