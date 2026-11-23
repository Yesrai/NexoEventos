#!/usr/bin/env python3
"""Exporta de SOLO LECTURA las métricas reales de CloudWatch de las ventanas en que AWS V1/V2 estuvieron encendidos, a un JSON para push-history.py.
No enciende ni modifica nada en AWS: necesita únicamente el laboratorio activo (credenciales temporales) y permisos cloudwatch:ListMetrics/GetMetricData.
Las métricas de 1 minuto se conservan ~15 días y después se agregan (5 min, luego 1 h): exportar pronto las ventanas del 19–22 de octubre. Las series que no existan se omiten y se informan.
Uso: export-cloudwatch.py [--profile nexoeventos-lab] [--window INICIO,FIN ...] [--period 60] [--out work/observability/aws-cloudwatch.json] [--dry-run] [--selftest]
Ventanas por defecto (evidencias existentes): V1 con carga 2026-10-19T00:00Z–2026-10-20T00:00Z; V2 (ALB + Auto Scaling) 2026-10-22T14:00Z–2026-10-22T23:00Z; RDS Multi-AZ y failover 2026-10-23T00:00Z–03:00Z."""
import argparse, datetime as dt, json, os, pathlib, subprocess, sys

ap = argparse.ArgumentParser(); ap.add_argument("--profile", default="nexoeventos-lab"); ap.add_argument("--region", default="us-east-1")
ap.add_argument("--window", action="append", help="INICIO,FIN en UTC (ISO)"); ap.add_argument("--period", type=int, default=60)
ap.add_argument("--out", default="work/observability/aws-cloudwatch.json"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--selftest", action="store_true"); a = ap.parse_args()
WINDOWS = a.window or ["2026-10-19T00:00:00Z,2026-10-20T00:00:00Z", "2026-10-22T14:00:00Z,2026-10-22T23:00:00Z", "2026-10-23T00:00:00Z,2026-10-23T03:00:00Z"]   # V1 con carga · V2 (ALB + Auto Scaling) · RDS Multi-AZ y failover
# (namespace, métrica, dimensión de descubrimiento, estadística, clave de Zabbix, escala)
WANT = [("AWS/EC2", "CPUUtilization", "InstanceId", "Average", "nexo.hist.cpu_pct", 1), ("AWS/EC2", "NetworkIn", "InstanceId", "Sum", "nexo.hist.net_in_bytes", 1), ("AWS/EC2", "NetworkOut", "InstanceId", "Sum", "nexo.hist.net_out_bytes", 1),
        ("AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", "Average", "nexo.hist.db_cpu_pct", 1), ("AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", "Maximum", "nexo.hist.db_connections", 1),
        ("AWS/ApplicationELB", "RequestCount", "LoadBalancer", "Sum", "nexo.hist.alb_requests", 1), ("AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", "Sum", "nexo.hist.alb_5xx", 1),
        ("AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", "Average", "nexo.hist.alb_target_time", 1), ("AWS/AutoScaling", "GroupInServiceInstances", "AutoScalingGroupName", "Average", "nexo.hist.asg_in_service", 1)]


def aws(*args):
    r = subprocess.run(["aws", "--profile", a.profile, "--region", a.region, *args, "--output", "json"], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"aws {' '.join(args[:2])}: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout or "{}")


def to_points(key, results, scale=1, stat="Average"):
    """GetMetricData → puntos (marca de tiempo original). Varias series (p. ej. varias instancias del Auto Scaling) se combinan por instante: suma para «Sum»,
    máximo para «Maximum» y media para el resto, para no generar valores duplicados en el mismo instante."""
    by = {}
    for res in results:
        for ts, v in zip(res.get("Timestamps", []), res.get("Values", [])):
            by.setdefault(int(dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()), []).append(v)
    agg = {"Sum": sum, "Maximum": max}.get(stat, lambda xs: sum(xs) / len(xs))
    return [{"host": "aws-historico", "key": key, "clock": c, "value": agg(vs) * scale} for c, vs in sorted(by.items())]


if a.selftest:
    s = to_points("nexo.hist.cpu_pct", [{"Timestamps": ["2026-10-19T10:00:00+00:00", "2026-10-19T10:01:00Z"], "Values": [12.5, 14.0]}, {"Timestamps": ["2026-10-19T10:00:00Z"], "Values": [17.5]}])
    assert [p["value"] for p in s] == [15.0, 14.0] and s[0]["clock"] == 1792404000, s   # media entre dos instancias en el mismo instante
    print("selftest OK (conversión de GetMetricData a puntos con marca de tiempo original)"); sys.exit(0)
if a.dry_run:
    for w in WINDOWS:
        print("ventana", w)
    for ns, m, dim, stat, key, _ in WANT:
        print(f"  {ns}/{m} ({dim}, {stat}, periodo {a.period}s) → {key}")
    sys.exit(0)
points, notes, series = [], [], []


def mask(v):
    """Identificador del recurso enmascarado (solo los 4 últimos caracteres): suficiente para distinguir series sin exponer identificadores."""
    return "…" + v[-4:] if len(v) > 6 else v


def observed_resolution(ts):
    d = sorted({b - a for a, b in zip(ts, ts[1:])})
    return d[0] if d else None


for w in WINDOWS:
    start, end = w.split(",")
    for ns, m, dim, stat, key, scale in WANT:
        ms = [x for x in aws("cloudwatch", "list-metrics", "--namespace", ns, "--metric-name", m).get("Metrics", []) if any(d["Name"] == dim for d in x["Dimensions"]) and len(x["Dimensions"]) == 1]
        if not ms:
            notes.append(f"{ns}/{m}: sin métricas (omitida)"); continue
        n = 0
        for i in range(0, len(ms), 50):
            chunk = ms[i:i + 50]
            q = [{"Id": f"m{j}", "MetricStat": {"Metric": x, "Period": a.period, "Stat": stat}, "ReturnData": True} for j, x in enumerate(chunk)]
            res = aws("cloudwatch", "get-metric-data", "--metric-data-queries", json.dumps(q), "--start-time", start, "--end-time", end, "--scan-by", "TimestampAscending").get("MetricDataResults", [])
            for r in res:   # DATOS ORIGINALES de CloudWatch, una serie por recurso, sin combinar ni interpolar
                x = chunk[int(r["Id"][1:])]; ts = [int(dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()) for t in r.get("Timestamps", [])]
                if ts:
                    series.append({"namespace": ns, "metric": m, "stat": stat, "dimension": dim, "resource": mask(next(d["Value"] for d in x["Dimensions"] if d["Name"] == dim)),
                                   "window": w, "requested_period_s": a.period, "observed_resolution_s": observed_resolution(ts), "n": len(ts), "points": [[t, v] for t, v in zip(ts, r.get("Values", []))]})
            pts = to_points(key, res, scale, stat); points += pts; n += len(pts)
        notes.append(f"{w} {ns}/{m}: {len(ms)} series, {n} puntos"); print(notes[-1])
out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"schema": 2, "source": "CloudWatch GetMetricData (solo lectura)", "exported_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "windows": WINDOWS, "notes": notes,
                           "series_original": series,
                           "points_derivados": {"nota": "DERIVADO: varias series del mismo instante combinadas (suma para Sum, máximo para Maximum, media para el resto) y escaladas, solo para cargarlas en Zabbix con push-history.py; no son datos originales",
                                                "points": points}}, indent=1)); os.chmod(out, 0o600)
print(f"{len(series)} series originales y {len(points)} puntos derivados → {out}")
