#!/usr/bin/env python3
"""Ventana CONTROLADA de medición de AWS V1 con k6: escalera 1/10/20/40/50 usuarios + disputa de asiento, con datos aislados.

Solo se ejecuta con autorización explícita: NEXO_ALLOW_CLOUD_CHANGES=YES (crea/borra el fixture) y NEXO_LOAD_TEST_APPROVED=<run-id>.
Cada peldaño usa perf/run_cloud.py (≤ 4 min, ≤ 50 usuarios). Entre peldaños se evalúan criterios de parada y no se avanza si falla algo:
  p95 > 2 s sostenido, errores inesperados, CPU de la EC2 > 85 % durante 2 min (muestreo en la instancia cada ~4 s), créditos de CPU < 100,
  conexiones a PostgreSQL > 70 de 81, RDS CPU > 85 % o memoria liberable < 80 MB, o cualquier violación de integridad.
Siempre limpia SOLO el fixture (eventos 90001-90099 y usuarios k6-*) y compara la huella de la base antes y después. No repite nada solo.
Uso: NEXO_ALLOW_CLOUD_CHANGES=YES NEXO_LOAD_TEST_APPROVED=<run-id> python3 scripts/cloud/run-k6-ladder.py --run-id <run-id> [--plan]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://nexoeventos-demo.duckdns.org"
PY = sys.executable
LEVELS = ["smoke", "10", "20", "40", "50"]
MAX_TOTAL_SECONDS = 28 * 60
CPU_LIMIT, CPU_WINDOW_S = 85.0, 120
CREDITS_MIN, CONNS_MAX, RDS_CPU_MAX, RDS_FREE_MIN_MB = 100.0, 70, 85.0, 80.0

FINGERPRINT = """
SELECT 'alembic='||version_num FROM alembic_version;
SELECT 'reservations='||count(*)||':'||md5(coalesce(string_agg(id::text, ',' ORDER BY id::text),'')) FROM reservations;
SELECT 'tickets='||count(*)||' usados='||count(used_at) FROM tickets;
SELECT 'users='||count(*)||':'||md5(coalesce(string_agg(id::text, ',' ORDER BY id::text),'')) FROM users;
SELECT 'access_logs='||count(*) FROM access_logs;
SELECT 'events='||count(*)||':'||md5(coalesce(string_agg(id||':'||capacity||':'||reserved_count||':'||status||':'||event_date, ',' ORDER BY id),'')) FROM events;
SELECT 'event_seats='||count(*)||' ocupados='||count(reservation_id) FROM event_seats;
SELECT 'zonas_reservadas='||coalesce(sum(reserved_count),0) FROM event_zones;
SELECT 'queue_entries='||count(*) FROM queue_entries;
"""
MIG = 'set -euo pipefail; set -a; . /etc/nexoeventos/migration.env; set +a; DB_URL=${MIGRATION_DATABASE_URL/postgresql+psycopg:/postgresql:}\n'


def aws(*args: str) -> str:
    return subprocess.check_output(["aws", *args], text=True)


def instance_id() -> str:
    return aws("ec2", "describe-instances", "--filters", "Name=tag:Name,Values=nexoeventos-academy-app", "Name=instance-state-name,Values=running", "--query", "Reservations[0].Instances[0].InstanceId", "--output", "text").strip()


def ssm_start(script: str, comment: str) -> tuple[str, str]:
    iid = instance_id()
    cid = aws("ssm", "send-command", "--instance-ids", iid, "--document-name", "AWS-RunShellScript", "--comment", comment, "--parameters", json.dumps({"commands": [script]}), "--timeout-seconds", "900", "--query", "Command.CommandId", "--output", "text").strip()
    return cid, iid


def ssm_wait(cid: str, iid: str, limit: int = 600) -> str:
    for _ in range(limit // 3):
        time.sleep(3)
        r = subprocess.run(["aws", "ssm", "get-command-invocation", "--command-id", cid, "--instance-id", iid, "--output", "json"], capture_output=True, text=True)
        if r.returncode:
            continue
        d = json.loads(r.stdout)
        if d["Status"] not in ("Pending", "InProgress", "Delayed"):
            if d["Status"] != "Success":
                raise RuntimeError(f"SSM {d['Status']}: {d['StandardErrorContent'][-300:]}")
            return d["StandardOutputContent"]
    raise RuntimeError("SSM timeout")


def ssm_run(script: str, comment: str) -> str:
    return ssm_wait(*ssm_start(script, comment))


def sql(query: str, comment: str) -> str:
    return ssm_run(MIG + 'psql "$DB_URL" -v ON_ERROR_STOP=1 -At <<\'SQL\'\n' + query + "\nSQL\n", comment)


def sampler_script(seconds: int) -> str:
    n = int((seconds + 30) / 4.2) + 1
    return MIG.replace("set -euo pipefail", "set -u") + f"""for i in $(seq 1 {n}); do
  v=$(vmstat 4 2 | tail -1); ts=$(date +%s)
  busy=$(echo "$v" | awk '{{print 100-$15}}'); steal=$(echo "$v" | awk '{{print $17}}')
  mem=$(awk '/MemAvailable/{{print int($2/1024)}}' /proc/meminfo)
  api=$(ps -eo rss,args | awk '/uvicorn|multiprocessing/ && !/awk/ {{s+=$1}} END{{print int(s/1024)}}')
  ngx=$(ps -eo rss,comm | awk '$2=="nginx"{{s+=$1}} END{{print int(s/1024)}}')
  conns=$(timeout 3 psql "$DB_URL" -Atc "select count(*) from pg_stat_activity where datname=current_database()" 2>/dev/null || echo -1)
  echo "S $ts $busy $steal $mem $api $ngx $conns"
done
"""


def parse_samples(output: str) -> list[dict]:
    rows = []
    for line in output.splitlines():
        m = re.fullmatch(r"S (\d+) (-?[\d.]+) ([\d.]+) (\d+) (\d+) (\d+) (-?\d+)", line.strip())
        if m:
            ts, busy, steal, mem, api, ngx, conns = m.groups()
            rows.append({"ts": int(ts), "cpu": float(busy), "steal": float(steal), "mem_avail_mb": int(mem), "api_rss_mb": int(api), "nginx_rss_mb": int(ngx), "conns": int(conns)})
    return rows


def cpu_stats(samples: list[dict], start: float, end: float) -> dict:
    win = [s for s in samples if start - 5 <= s["ts"] <= end + 5]
    if not win:
        return {"samples": 0}
    best = 0.0  # media móvil máxima de CPU en ventanas de 2 min
    for i, s in enumerate(win):
        chunk = [x["cpu"] for x in win if s["ts"] <= x["ts"] < s["ts"] + CPU_WINDOW_S]
        if chunk and (win[-1]["ts"] - s["ts"] >= CPU_WINDOW_S - 10 or i == 0):
            best = max(best, sum(chunk) / len(chunk))
    avg = sum(s["cpu"] for s in win) / len(win)
    return {"samples": len(win), "cpu_avg_pct": round(avg, 1), "cpu_max_pct": round(max(s["cpu"] for s in win), 1), "cpu_2min_max_avg_pct": round(best, 1),
            "steal_max_pct": round(max(s["steal"] for s in win), 1), "mem_avail_min_mb": min(s["mem_avail_mb"] for s in win), "api_rss_max_mb": max(s["api_rss_mb"] for s in win),
            "nginx_rss_max_mb": max(s["nginx_rss_mb"] for s in win), "db_conns_max": max(s["conns"] for s in win)}


def cw(namespace: str, metric: str, dim: tuple[str, str], start: datetime, end: datetime, period: int, stat: str) -> list[tuple[str, float]]:
    out = aws("cloudwatch", "get-metric-statistics", "--namespace", namespace, "--metric-name", metric, "--dimensions", f"Name={dim[0]},Value={dim[1]}",
              "--start-time", start.strftime("%Y-%m-%dT%H:%M:%SZ"), "--end-time", end.strftime("%Y-%m-%dT%H:%M:%SZ"), "--period", str(period), "--statistics", stat, "--output", "json")
    return sorted((d["Timestamp"], d[stat]) for d in json.loads(out)["Datapoints"])


def cloud_metrics(start: datetime, end: datetime) -> dict:
    iid, rds = instance_id(), "nexoeventos-academy-postgres"
    def last(points): return round(points[-1][1], 2) if points else None
    res = {"window_utc": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")]}
    ec2 = ("InstanceId", iid)
    res["ec2"] = {"cpu_pct_5min": [round(v, 1) for _, v in cw("AWS/EC2", "CPUUtilization", ec2, start, end, 300, "Maximum")],
                  "cpu_credit_balance": [round(v, 1) for _, v in cw("AWS/EC2", "CPUCreditBalance", ec2, start, end, 300, "Average")],
                  "cpu_credit_usage": [round(v, 2) for _, v in cw("AWS/EC2", "CPUCreditUsage", ec2, start, end, 300, "Sum")],
                  "network_out_mb": round(sum(v for _, v in cw("AWS/EC2", "NetworkOut", ec2, start, end, 300, "Sum")) / 2**20, 1),
                  "network_in_mb": round(sum(v for _, v in cw("AWS/EC2", "NetworkIn", ec2, start, end, 300, "Sum")) / 2**20, 1)}
    d = ("DBInstanceIdentifier", rds)
    def series(metric, stat, scale=1.0): return [round(v / scale, 2) for _, v in cw("AWS/RDS", metric, d, start, end, 60, stat)]
    res["rds"] = {"cpu_pct_1min_max": series("CPUUtilization", "Maximum"), "connections_max": series("DatabaseConnections", "Maximum"), "freeable_memory_mb_min": series("FreeableMemory", "Minimum", 2**20),
                  "read_iops_max": series("ReadIOPS", "Maximum"), "write_iops_max": series("WriteIOPS", "Maximum"), "disk_queue_depth_max": series("DiskQueueDepth", "Maximum"),
                  "cpu_credit_balance_min": series("CPUCreditBalance", "Minimum")}
    return res


def latest(metric_fn, minutes: int = 12):
    end = datetime.now(timezone.utc)
    return metric_fn(end - timedelta(minutes=minutes), end)


def integrity() -> dict:
    code = (ROOT / "perf" / "check_integrity.py").read_text(encoding="utf-8")
    script = MIG.replace("set -euo pipefail", "set -u") + '/opt/nexoeventos-deploy/current/backend/.venv/bin/python - --database-url "$DB_URL" --read-only-remote --event-ids 90001,90002,90003,90004 <<\'PYX\' || true\n' + code + "\nPYX\n"
    out = ssm_run(script, "k6: integridad (lectura)")
    lines = [l for l in out.splitlines() if l.startswith("{")]
    return json.loads(lines[-1]) if lines else {"error": "sin salida", "total_violations": -1}


def run_level(base_run: str, index: int, step: str, scenarios: str, label: str) -> dict:
    run_id = f"{base_run}{index}"
    hold = {"smoke": 60, "10": 120, "20": 150, "40": 150, "50": 120}[step]
    vus = {"smoke": 1, "10": 10, "20": 20, "40": 40, "50": 50}[step]
    est = 30 + hold + 5 + 10 + int(vus * 0.6) + 15 if scenarios == "mix" else 110
    cid, iid = ssm_start(sampler_script(est), f"k6 {label}: muestreo de CPU/memoria")
    t0 = time.time()
    env = {**os.environ, "NEXO_LOAD_TEST_APPROVED": run_id}
    proc = subprocess.run([PY, str(ROOT / "perf" / "run_cloud.py"), "--base-url", BASE, "--run-id", run_id, "--step", step, "--scenarios", scenarios, "--label", f"aws-v1-{base_run}/{label}"], env=env, capture_output=True, text=True)
    t1 = time.time()
    samples = parse_samples(ssm_wait(cid, iid, 300))
    return {"label": label, "step": step, "scenarios": scenarios, "run_id": run_id, "rc": proc.returncode, "stdout_tail": proc.stdout.strip().splitlines()[-6:], "stderr_tail": proc.stderr[-400:],
            "start_epoch": t0, "end_epoch": t1, "elapsed_s": round(t1 - t0, 1), "instance": cpu_stats(samples, t0, t1), "samples": samples}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()
    base = args.run_id
    if not re.fullmatch(r"[a-z0-9]{3,8}", base):
        sys.exit("--run-id: 3-8 caracteres alfanuméricos en minúsculas.")
    plan = [(s, "mix") for s in LEVELS] + [("20", "same_seat")]
    print(f"Plan: {', '.join(f'{s}/{sc}' for s, sc in plan)} · destino {BASE} · máx. {MAX_TOTAL_SECONDS // 60} min de escalera · 50 usuarios como máximo")
    if args.plan:
        return
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES" or os.environ.get("NEXO_LOAD_TEST_APPROVED") != base:
        sys.exit("Requiere NEXO_ALLOW_CLOUD_CHANGES=YES y NEXO_LOAD_TEST_APPROVED igual al --run-id.")
    out = ROOT / "perf" / "results" / f"aws-v1-{base}"
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"schema": 1, "run": base, "target": BASE, "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "levels": [], "stopped_reason": None}
    t_start = time.time()
    created = False
    try:
        # --- precondiciones (lectura) ---
        iid = instance_id()
        inst = json.loads(aws("ec2", "describe-instances", "--instance-ids", iid, "--query", "Reservations[0].Instances[0].[InstanceType,State.Name,Monitoring.State]", "--output", "json"))
        credit = aws("ec2", "describe-instance-credit-specifications", "--instance-ids", iid, "--query", "InstanceCreditSpecifications[0].CpuCredits", "--output", "text").strip()
        rds = json.loads(aws("rds", "describe-db-instances", "--db-instance-identifier", "nexoeventos-academy-postgres", "--query", "DBInstances[0].[DBInstanceClass,DBInstanceStatus,MultiAZ,AllocatedStorage,StorageType]", "--output", "json"))
        report["environment"] = {"ec2": {"type": inst[0], "state": inst[1], "monitoring": inst[2], "cpu_credits_mode": credit}, "rds": {"class": rds[0], "status": rds[1], "multi_az": rds[2], "storage_gib": rds[3], "storage_type": rds[4]}, "generator": "Mac del autor, vía Internet; k6 2.3.0 en Docker"}
        assert inst[1] == "running" and rds[1] == "available", "EC2/RDS no disponibles"
        pre = sql("SELECT 'fixture_events='||count(*) FROM events WHERE id BETWEEN 90001 AND 90099; SELECT 'k6_users='||count(*) FROM users WHERE email LIKE 'k6-%@example.com'; SELECT 'max_connections='||current_setting('max_connections');", "k6: precheck (lectura)")
        assert "fixture_events=0" in pre and "k6_users=0" in pre, f"ids/cuentas del fixture no libres: {pre}"
        before = sql(FINGERPRINT, "k6: huella previa (lectura)")
        report["fingerprint_before"] = before.split("\n")
        now = datetime.now(timezone.utc)
        report["baseline_metrics"] = latest(cloud_metrics, 15)
        base_credit = (report["baseline_metrics"]["ec2"]["cpu_credit_balance"] or [None])[-1]
        print(f"EC2 {inst[0]} ({credit}), RDS {rds[0]} · créditos EC2 al inicio: {base_credit} · {pre.split()[-1]}")
        assert base_credit is None or base_credit >= CREDITS_MIN, "créditos de CPU insuficientes para empezar"
        # --- fixture ---
        created = True
        sql(subprocess.check_output([PY, str(ROOT / "perf" / "cloud_fixture.py"), "up"], text=True), "k6: crear fixture (ids 90001-90004)")
        print("Fixture creado (eventos ocultos 90001-90004).", flush=True)
        for i, (step, scenarios) in enumerate(plan):
            if time.time() - t_start > MAX_TOTAL_SECONDS:
                report["stopped_reason"] = "límite de 28 min de escalera"; break
            label = f"{step}-{scenarios}" if scenarios != "mix" else f"nivel-{step}"
            print(f"▶ {label} …", flush=True)
            lv = run_level(base, i, step, scenarios, label)
            lv["integrity"] = integrity()
            inst_s = lv["instance"]
            # métricas recientes de CloudWatch (con retraso de minutos; informativas y para créditos)
            recent = latest(cloud_metrics, 15)
            credits_now = (recent["ec2"]["cpu_credit_balance"] or [None])[-1]
            lv["credits_latest"] = credits_now
            lv["rds_recent"] = {k: (v[-1] if v else None) for k, v in recent["rds"].items()}
            reasons = []
            if lv["rc"] != 0: reasons.append(f"k6 terminó con error o umbral/abort (rc={lv['rc']})")
            if lv["integrity"].get("total_violations") != 0: reasons.append(f"integridad: {lv['integrity'].get('total_violations')}")
            if inst_s.get("samples", 0) == 0: reasons.append("sin muestras de CPU (métrica crítica no observable)")
            if inst_s.get("cpu_2min_max_avg_pct", 0) > CPU_LIMIT: reasons.append(f"CPU {inst_s['cpu_2min_max_avg_pct']} % > {CPU_LIMIT} % en 2 min")
            if inst_s.get("db_conns_max", 0) > CONNS_MAX: reasons.append(f"conexiones {inst_s['db_conns_max']} > {CONNS_MAX}")
            if credits_now is not None and credits_now < CREDITS_MIN: reasons.append(f"créditos de CPU {credits_now} < {CREDITS_MIN}")
            if (lv["rds_recent"].get("cpu_pct_1min_max") or 0) > RDS_CPU_MAX: reasons.append("RDS CPU alta")
            if (lv["rds_recent"].get("freeable_memory_mb_min") or 1e9) < RDS_FREE_MIN_MB: reasons.append("RDS memoria liberable baja")
            lv["ok"] = not reasons; lv["stop_reasons"] = reasons
            report["levels"].append(lv)
            (out / f"{label}.json").write_text(json.dumps({k: v for k, v in lv.items() if k != "samples"}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print("   " + " | ".join(lv["stdout_tail"][-3:-1]) if lv["stdout_tail"] else "", flush=True)
            print(f"   EC2 CPU media {inst_s.get('cpu_avg_pct')} % · máx 2 min {inst_s.get('cpu_2min_max_avg_pct')} % · mem libre mín {inst_s.get('mem_avail_min_mb')} MB · conexiones máx {inst_s.get('db_conns_max')} · créditos {credits_now} · integridad {lv['integrity'].get('total_violations')} → {'OK' if lv['ok'] else 'PARADA: ' + '; '.join(reasons)}", flush=True)
            if not lv["ok"]:
                report["stopped_reason"] = f"{label}: " + "; ".join(reasons); break
    except BaseException as error:  # noqa: BLE001 - se informa y se limpia
        report["stopped_reason"] = f"error del orquestador: {type(error).__name__}: {str(error)[:300]}"
        print(report["stopped_reason"], file=sys.stderr)
    finally:
        try:
            if created:
                sql(subprocess.check_output([PY, str(ROOT / "perf" / "cloud_fixture.py"), "down"], text=True), "k6: limpiar fixture (solo ids 90001-90099 y usuarios k6-*)")
                left = sql("SELECT 'fixture_events='||count(*) FROM events WHERE id BETWEEN 90001 AND 90099; SELECT 'k6_users='||count(*) FROM users WHERE email LIKE 'k6-%@example.com';", "k6: restos (lectura)").split()
                report["cleanup"] = {"leftovers": left, "complete": left == ["fixture_events=0", "k6_users=0"]}
                after = sql(FINGERPRINT, "k6: huella posterior (lectura)")
                report["fingerprint_after"] = after.split("\n")
                report["fingerprint_identical"] = after == report.get("fingerprint_before_raw", None) or after.split("\n") == report.get("fingerprint_before")
                print(f"Limpieza: {report['cleanup']} · huella idéntica: {report['fingerprint_identical']}", flush=True)
        except BaseException as error:  # noqa: BLE001
            report["cleanup"] = {"error": f"{type(error).__name__}: {str(error)[:300]}"}
            print("ERROR DE LIMPIEZA (no se hacen más borrados):", report["cleanup"], file=sys.stderr)
        report["ended_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        report["elapsed_s"] = round(time.time() - t_start, 1)
        try:
            time.sleep(150)  # las métricas de RDS/EC2 de CloudWatch tardan en aparecer
            report["cloudwatch"] = cloud_metrics(datetime.fromisoformat(report["started_utc"]) - timedelta(minutes=2), datetime.now(timezone.utc))
        except BaseException as error:  # noqa: BLE001
            report["cloudwatch"] = {"error": str(error)[:200]}
        for lv in report["levels"]:
            lv.pop("samples", None)
        (out / "baseline.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Resultados en perf/results/aws-v1-{base}/ · detenida por: {report['stopped_reason'] or 'ninguna (escalera completa)'}")
        ok = report["stopped_reason"] is None and report.get("cleanup", {}).get("complete") and report.get("fingerprint_identical")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
