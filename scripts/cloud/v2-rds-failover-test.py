#!/usr/bin/env python3
"""Failover Multi-AZ de la RDS con AWS V2 (ALB + ASG, health check `/livez`). Hipótesis: la caída de ~15–30 s de PostgreSQL NO marca las instancias como
no sanas (el ALB usa `/livez`, sin base de datos) y el ASG NO lanza ni termina instancias; las peticiones que necesitan la base devuelven 503 con
`Retry-After` (o fallan una a una) y se recuperan solas. Solo lecturas (`/api/events`, `/healthz`, `/livez`); sin datos ni fixtures.
Provoca `reboot-db-instance --force-failover` y exige NEXO_ALLOW_CLOUD_CHANGES=YES y --i-am-authorized. No toca Terraform.
Criterios de parada: el ALB sin destinos sanos más de 90 s, tiempo máximo (--max-seconds) o RDS no `available` pasada la ventana. No reinicia nada más.
Uso: python3 scripts/cloud/v2-rds-failover-test.py --out docs/evidencias/AAAAMMDD-d2-failover-v2 --i-am-authorized
"""
import argparse
import importlib.util
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = "nexoeventos-demo.duckdns.org"
RDS_ID = "nexoeventos-academy-postgres"
PATHS = ["/api/events", "/healthz", "/livez"]


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load("v2m", "scripts/cloud/v2-measure.py")
V = load("chaos_validate", "scripts/cloud/validate-chaos-result.py")
T0 = time.time()
now = lambda: round(time.time() - T0, 1)  # noqa: E731


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rds_state() -> dict:
    d = M.aws("rds", "describe-db-instances", "--db-instance-identifier", RDS_ID)["DBInstances"][0]
    return {"status": d["DBInstanceStatus"], "az": d.get("AvailabilityZone"), "secondary_az": d.get("SecondaryAvailabilityZone")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--rate", type=float, default=6.0)
    ap.add_argument("--clients", type=int, default=4)
    ap.add_argument("--max-seconds", type=int, default=480)
    ap.add_argument("--i-am-authorized", action="store_true")
    args = ap.parse_args()
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES" or not args.i_am_authorized:
        sys.exit("Bloqueado: requiere NEXO_ALLOW_CLOUD_CHANGES=YES y --i-am-authorized.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    health0 = M.target_health()
    assert len(health0) == 2 and all(s == "healthy" for s in health0.values()), f"V2 no tiene 2 destinos sanos: {health0}"
    pre = rds_state()
    assert pre["status"] == "available" and pre["secondary_az"], f"RDS no está available y Multi-AZ: {pre['status']}"
    act0 = {a["ActivityId"] for a in M.aws("autoscaling", "describe-scaling-activities", "--auto-scaling-group-name", M.ASG_NAME, "--max-items", "20").get("Activities", [])}
    alb = subprocess.check_output(["terraform", "output", "-raw", "alb_dns_name"], cwd=ROOT / "infra" / "aws-v2", text=True).strip()
    ip = sorted({a[4][0] for a in socket.getaddrinfo(alb, 443, socket.AF_INET)})[0]
    real = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **k: real(ip if host == DOMAIN else host, *a, **k)

    stop = threading.Event()
    state = {"no_healthy_since": None, "abort": None}
    log: list[dict] = []
    timeline: list[dict] = []

    def traffic(worker: int) -> None:
        rng = random.Random(2000 + worker)
        per_worker = args.rate / args.clients
        stop.wait(rng.uniform(0, 1 / per_worker))
        while not stop.is_set():
            path = rng.choice(PATHS)
            t = time.time()
            retry_after = None
            try:
                with httpx.Client(headers={"Connection": "close"}, timeout=15) as c:
                    r = c.get(f"https://{DOMAIN}{path}")
                    code, retry_after = r.status_code, r.headers.get("retry-after")
            except httpx.HTTPError as exc:
                code = -1
                retry_after = type(exc).__name__
            log.append({"t": round(t - T0, 2), "path": path, "status": code, "ms": round((time.time() - t) * 1000), "retry_after": retry_after, "client": worker})
            stop.wait(max(0.0, 1 / per_worker - (time.time() - t)))

    def poll() -> None:
        last = None
        while not stop.is_set():
            try:
                health = M.target_health()
                asg = M.aws("autoscaling", "describe-auto-scaling-groups", "--auto-scaling-group-names", M.ASG_NAME)["AutoScalingGroups"][0]
                snap = {"alb": {k[-6:]: v for k, v in health.items()}, "asg": {i["InstanceId"][-6:]: [i["LifecycleState"], i["HealthStatus"]] for i in asg["Instances"]},
                        "rds": rds_state()}
                key = json.dumps(snap, sort_keys=True)
                if key != last:
                    timeline.append({"t": now(), **snap})
                    last = key
                if not any(s == "healthy" for s in health.values()):
                    state["no_healthy_since"] = state["no_healthy_since"] or time.time()
                    if time.time() - state["no_healthy_since"] > 90:
                        state["abort"] = "el ALB estuvo sin destinos sanos más de 90 s"
                else:
                    state["no_healthy_since"] = None
                if now() > args.max_seconds:
                    state["abort"] = f"tiempo máximo excedido ({args.max_seconds} s)"
            except Exception as exc:  # noqa: BLE001
                timeline.append({"t": now(), "error": type(exc).__name__})
            time.sleep(1)

    threads = [threading.Thread(target=traffic, args=(w,)) for w in range(args.clients)] + [threading.Thread(target=poll)]
    [t.start() for t in threads]
    events: dict = {"rds_before": pre, "rate_req_per_s": args.rate, "max_seconds": args.max_seconds}
    try:
        time.sleep(20)  # línea base
        events["failover_issued_at"] = now()
        r = subprocess.run(["aws", "rds", "reboot-db-instance", "--db-instance-identifier", RDS_ID, "--force-failover", "--query", "DBInstance.DBInstanceStatus", "--output", "text"],
                           capture_output=True, text=True)
        events["reboot_result"] = (r.stdout.strip() or r.stderr.strip()[-120:])
        deadline = time.time() + args.max_seconds
        az_changed_at = available_at = None
        while time.time() < deadline and not state["abort"]:
            s = rds_state()
            if s["status"] != "available":
                available_at = None
            if s["az"] != pre["az"] and az_changed_at is None:
                az_changed_at = now()
            if s["status"] == "available" and s["az"] != pre["az"]:
                available_at = available_at or now()
                if now() - available_at >= 30:
                    break
            time.sleep(2)
        events.update({"primary_az_changed_at": az_changed_at, "available_again_at": available_at, "abort_reason": state["abort"]})
    finally:
        time.sleep(10)
        stop.set()
        [t.join() for t in threads]
    end = time.time()
    events["rds_after"] = rds_state()
    errors = [r for r in log if r["status"] != 200]
    by_path = {p: {"requests": sum(1 for r in log if r["path"] == p), "non_200": sum(1 for r in errors if r["path"] == p),
                   "statuses": {str(s): sum(1 for r in errors if r["path"] == p and r["status"] == s) for s in sorted({r["status"] for r in errors if r["path"] == p})},
                   "first_non200_at": next((r["t"] for r in errors if r["path"] == p), None), "last_non200_at": next((r["t"] for r in reversed(errors) if r["path"] == p), None),
                   "with_retry_after_5xx": sum(1 for r in errors if r["path"] == p and r["status"] == 503 and r["retry_after"])} for p in PATHS}
    summary = {"requests": len(log), "non_200": len(errors), "by_path": by_path}
    summary.update(V.split_availability(log))
    act_new = [a for a in M.aws("autoscaling", "describe-scaling-activities", "--auto-scaling-group-name", M.ASG_NAME, "--max-items", "20").get("Activities", []) if a["ActivityId"] not in act0]
    final = {"alb": M.target_health(), "asg_activities_new": [a["Description"] for a in act_new]}
    health_changes = [x for x in timeline if "alb" in x and any(v != "healthy" for v in x["alb"].values())]
    result = {"schema": 1, "hypothesis": "con /livez, un failover de RDS no marca instancias no sanas ni provoca actividades del ASG",
              "events": events, "client": summary, "target_not_healthy_snapshots": health_changes, "timeline": timeline, "final": final,
              "duration_s": round(end - T0, 1), "started_at": iso(T0)}
    (out / "resultado.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "solicitudes.json").write_text(json.dumps(log) + "\n", encoding="utf-8")
    print(json.dumps({"events": events, "client": {k: v for k, v in summary.items() if k != "by_path"}, "by_path": by_path,
                      "destinos_no_sanos_en_algun_momento": len(health_changes), "actividades_asg_nuevas": final["asg_activities_new"]}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
