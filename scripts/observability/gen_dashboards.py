#!/usr/bin/env python3
"""Genera los paneles de Grafana (JSON) de NexoEventos: resumen en vivo, histórico AWS, histórico OCI y VM de Azure.
La fuente de verdad son estas definiciones; los JSON generados se versionan en ansible/roles/monitoring_zabbix_grafana/{files/grafana/dashboards,templates}.
Uso: python3 scripts/observability/gen_dashboards.py"""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "ansible/roles/monitoring_zabbix_grafana"
ZDS = {"type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-nexo"}
ADS = {"type": "grafana-azure-monitor-datasource", "uid": "azure-monitor"}


def ztarget(host, item, ref="A", legend=None):
    t = {"datasource": ZDS, "queryType": "0", "group": {"filter": "/.*/"}, "host": {"filter": host}, "application": {"filter": ""}, "itemTag": {"filter": ""},
         "item": {"filter": item}, "functions": [], "mode": 0, "refId": ref,
         "options": {"showDisabledItems": False, "skipEmptyValues": False, "disableDataAlignment": False, "useZabbixValueMapping": True}}
    if legend:
        t["functions"] = [{"def": {"name": "setAlias", "category": "Alias", "params": [{"name": "alias", "type": "string"}], "defaultParams": []}, "params": [legend], "text": f'setAlias({legend})'}]
    return t


def ts(pid, title, x, y, w, h, targets, unit="short", desc="", ds=ZDS, mx=None):
    d = {"id": pid, "type": "timeseries", "title": title, "description": desc, "datasource": ds, "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "fieldConfig": {"defaults": {"unit": unit, "custom": {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 12, "showPoints": "auto", "spanNulls": True}}, "overrides": []},
         "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}, "targets": targets}
    if mx is not None:
        d["fieldConfig"]["defaults"]["max"] = mx
    return d


def stat(pid, title, x, y, w, h, targets, unit="short", mappings=None, thresholds=None, desc=""):
    return {"id": pid, "type": "stat", "title": title, "description": desc, "datasource": ZDS, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "fieldConfig": {"defaults": {"unit": unit, "mappings": mappings or [], "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "green", "value": None}]}}, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "background", "graphMode": "area", "textMode": "auto"}, "targets": targets}


def text(pid, x, y, w, h, md):
    return {"id": pid, "type": "text", "title": "", "gridPos": {"x": x, "y": y, "w": w, "h": h}, "options": {"mode": "markdown", "content": md}}


def problems(pid, x, y, w, h):
    return {"id": pid, "type": "alexanderzobnin-zabbix-triggers-panel", "title": "Problemas activos (Zabbix)", "datasource": ZDS, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "options": {"layout": "table", "sortProblems": "lastchange", "showEvents": "all", "fontSize": "100%", "triggerSeverity": [{"color": "#B7DBAB", "priority": 0, "severity": "Not classified", "show": True},
            {"color": "#FFF9A1", "priority": 2, "severity": "Warning", "show": True}, {"color": "#FFB357", "priority": 3, "severity": "Average", "show": True}, {"color": "#FF7F50", "priority": 4, "severity": "High", "show": True},
            {"color": "#E24D42", "priority": 5, "severity": "Disaster", "show": True}]},
            "targets": [{"datasource": ZDS, "queryType": "5", "group": {"filter": "/.*/"}, "host": {"filter": ""}, "proxy": {"filter": ""}, "application": {"filter": ""}, "itemTag": {"filter": ""},
                         "trigger": {"filter": ""}, "tags": {"filter": ""}, "showProblems": "problems", "options": {"hostsInMaintenance": False, "acknowledged": 2, "limit": 100, "minSeverity": 2}, "refId": "A"}]}


def dash(uid, title, panels, tags, time_from="now-6h", desc=""):
    return {"uid": uid, "title": title, "description": desc, "tags": ["nexoeventos"] + tags, "timezone": "utc", "schemaVersion": 39, "version": 1, "editable": False,
            "refresh": "1m" if time_from == "now-6h" else "", "time": {"from": time_from, "to": "now"}, "panels": panels, "templating": {"list": []}, "annotations": {"list": []}}


UPDOWN = [{"type": "value", "options": {"200": {"text": "DISPONIBLE (200)", "color": "green"}, "0": {"text": "SIN RESPUESTA", "color": "red"}}}, {"type": "range", "options": {"from": 201, "to": 999, "result": {"text": "ERROR HTTP", "color": "orange"}}}]
dashboards = {}

dashboards["00-multicloud-resumen.json"] = dash("nexo-resumen", "NexoEventos — observabilidad multicloud (resumen)", [
    text(1, 0, 0, 24, 4, "### Qué muestra este panel\n**En vivo** (Zabbix en Azure, independiente de AWS): sondas externas cada minuto sobre NexoEventos (`/healthz` = API + base de datos, `/api/events`, TLS) y los problemas activos. "
        "**Histórico** (otros paneles): series *reales* de AWS (CloudWatch y pruebas de carga) y OCI (OCI Monitoring) tomadas de solo lectura en las ventanas en que esos recursos estuvieron encendidos; "
        "se importan con su fecha original y **no** son monitoreo en vivo. AWS está apagado entre ventanas: «SIN RESPUESTA» fuera de ellas es el estado esperado y demuestra la detección."),
    stat(2, "Disponibilidad /healthz (en vivo)", 0, 4, 6, 5, [ztarget("aws-nexoeventos-v1", "/healthz: código HTTP/")], mappings=UPDOWN, thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 200}, {"color": "orange", "value": 201}]),
    stat(3, "Catálogo /api/events (en vivo)", 6, 4, 6, 5, [ztarget("aws-nexoeventos-v1", "/catálogo: código HTTP/")], mappings=UPDOWN, thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 200}, {"color": "orange", "value": 201}]),
    stat(4, "Latencia /healthz", 12, 4, 6, 5, [ztarget("aws-nexoeventos-v1", "/healthz: latencia total/")], unit="s", thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1.5}, {"color": "red", "value": 3}]),
    stat(5, "Certificado TLS: días hasta el vencimiento", 18, 4, 6, 5, [ztarget("aws-nexoeventos-v1", "/TLS: días hasta el vencimiento/")], unit="d", thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 7}, {"color": "green", "value": 14}]),
    ts(6, "Código HTTP de /healthz y /api/events (en vivo)", 0, 9, 12, 8, [ztarget("aws-nexoeventos-v1", "/healthz: código HTTP/", "A", "healthz"), ztarget("aws-nexoeventos-v1", "/catálogo: código HTTP/", "B", "/api/events")], desc="0 = sin respuesta"),
    ts(7, "Latencia de /healthz (en vivo)", 12, 9, 12, 8, [ztarget("aws-nexoeventos-v1", "/healthz: latencia total/", "A", "latencia")], unit="s"),
    problems(8, 0, 17, 24, 9),
], ["resumen", "en-vivo"], desc="Resumen de disponibilidad (en vivo) y problemas; enlaces a los paneles históricos y de Azure.")

H = lambda host, item, ref, legend: ztarget(host, item, ref, legend)
dashboards["10-aws-historico.json"] = dash("nexo-aws-hist", "AWS — histórico real (CloudWatch y pruebas de carga) — NO es monitoreo en vivo", [
    text(1, 0, 0, 24, 3, "**Datos históricos reales** de las ventanas en que V1/V2 estuvieron encendidos (octubre de 2026), leídos de CloudWatch y de `perf/results` y cargados con su marca de tiempo original. Ajuste el rango de tiempo a la fecha de cada ventana."),
    ts(2, "CPU de la instancia y de la base de datos (%)", 0, 3, 12, 8, [H("aws-historico", "/CPU de la instancia/", "A", "EC2"), H("aws-historico", "/CPU de la base de datos/", "B", "RDS")], unit="percent", mx=100),
    ts(3, "Conexiones a la base de datos", 12, 3, 12, 8, [H("aws-historico", "/Conexiones a la base de datos/", "A", "RDS conexiones")]),
    ts(4, "Balanceador: peticiones y errores 5xx", 0, 11, 8, 8, [H("aws-historico", "/Peticiones por intervalo/", "A", "peticiones"), H("aws-historico", "/Errores 5xx/", "B", "5xx")]),
    ts(5, "Latencia de destino del ALB (s)", 8, 11, 8, 8, [H("aws-historico", "/Latencia de destino ALB/", "A", "latencia ALB")], unit="s"),
    ts(9, "Auto Scaling: instancias en servicio", 16, 11, 8, 8, [H("aws-historico", "/Instancias en servicio/", "A", "instancias ASG")]),
    ts(6, "Pruebas de carga k6: latencia p95 (ms)", 0, 19, 8, 8, [H("aws-historico", "/Carga k6: latencia p95/", "A", "p95")], unit="ms"),
    ts(7, "Pruebas de carga k6: peticiones por segundo", 8, 19, 8, 8, [H("aws-historico", "/Carga k6: peticiones por segundo/", "A", "rps")], unit="reqps"),
    ts(10, "Failover Multi-AZ de la RDS: código HTTP de /healthz (23-oct-2026, sondeo de 1 s)", 0, 27, 24, 8, [H("aws-historico", "/Failover Multi-AZ: código HTTP/", "A", "healthz (0 = sin respuesta)")], desc="Interrupción medida ≈ 13 s; ver docs/evidencias/multicloud/aws/20261023-rds-multiaz/failover."),
    ts(8, "Pruebas de carga k6: errores inesperados por peldaño", 16, 19, 8, 8, [H("aws-historico", "/Carga k6: errores inesperados/", "A", "errores")]),
], ["aws", "historico"], time_from="now-30d", desc="Series reales importadas; no es monitoreo en vivo.")

dashboards["20-oci-historico.json"] = dash("nexo-oci-hist", "OCI — histórico real (OCI Monitoring) de la recuperación — NO es monitoreo en vivo", [
    text(1, 0, 0, 24, 3, "**Datos históricos reales** de OCI Monitoring de la VM temporal de recuperación (23-oct-2026) y del bucket privado de respaldos (cargas, descargas y verificaciones del 23-oct-2026). Las VM temporales ya fueron destruidas; el bucket sigue activo."),
    ts(2, "CPU y memoria de la VM de recuperación (%)", 0, 3, 12, 8, [H("oci-historico", "/CPU de la instancia/", "A", "CPU"), H("oci-historico", "/Memoria utilizada/", "B", "memoria")], unit="percent", mx=100),
    ts(3, "Red de la VM de recuperación (bytes)", 12, 3, 12, 8, [H("oci-historico", "/Red entrante/", "A", "entrante"), H("oci-historico", "/Red saliente/", "B", "saliente")], unit="bytes"),
    ts(4, "Bucket de respaldos: cargas, descargas y errores de cliente (5 min)", 0, 11, 12, 8, [H("oci-historico", "/PutRequests/", "A", "PutRequests"), H("oci-historico", "/GetRequests/", "B", "GetRequests"), H("oci-historico", "/ClientErrors/", "C", "ClientErrors")]),
    ts(5, "Bucket de respaldos: latencia al primer byte (ms)", 12, 11, 12, 8, [H("oci-historico", "/latencia al primer byte/", "A", "ms")], unit="ms"),
], ["oci", "historico"], time_from="now-30d", desc="Series reales importadas; no es monitoreo en vivo.")

sub = "{{ grafana_azure_subscription_id }}"
az = lambda metric, agg, ref: {"datasource": ADS, "queryType": "Azure Monitor", "subscription": sub, "azureMonitor": {"resources": [{"subscription": sub, "resourceGroup": "rg-nexoeventos-observabilidad", "metricNamespace": "microsoft.compute/virtualmachines", "resourceName": "vm-nexoeventos-obs"}],
    "metricNamespace": "microsoft.compute/virtualmachines", "metricName": metric, "aggregation": agg, "timeGrain": "auto", "dimensionFilters": []}, "refId": ref}
azure = dash("nexo-azure-vm", "Azure — VM de monitoreo (Azure Monitor y agente de Zabbix)", [
    text(1, 0, 0, 24, 3, "Métricas **de plataforma de Azure Monitor** (sin agente, con la identidad administrada de la VM) junto a las del **agente de Zabbix** de la propia VM (CPU, memoria, disco, PostgreSQL y salud de Zabbix)."),
    ts(2, "Azure Monitor: CPU de la VM (%)", 0, 3, 12, 8, [az("Percentage CPU", "Average", "A")], unit="percent", ds=ADS, mx=100),
    ts(3, "Azure Monitor: memoria disponible (bytes)", 12, 3, 12, 8, [az("Available Memory Bytes", "Minimum", "A")], unit="bytes", ds=ADS),
    ts(4, "Azure Monitor: red entrante y saliente (bytes)", 0, 11, 12, 8, [az("Network In Total", "Total", "A"), az("Network Out Total", "Total", "B")], unit="bytes", ds=ADS),
    ts(5, "Zabbix agente: CPU utilizada (%)", 12, 11, 12, 8, [ztarget("azure-obs", "/CPU utilization/", "A", "CPU")], unit="percent", mx=100),
    ts(6, "Zabbix agente: memoria disponible (%)", 0, 19, 12, 8, [ztarget("azure-obs", "/Available memory in %/", "A", "memoria disponible")], unit="percent", mx=100),
    ts(7, "Zabbix server: valores procesados por segundo", 12, 19, 12, 8, [ztarget("azure-obs", "/Zabbix server: Values processed per second|Values processed per second/", "A", "NVPS")]),
], ["azure"], desc="Autenticación de Azure Monitor con identidad administrada (rol Monitoring Reader en el grupo de recursos).")

for d_ in dashboards.values():                       # series históricas: sin unir huecos (la VM no existía entre ventanas) y con puntos visibles
    if "historico" in d_["tags"]:
        for p_ in d_["panels"]:
            if p_["type"] == "timeseries":
                p_["fieldConfig"]["defaults"]["custom"].update({"spanNulls": False, "showPoints": "always", "pointSize": 4})
out_files = ROOT / "files/grafana/dashboards"; out_tpl = ROOT / "templates"
out_files.mkdir(parents=True, exist_ok=True)
for name, d in dashboards.items():
    if name.startswith("30-") or d["uid"] == "nexo-azure-vm":
        (out_tpl / "grafana-30-azure.json.j2").write_text(json.dumps(d, indent=2, ensure_ascii=False).replace('"{{ grafana_azure_subscription_id }}"', '"{{ grafana_azure_subscription_id }}"') + "\n")
    else:
        (out_files / name).write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
(out_tpl / "grafana-30-azure.json.j2").write_text(json.dumps(azure, indent=2, ensure_ascii=False) + "\n")
print("generados:", sorted(dashboards))
