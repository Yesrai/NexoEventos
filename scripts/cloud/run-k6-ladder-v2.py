#!/usr/bin/env python3
"""Escalera k6 contra AWS V2 (ALB + 2 instancias) con el MISMO perfil mixto, niveles, duraciones y criterios de parada que V1 (run-k6-ladder.py).

Diferencias necesarias (documentadas en los resultados):
  - k6 usa el dominio autorizado resuelto a la IP del ALB (--resolve-ip); el origen del tráfico sigue siendo este Mac.
  - Se muestrea CPU/memoria en LAS DOS instancias (Session Manager) y se mide el reparto de solicitudes por instancia con el log de Nginx.
  - Los datos ficticios (fixture 90001-90004), la huella y la integridad usan la identidad migradora de la EC2 de V1, que debe estar ENCENDIDA
    temporalmente (las instancias de V2 no la tienen; no se copia ninguna credencial privilegiada a V2).
  - Las instancias de V2 son nuevas y en modo de créditos `unlimited`: el criterio «créditos de CPU» se evalúa sobre CPUSurplusCreditBalance
    (créditos excedentes facturables, límite 50) en lugar del saldo, que parte de cero y no limita la CPU.
Se detiene sin avanzar si p95 > 2 s, errores, CPU > 85 % (2 min) en cualquier instancia, memoria liberable de RDS < 80 MB, conexiones > 70,
créditos excedentes > 50, una instancia deja de estar sana o hay violación de integridad. Limpia solo el fixture y compara la huella.
Uso: NEXO_ALLOW_CLOUD_CHANGES=YES NEXO_LOAD_TEST_APPROVED=<run-id> python3 scripts/cloud/run-k6-ladder-v2.py --run-id <run-id> [--plan]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


L = load("ladder", "scripts/cloud/run-k6-ladder.py")
M = load("v2m", "scripts/cloud/v2-measure.py")
LEVELS = ["smoke", "10", "20", "40", "50"]
HOLD = {"smoke": 60, "10": 120, "20": 150, "40": 150, "50": 120}
VUS = {"smoke": 1, "10": 10, "20": 20, "40": 40, "50": 50}
SURPLUS_MAX = 50.0
TG_NAME, LB_NAME, ASG_NAME = M.TG_NAME, M.LB_NAME, M.ASG_NAME


def sampler_v2(seconds: int) -> str:
    n = int((seconds + 30) / 4.2) + 1
    return f"""set -u
for i in $(seq 1 {n}); do
  v=$(vmstat 4 2 | tail -1); ts=$(date +%s)
  busy=$(echo "$v" | awk '{{print 100-$15}}'); steal=$(echo "$v" | awk '{{print $17}}')
  mem=$(awk '/MemAvailable/{{print int($2/1024)}}' /proc/meminfo)
  api=$(ps -eo rss,args | awk '/uvicorn|multiprocessing/ && !/awk/ {{s+=$1}} END{{print int(s/1024)}}')
  ngx=$(ps -eo rss,comm | awk '$2=="nginx"{{s+=$1}} END{{print int(s/1024)}}')
  echo "S $ts $busy $steal $mem $api $ngx -1"
done
"""


def ssm_on(iid: str, script: str, comment: str) -> str:
    return L.aws("ssm", "send-command", "--instance-ids", iid, "--document-name", "AWS-RunShellScript", "--comment", comment, "--parameters",
                 json.dumps({"commands": [script]}), "--timeout-seconds", "900", "--query", "Command.CommandId", "--output", "text").strip()


def targets() -> dict[str, str]:
    return M.target_health()


def alb_ip() -> str:
    dns = subprocess.check_output(["terraform", "output", "-raw", "alb_dns_name"], cwd=ROOT / "infra" / "aws-v2", text=True).strip()
    return sorted({a[4][0] for a in socket.getaddrinfo(dns, 443, socket.AF_INET)})[0]


def cw_dims(namespace: str, metric: str, dims: list[tuple[str, str]], start, end, period: int, stat: str) -> list[float]:
    args = ["cloudwatch", "get-metric-statistics", "--namespace", namespace, "--metric-name", metric, "--dimensions", *[f"Name={k},Value={v}" for k, v in dims],
            "--start-time", start.strftime("%Y-%m-%dT%H:%M:%SZ"), "--end-time", end.strftime("%Y-%m-%dT%H:%M:%SZ"), "--period", str(period)]
    args += ["--extended-statistics", stat] if stat.startswith("p") else ["--statistics", stat]
    pts = sorted(json.loads(L.aws(*args, "--output", "json"))["Datapoints"], key=lambda d: d["Timestamp"])
    return [round(d["ExtendedStatistics"][stat] if stat.startswith("p") else d[stat], 3) for d in pts]


def metrics_v2(start: datetime, end: datetime) -> dict:
    lb = L.aws("elbv2", "describe-load-balancers", "--names", LB_NAME, "--query", "LoadBalancers[0].LoadBalancerArn", "--output", "text").strip().split("loadbalancer/")[1]
    tg = L.aws("elbv2", "describe-target-groups", "--names", TG_NAME, "--query", "TargetGroups[0].TargetGroupArn", "--output", "text").strip().split(":")[-1]
    alb = [("LoadBalancer", lb)]
    out = {"window_utc": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")],
           "alb": {"request_count": cw_dims("AWS/ApplicationELB", "RequestCount", alb, start, end, 60, "Sum"), "target_response_p95_s": cw_dims("AWS/ApplicationELB", "TargetResponseTime", alb, start, end, 60, "p95"),
                   "target_5xx": cw_dims("AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", alb, start, end, 60, "Sum"), "elb_5xx": cw_dims("AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", alb, start, end, 60, "Sum"),
                   "healthy_hosts_min": cw_dims("AWS/ApplicationELB", "HealthyHostCount", alb + [("TargetGroup", tg)], start, end, 60, "Minimum")}, "ec2": {}}
    for iid in targets():
        d = [("InstanceId", iid)]
        out["ec2"][iid[-6:]] = {"cpu_pct_5min_max": cw_dims("AWS/EC2", "CPUUtilization", d, start, end, 300, "Maximum"), "cpu_credit_balance": cw_dims("AWS/EC2", "CPUCreditBalance", d, start, end, 300, "Average"),
                                "cpu_surplus_credit_balance": cw_dims("AWS/EC2", "CPUSurplusCreditBalance", d, start, end, 300, "Maximum"), "network_out_mb": round(sum(cw_dims("AWS/EC2", "NetworkOut", d, start, end, 300, "Sum")) / 2**20, 1)}
    r = [("DBInstanceIdentifier", "nexoeventos-academy-postgres")]
    out["rds"] = {"cpu_pct_1min_max": cw_dims("AWS/RDS", "CPUUtilization", r, start, end, 60, "Maximum"), "connections_max": cw_dims("AWS/RDS", "DatabaseConnections", r, start, end, 60, "Maximum"),
                  "freeable_memory_mb_min": [round(v / 2**20, 1) for v in cw_dims("AWS/RDS", "FreeableMemory", r, start, end, 60, "Minimum")], "write_iops_max": cw_dims("AWS/RDS", "WriteIOPS", r, start, end, 60, "Maximum"),
                  "cpu_credit_balance_min": cw_dims("AWS/RDS", "CPUCreditBalance", r, start, end, 60, "Minimum")}
    return out


def recent(minutes: int = 12) -> dict:
    end = datetime.now(timezone.utc)
    return metrics_v2(end - timedelta(minutes=minutes), end)


def run_level(base: str, index: int, step: str, ip: str) -> dict:
    run_id = f"{base}{index}"
    est = 30 + HOLD[step] + 5 + 10 + int(VUS[step] * 0.6) + 15
    inst = sorted(targets())
    samplers = {i: ssm_on(i, sampler_v2(est), f"k6 v2 {step}: muestreo") for i in inst}
    t0 = time.time()
    stop, found = threading.Event(), {}
    threading.Thread(target=L.watchdog, args=(f"k6-{run_id}-mix", stop, found), daemon=True).start()
    proc = subprocess.run([L.PY, str(ROOT / "perf" / "run_cloud.py"), "--base-url", L.BASE, "--run-id", run_id, "--step", step, "--scenarios", "mix", "--label", f"aws-v2-{base}/nivel-{step}", "--resolve-ip", ip],
                          env={**os.environ, "NEXO_LOAD_TEST_APPROVED": run_id}, capture_output=True, text=True)
    t1 = time.time()
    stop.set()
    per, dist = {}, {}
    window = (datetime.fromtimestamp(t0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), datetime.fromtimestamp(t1 + 3, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    for i, cid in samplers.items():
        samples = L.parse_samples(L.ssm_wait(cid, i, 300))
        per[i[-6:]] = L.cpu_stats(samples, t0, t1)
        dist[i[-6:]] = M.count_requests(M.ssm_output(i, "cat /var/log/nginx/nexoeventos-access.log"), *window)
    total = sum(v["requests"] for v in dist.values()) or 1
    return {"label": f"nivel-{step}", "step": step, "run_id": run_id, "rc": proc.returncode, "stdout_tail": proc.stdout.strip().splitlines()[-6:], "stderr_tail": proc.stderr[-400:], "elapsed_s": round(t1 - t0, 1),
            "instances": per, "distribution": dist, "share_pct": {k: round(100 * v["requests"] / total) for k, v in dist.items()}, "watchdog": found}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--levels", default=",".join(LEVELS))
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()
    base = args.run_id
    levels = [x for x in args.levels.split(",") if x]
    if not re.fullmatch(r"[a-z0-9]{3,8}", base) or any(x not in LEVELS for x in levels):
        sys.exit("--run-id: 3-8 caracteres alfanuméricos en minúsculas; --levels entre " + ",".join(LEVELS))
    print(f"Plan V2: {', '.join(levels)} (perfil mixto) · destino {L.BASE} vía ALB · máx. {L.MAX_TOTAL_SECONDS // 60} min · 50 usuarios como máximo")
    if args.plan:
        return
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES" or os.environ.get("NEXO_LOAD_TEST_APPROVED") != base:
        sys.exit("Requiere NEXO_ALLOW_CLOUD_CHANGES=YES y NEXO_LOAD_TEST_APPROVED igual al --run-id.")
    out = ROOT / "perf" / "results" / f"aws-v2-{base}"
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"schema": 1, "run": base, "target": "AWS V2 (ALB + 2 EC2 en 2 zonas)", "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "levels": [], "stopped_reason": None}
    t_start, created = time.time(), False
    try:
        health = targets()
        assert len(health) == 2 and all(s == "healthy" for s in health.values()), f"V2 no tiene 2 instancias sanas: {health}"
        ip = alb_ip()
        pre = L.sql("SELECT 'fixture_events='||count(*) FROM events WHERE id BETWEEN 90001 AND 90099; SELECT 'k6_users='||count(*) FROM users WHERE email LIKE 'k6-%@example.com';", "k6 v2: precheck (lectura)")
        assert "fixture_events=0" in pre and "k6_users=0" in pre, f"fixture no libre: {pre}"
        before = L.sql(L.FINGERPRINT, "k6 v2: huella previa (lectura)")
        report["fingerprint_before"] = before.split("\n")
        report["baseline_metrics"] = recent(15)
        report["environment"] = {"asg": ASG_NAME, "instances": len(health), "instance_type": "t3.small x2 (modo unlimited)", "rds": "db.t3.micro", "generator": "Mac del autor vía Internet; k6 2.3.0 en Docker; dominio resuelto a la IP del ALB"}
        created = True
        L.sql(subprocess.check_output([L.PY, str(ROOT / "perf" / "cloud_fixture.py"), "up"], text=True), "k6 v2: crear fixture")
        print("Fixture creado (ocultos 90001-90004).", flush=True)
        for i, step in enumerate(levels):
            if time.time() - t_start > L.MAX_TOTAL_SECONDS:
                report["stopped_reason"] = "límite de tiempo de la escalera"; break
            print(f"▶ nivel-{step} …", flush=True)
            lv = run_level(base, i, step, ip)
            lv["integrity"] = L.integrity()
            rec = recent(15)
            surplus = max([(v["cpu_surplus_credit_balance"] or [0])[-1] for v in rec["ec2"].values()] or [0])
            health_now = targets()
            reasons = []
            if lv["rc"] != 0: reasons.append(f"k6 terminó con error o umbral/abort (rc={lv['rc']})")
            if lv["integrity"].get("total_violations") != 0: reasons.append(f"integridad: {lv['integrity'].get('total_violations')}")
            if any(v.get("samples", 0) == 0 for v in lv["instances"].values()) or len(lv["instances"]) < 2: reasons.append("sin muestras de CPU en alguna instancia")
            if max((v.get("cpu_2min_max_avg_pct", 0) for v in lv["instances"].values()), default=0) > L.CPU_LIMIT: reasons.append("CPU > 85 % en 2 min en una instancia")
            if any(v.get("mem_avail_min_mb", 1e9) < 300 for v in lv["instances"].values()): reasons.append("memoria disponible < 300 MB en una instancia")
            if surplus > SURPLUS_MAX: reasons.append(f"créditos excedentes {surplus} > {SURPLUS_MAX}")
            if lv["watchdog"].get("tripped"): reasons.append(lv["watchdog"]["tripped"])
            if (rec["rds"]["connections_max"] or [0])[-1] > L.CONNS_MAX: reasons.append("conexiones a PostgreSQL > 70")
            if (rec["rds"]["cpu_pct_1min_max"] or [0])[-1] > L.RDS_CPU_MAX: reasons.append("RDS CPU alta")
            if (rec["rds"]["freeable_memory_mb_min"] or [1e9])[-1] < L.RDS_FREE_MIN_MB: reasons.append("RDS memoria liberable baja")
            if len(health_now) != 2 or any(s != "healthy" for s in health_now.values()): reasons.append(f"instancia no sana: {list(health_now.values())}")
            lv["surplus_credits_latest"], lv["rds_recent"] = surplus, {k: (v[-1] if v else None) for k, v in rec["rds"].items()}
            lv["ok"], lv["stop_reasons"] = not reasons, reasons
            report["levels"].append(lv)
            (out / f"nivel-{step}.json").write_text(json.dumps(lv, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print("   " + (" | ".join(lv["stdout_tail"][-3:-1]) if lv["stdout_tail"] else ""), flush=True)
            print(f"   reparto {lv['share_pct']} · CPU máx 2 min {[v.get('cpu_2min_max_avg_pct') for v in lv['instances'].values()]} % · mem libre mín {[v.get('mem_avail_min_mb') for v in lv['instances'].values()]} MB · excedentes {surplus} · integridad {lv['integrity'].get('total_violations')} → {'OK' if lv['ok'] else 'PARADA: ' + '; '.join(reasons)}", flush=True)
            if not lv["ok"]:
                report["stopped_reason"] = f"nivel-{step}: " + "; ".join(reasons); break
    except BaseException as error:  # noqa: BLE001
        report["stopped_reason"] = f"error del orquestador: {type(error).__name__}: {str(error)[:300]}"
        print(report["stopped_reason"], file=sys.stderr)
    finally:
        try:
            if created:
                L.sql(subprocess.check_output([L.PY, str(ROOT / "perf" / "cloud_fixture.py"), "down"], text=True), "k6 v2: limpiar fixture (solo 90001-90099 y k6-*)")
                left = L.sql("SELECT 'fixture_events='||count(*) FROM events WHERE id BETWEEN 90001 AND 90099; SELECT 'k6_users='||count(*) FROM users WHERE email LIKE 'k6-%@example.com';", "k6 v2: restos (lectura)").split()
                after = L.sql(L.FINGERPRINT, "k6 v2: huella posterior (lectura)")
                report["cleanup"] = {"leftovers": left, "complete": left == ["fixture_events=0", "k6_users=0"]}
                report["fingerprint_after"], report["fingerprint_identical"] = after.split("\n"), after.split("\n") == report.get("fingerprint_before")
                print(f"Limpieza: {report['cleanup']} · huella idéntica: {report['fingerprint_identical']}", flush=True)
        except BaseException as error:  # noqa: BLE001
            report["cleanup"] = {"error": f"{type(error).__name__}: {str(error)[:300]}"}
            print("ERROR DE LIMPIEZA (no se hacen más borrados):", report["cleanup"], file=sys.stderr)
        report["ended_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        report["elapsed_s"] = round(time.time() - t_start, 1)
        try:
            time.sleep(150)
            report["cloudwatch"] = metrics_v2(datetime.fromisoformat(report["started_utc"]) - timedelta(minutes=2), datetime.now(timezone.utc))
        except BaseException as error:  # noqa: BLE001
            report["cloudwatch"] = {"error": str(error)[:200]}
        (out / "baseline.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Resultados en perf/results/aws-v2-{base}/ · detenida por: {report['stopped_reason'] or 'ninguna (escalera completa)'}")
        sys.exit(0 if report["stopped_reason"] is None and report.get("cleanup", {}).get("complete") and report.get("fingerprint_identical") else 1)


if __name__ == "__main__":
    main()
