#!/usr/bin/env python3
"""Medición de AWS V2 (ALB + Auto Scaling): estado, métricas, reparto de carga entre instancias y caída de una instancia.

NO se ejecuta sin autorización: todas las órdenes hablan con AWS. `state`, `metrics` y `distribution` son de solo lectura; `failover` detiene
la API de UNA instancia por Session Manager (reversible) y la vuelve a arrancar al terminar. Las funciones puras (conteo de solicitudes por
instancia y transiciones de salud) se prueban en local con scripts/v2/test_measure.py.
Uso:
  v2-measure.py state
  v2-measure.py metrics --start 2026-10-20T15:00:00Z --end 2026-10-20T15:30:00Z
  v2-measure.py distribution --start ... --end ...        (cuenta solicitudes /api/ por instancia a partir del log de Nginx)
  v2-measure.py failover --instance-id i-... [--hold 90]    (con carga k6 de 20 usuarios en marcha)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

ASG_NAME = "nexoeventos-academy-v2-asg"
TG_NAME = "nexoeventos-academy-v2-tg"
LB_NAME = "nexoeventos-academy-v2-alb"


def aws(*args: str) -> dict | list | str:
    out = subprocess.check_output(["aws", *args, "--output", "json"], text=True)
    return json.loads(out) if out.strip() else {}


# ---------------------------------------------------------------- funciones puras (probadas en local) ----------------------------------------
LOG = re.compile(r'"?(?P<ts>\d{4}-\d\d-\d\dT[\d:]+[+-]\d\d:\d\d|\d{4}-\d\d-\d\dT[\d:]+Z).*?path=(?P<path>\S+) status=(?P<status>\d+)')


def count_requests(log_text: str, start: str, end: str, prefix: str = "/api/") -> dict:
    """Solicitudes (y errores 5xx) cuyo sello de tiempo cae en [start, end) y cuya ruta empieza por `prefix`."""
    s, e = datetime.fromisoformat(start.replace("Z", "+00:00")), datetime.fromisoformat(end.replace("Z", "+00:00"))
    total = errors = 0
    for line in log_text.splitlines():
        m = LOG.search(line)
        if not m:
            continue
        when = datetime.fromisoformat(m["ts"].replace("Z", "+00:00"))
        if s <= when < e and m["path"].startswith(prefix):
            total += 1
            errors += m["status"].startswith("5")
    return {"requests": total, "errors_5xx": errors}


def health_transitions(samples: list[tuple[float, dict[str, str]]]) -> list[dict]:
    """De una serie (t, {instancia: estado}) devuelve los cambios de estado con su instante relativo al primer sondeo."""
    t0, last, out = samples[0][0], {}, []
    for t, states in samples:
        for instance, state in states.items():
            if last.get(instance) != state:
                out.append({"t_s": round(t - t0, 1), "instance": instance, "from": last.get(instance), "to": state})
                last[instance] = state
    return out


def failover_summary(transitions: list[dict], stopped_at_s: float, restored_at_s: float | None) -> dict:
    """Tiempo hasta que el ALB marca la instancia como no sana y hasta que vuelve a estar sana."""
    down = next((x for x in transitions if x["to"] in ("unhealthy", "draining", "unused") and x["t_s"] >= stopped_at_s), None)
    up = next((x for x in transitions if x["to"] == "healthy" and restored_at_s is not None and x["t_s"] >= restored_at_s), None)
    return {"detected_after_s": round(down["t_s"] - stopped_at_s, 1) if down else None, "recovered_after_s": round(up["t_s"] - restored_at_s, 1) if up and restored_at_s is not None else None}


# ----------------------------------------------------------------------------- órdenes ------------------------------------------------------
def target_health() -> dict[str, str]:
    tg = aws("elbv2", "describe-target-groups", "--names", TG_NAME)["TargetGroups"][0]["TargetGroupArn"]
    return {d["Target"]["Id"]: d["TargetHealth"]["State"] for d in aws("elbv2", "describe-target-health", "--target-group-arn", tg)["TargetHealthDescriptions"]}


def cmd_state(_: argparse.Namespace) -> None:
    asg = aws("autoscaling", "describe-auto-scaling-groups", "--auto-scaling-group-names", ASG_NAME)["AutoScalingGroups"][0]
    health = target_health()
    print(f"ASG {asg['MinSize']}-{asg['MaxSize']} deseado {asg['DesiredCapacity']}")
    for i in asg["Instances"]:
        print(f"  {i['InstanceId'][-6:]} {i['AvailabilityZone']} {i['LifecycleState']} asg={i['HealthStatus']} alb={health.get(i['InstanceId'], '-')}")


def cmd_metrics(a: argparse.Namespace) -> None:
    lb = aws("elbv2", "describe-load-balancers", "--names", LB_NAME)["LoadBalancers"][0]["LoadBalancerArn"].split("loadbalancer/")[1]
    tg = aws("elbv2", "describe-target-groups", "--names", TG_NAME)["TargetGroups"][0]["TargetGroupArn"].split(":")[-1]
    def stat(ns, metric, dims, statistic, period=60):
        pts = aws("cloudwatch", "get-metric-statistics", "--namespace", ns, "--metric-name", metric, "--dimensions", *[f"Name={k},Value={v}" for k, v in dims],
                  "--start-time", a.start, "--end-time", a.end, "--period", str(period), "--statistics" if not statistic.startswith("p") else "--extended-statistics", statistic)["Datapoints"]
        return [round(p.get(statistic, p.get("ExtendedStatistics", {}).get(statistic, 0)), 3) for p in sorted(pts, key=lambda p: p["Timestamp"])]
    alb = [("LoadBalancer", lb)]
    result = {"alb_request_count": stat("AWS/ApplicationELB", "RequestCount", alb, "Sum"), "alb_target_response_p95_s": stat("AWS/ApplicationELB", "TargetResponseTime", alb, "p95"),
              "alb_target_5xx": stat("AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", alb, "Sum"), "healthy_hosts_min": stat("AWS/ApplicationELB", "HealthyHostCount", alb + [("TargetGroup", tg)], "Minimum"),
              "asg_in_service": stat("AWS/AutoScaling", "GroupInServiceInstances", [("AutoScalingGroupName", ASG_NAME)], "Average"), "asg_cpu_avg_pct": stat("AWS/EC2", "CPUUtilization", [("AutoScalingGroupName", ASG_NAME)], "Average"),
              "rds_connections_max": stat("AWS/RDS", "DatabaseConnections", [("DBInstanceIdentifier", "nexoeventos-academy-postgres")], "Maximum")}
    print(json.dumps(result, indent=1))


def ssm_output(instance: str, script: str) -> str:
    cid = aws("ssm", "send-command", "--instance-ids", instance, "--document-name", "AWS-RunShellScript", "--parameters", json.dumps({"commands": [script]}))["Command"]["CommandId"]
    for _ in range(60):
        time.sleep(2)
        r = subprocess.run(["aws", "ssm", "get-command-invocation", "--command-id", cid, "--instance-id", instance, "--output", "json"], capture_output=True, text=True)
        if r.returncode == 0 and json.loads(r.stdout)["Status"] not in ("Pending", "InProgress", "Delayed"):
            return json.loads(r.stdout)["StandardOutputContent"]
    raise RuntimeError("SSM timeout")


def cmd_distribution(a: argparse.Namespace) -> None:
    result = {}
    for instance in target_health():
        log = ssm_output(instance, "cat /var/log/nginx/nexoeventos-access.log")
        result[instance] = count_requests(log, a.start, a.end)
    total = sum(v["requests"] for v in result.values()) or 1
    for instance, v in result.items():
        print(f"{instance[-6:]}: {v['requests']} solicitudes ({100 * v['requests'] / total:.0f} %), 5xx {v['errors_5xx']}")


def cmd_failover(a: argparse.Namespace) -> None:
    samples: list[tuple[float, dict[str, str]]] = []
    stop_flag = {"stop": False}
    def poll(until: float) -> None:
        while time.time() < until:
            samples.append((time.time(), target_health()))
            time.sleep(2)
    t0 = time.time()
    poll(t0 + 20)  # línea base sana
    stopped = time.time() - t0
    ssm_output(a.instance_id, "systemctl stop nexoeventos-api")
    poll(time.time() + a.hold)
    restored = time.time() - t0
    ssm_output(a.instance_id, "systemctl start nexoeventos-api")
    poll(time.time() + 60)
    tr = health_transitions([(t - 0, s) for t, s in samples])
    for x in tr:
        x["t_s"] = round(x["t_s"], 1)
    print(json.dumps({"transitions": tr, "summary": failover_summary(tr, stopped, restored), "note": "Cuente los 5xx y la latencia de k6 en la misma ventana"}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("state").set_defaults(fn=cmd_state)
    for name, fn in (("metrics", cmd_metrics), ("distribution", cmd_distribution)):
        p = sub.add_parser(name); p.add_argument("--start", required=True); p.add_argument("--end", required=True); p.set_defaults(fn=fn)
    p = sub.add_parser("failover"); p.add_argument("--instance-id", required=True); p.add_argument("--hold", type=int, default=90); p.set_defaults(fn=cmd_failover)
    args = ap.parse_args()
    args.fn(args)
