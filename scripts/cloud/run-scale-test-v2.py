#!/usr/bin/env python3
"""Prueba ÚNICA y controlada de Auto Scaling de V2 (2 → 3 instancias) con la política existente (CPU media, objetivo 40 %), según
docs/operacion/propuesta-escalado-v2.md. Genera inicios de sesión (Argon2) a 8/s con k6 (escenario login_rate, ≤ 50 usuarios), vigila en vivo y registra:
alarma alta, capacidad deseada 3, instancia nueva (pending/InService), tercera instancia healthy; tras ≥ 2 min de evidencia (o 12 min de carga) para la
carga y observa el regreso a 2 sin intervenir (≤ 25 min). Los usuarios ficticios k6-* y la huella usan la identidad migradora de la EC2 de V1 (encendida
temporalmente; se detiene al limpiar). Criterios de parada: errores o p95 de login > 3 s (k6), CPU > 85 % 2 min, memoria < 300 MB, RDS CPU > 60 % / memoria
< 100 MB / conexiones > 50, créditos excedentes > 50, menos de 2 destinos sanos. No aumenta la carga ni toca la política ni fuerza instancias.
Uso: NEXO_ALLOW_CLOUD_CHANGES=YES NEXO_LOAD_TEST_APPROVED=<run-id> python3 scripts/cloud/run-scale-test-v2.py --run-id <run-id> [--plan]
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
from concurrent.futures import ThreadPoolExecutor
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
LV2 = load("ladderv2", "scripts/cloud/run-k6-ladder-v2.py")
ALARM_PREFIX = f"TargetTracking-{M.ASG_NAME}"
MAX_LOAD_S, EVIDENCE_AFTER_THIRD_S, MAX_COOLDOWN_S, THIRD_HEALTHY_LIMIT_S = 12 * 60, 120, 25 * 60, 12 * 60
T0 = time.time()
now = lambda: round(time.time() - T0, 1)  # noqa: E731


def asg_state() -> dict:
    g = M.aws("autoscaling", "describe-auto-scaling-groups", "--auto-scaling-group-names", M.ASG_NAME)["AutoScalingGroups"][0]
    return {"desired": g["DesiredCapacity"], "instances": {i["InstanceId"]: [i["AvailabilityZone"], i["LifecycleState"], i["HealthStatus"]] for i in g["Instances"]}}


def alarms() -> dict:
    out = {}
    for a in M.aws("cloudwatch", "describe-alarms", "--alarm-name-prefix", ALARM_PREFIX).get("MetricAlarms", []):
        out["alta" if "AlarmHigh" in a["AlarmName"] else "baja"] = a["StateValue"]
    return out


def probe(iid: str) -> dict:
    script = ("v=$(vmstat 3 2 | tail -1); echo \"P $(echo $v | awk '{print 100-$15}') $(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo) "
              "$(ps -eo rss,args | awk '/uvicorn|multiprocessing/ && !/awk/ {s+=$1} END{print int(s/1024)}')\"")
    m = re.search(r"P (\d+) (\d+) (\d+)", M.ssm_output(iid, script))
    return {"cpu": int(m[1]), "mem_avail_mb": int(m[2]), "api_rss_mb": int(m[3])} if m else {}


def rds_now() -> dict:
    end = datetime.now(timezone.utc)
    d = [("DBInstanceIdentifier", "nexoeventos-academy-postgres")]
    last = lambda m_, st, sc=1.0: ([v / sc for v in LV2.cw_dims("AWS/RDS", m_, d, end - timedelta(minutes=4), end, 60, st)] or [None])[-1]  # noqa: E731
    return {"cpu": last("CPUUtilization", "Maximum"), "free_mb": last("FreeableMemory", "Minimum", 2**20), "conns": last("DatabaseConnections", "Maximum")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()
    base = args.run_id
    if not re.fullmatch(r"[a-z0-9]{3,8}", base):
        sys.exit("--run-id: 3-8 caracteres alfanuméricos en minúsculas.")
    print(f"Plan: login_rate 8/s (≤ 50 usuarios) hasta {MAX_LOAD_S // 60} min · +{EVIDENCE_AFTER_THIRD_S}s tras la 3.ª instancia sana · observar regreso a 2 (≤ {MAX_COOLDOWN_S // 60} min)")
    if args.plan:
        return
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES" or os.environ.get("NEXO_LOAD_TEST_APPROVED") != base:
        sys.exit("Requiere NEXO_ALLOW_CLOUD_CHANGES=YES y NEXO_LOAD_TEST_APPROVED igual al --run-id.")
    out = ROOT / "perf" / "results" / f"aws-v2-scale-{base}"
    out.mkdir(parents=True, exist_ok=True)
    rep: dict = {"schema": 1, "run": base, "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "milestones": {}, "timeline": [], "probes": [], "stop_reason": None}
    save = lambda: (out / "escalado.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")  # noqa: E731
    ms = rep["milestones"]
    k6, container, cleaned = None, f"k6-{base}0-login-rate", False

    def cleanup() -> None:
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        try:
            L.sql(subprocess.check_output([L.PY, str(ROOT / "perf" / "cloud_fixture.py"), "down"], text=True), "escalado: borrar usuarios k6-* (solo ellos)")
            left = L.sql("SELECT 'k6_users='||count(*) FROM users WHERE email LIKE 'k6-%@example.com'; SELECT 'fixture_events='||count(*) FROM events WHERE id BETWEEN 90001 AND 90099;", "escalado: restos (lectura)").split()
            after = L.sql(L.FINGERPRINT, "escalado: huella posterior (lectura)").split("\n")
            rep["cleanup"] = {"leftovers": left, "complete": left == ["k6_users=0", "fixture_events=0"]}
            rep["fingerprint_after"], rep["fingerprint_identical"] = after, after == rep.get("fingerprint_before")
            print(f"[{now()}s] Limpieza: {rep['cleanup']} · huella idéntica: {rep['fingerprint_identical']}", flush=True)
        except BaseException as error:  # noqa: BLE001
            rep["cleanup"] = {"error": f"{type(error).__name__}: {str(error)[:300]}"}
            print("ERROR DE LIMPIEZA (no se hacen más borrados):", rep["cleanup"], file=sys.stderr)
        try:
            subprocess.run([str(ROOT / "scripts" / "cloud" / "v2-prepare.sh"), "v1-ec2-stop"], env={**os.environ, "NEXO_ALLOW_CLOUD_CHANGES": "YES"}, capture_output=True, text=True, timeout=900)
            rep["v1_ec2_stopped"] = True
        except BaseException as error:  # noqa: BLE001
            rep["v1_ec2_stopped"] = f"error: {str(error)[:120]}"
        save()

    try:
        health = M.target_health()
        st0 = asg_state()
        assert len(health) == 2 and all(s == "healthy" for s in health.values()) and st0["desired"] == 2 and len(st0["instances"]) == 2, f"estado inicial no válido: {health} {st0}"
        assert alarms().get("alta") == "OK", "la alarma alta no está en OK al empezar"
        ip = LV2.alb_ip()
        pre = L.sql("SELECT 'k6_users='||count(*) FROM users WHERE email LIKE 'k6-%@example.com'; SELECT 'fixture_events='||count(*) FROM events WHERE id BETWEEN 90001 AND 90099;", "escalado: precheck (lectura)")
        assert "k6_users=0" in pre and "fixture_events=0" in pre, pre
        rep["fingerprint_before"] = L.sql(L.FINGERPRINT, "escalado: huella previa (lectura)").split("\n")
        base_instances = set(st0["instances"])
        act0 = {a["ActivityId"] for a in M.aws("autoscaling", "describe-scaling-activities", "--auto-scaling-group-name", M.ASG_NAME, "--max-items", "30").get("Activities", [])}
        env = {**os.environ, "NEXO_LOAD_TEST_APPROVED": f"{base}0"}
        k6 = subprocess.Popen([L.PY, str(ROOT / "perf" / "run_cloud.py"), "--base-url", L.BASE, "--run-id", f"{base}0", "--step", "scale", "--scenarios", "login_rate", "--label", f"aws-v2-scale-{base}/carga", "--resolve-ip", ip],
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        load_start = time.time()
        ms["load_started_at_s"] = now()
        print(f"[{now()}s] Carga iniciada (registro de 50 usuarios ficticios y 8 logins/s)", flush=True)
        last_key, last_probe, last_rds, third_healthy_at, load_stopped, cpu_hist = None, 0.0, 0.0, None, None, {}
        cooldown_start = None
        while True:
            t = time.time()
            asg, tg, al = asg_state(), M.target_health(), alarms()
            snap = {"t": now(), "desired": asg["desired"], "asg": {i[-6:]: v for i, v in asg["instances"].items()}, "alb": {i[-6:]: v for i, v in tg.items()}, "alarms": al}
            key = json.dumps([snap["desired"], snap["asg"], snap["alb"], snap["alarms"]], sort_keys=True)
            if key != last_key:
                rep["timeline"].append(snap); last_key = key; save()
            healthy = [i for i, s in tg.items() if s == "healthy"]
            if al.get("alta") == "ALARM": ms.setdefault("alarm_high_at_s", now())
            if asg["desired"] == 3: ms.setdefault("desired_3_at_s", now())
            new = [i for i in asg["instances"] if i not in base_instances]
            if new: ms.setdefault("new_instance_seen_at_s", now())
            if any(asg["instances"][i][1] == "InService" for i in new): ms.setdefault("new_instance_inservice_at_s", now())
            if len(healthy) >= 3 and third_healthy_at is None:
                third_healthy_at = t; ms["third_instance_healthy_at_s"] = now(); print(f"[{now()}s] TERCERA instancia healthy", flush=True)
            if load_stopped is None:
                if len(healthy) < 2: rep["stop_reason"] = "menos de 2 destinos sanos"
                if third_healthy_at is None and not new and k6.poll() is None and t - load_start > THIRD_HEALTHY_LIMIT_S: rep["stop_reason"] = "no escaló en 12 min de carga (no se aumenta la carga ni se cambia la política)"
                if third_healthy_at is None and t - load_start > THIRD_HEALTHY_LIMIT_S: rep["stop_reason"] = rep["stop_reason"] or "la tercera instancia no está sana a los 12 min de carga"
                if k6.poll() is not None and not rep["stop_reason"]: rep["stop_reason"] = f"k6 terminó (rc={k6.returncode})"
            # sondas en vivo (CPU/memoria) y RDS
            if t - last_probe >= 30 and load_stopped is None:
                last_probe = t
                ids = [i for i, v in asg["instances"].items() if v[1] == "InService"]
                with ThreadPoolExecutor(max(1, len(ids))) as pool:
                    for iid, p in zip(ids, pool.map(lambda i: probe(i) if True else {}, ids)):
                        if not p: continue
                        rep["probes"].append({"t": now(), "instance": iid[-6:], **p})
                        cpu_hist.setdefault(iid, []).append(p["cpu"])
                        if len(cpu_hist[iid]) >= 4 and min(cpu_hist[iid][-4:]) > 85: rep["stop_reason"] = f"CPU > 85 % durante 2 min en {iid[-6:]}"
                        if p["mem_avail_mb"] < 300: rep["stop_reason"] = f"memoria disponible {p['mem_avail_mb']} MB < 300 en {iid[-6:]}"
            if t - last_rds >= 60 and load_stopped is None:
                last_rds = t
                r = rds_now(); rep["probes"].append({"t": now(), "rds": r})
                if (r["cpu"] or 0) > 60: rep["stop_reason"] = f"RDS CPU {r['cpu']} % > 60"
                if (r["free_mb"] or 1e9) < 100: rep["stop_reason"] = f"RDS memoria liberable {r['free_mb']} MB < 100"
                if (r["conns"] or 0) > 50: rep["stop_reason"] = f"RDS conexiones {r['conns']} > 50"
            # fin de la carga: evidencia suficiente (3.ª sana + 2 min), tope de 12 min o criterio de parada
            if load_stopped is None and (rep["stop_reason"] or (third_healthy_at and t - third_healthy_at >= EVIDENCE_AFTER_THIRD_S) or t - load_start >= MAX_LOAD_S):
                subprocess.run(["docker", "stop", container], capture_output=True)
                load_stopped = t; ms["load_stopped_at_s"] = now(); cooldown_start = t
                print(f"[{now()}s] Carga detenida ({rep['stop_reason'] or 'evidencia suficiente'})", flush=True)
                try: k6.wait(timeout=60)
                except subprocess.TimeoutExpired: pass
                rep["k6_output_tail"] = (k6.stdout.read() if k6.stdout else "")[-600:]
                cleanup()
                if rep["stop_reason"] and not new: break
            if load_stopped is not None:
                if al.get("baja") == "ALARM": ms.setdefault("alarm_low_at_s", now())
                if asg["desired"] == 2 and "desired_3_at_s" in ms: ms.setdefault("desired_back_to_2_at_s", now())
                if "desired_back_to_2_at_s" in ms and len(asg["instances"]) == 2 and len(healthy) == 2: ms["back_to_2_instances_at_s"] = now(); break
                if t - cooldown_start > MAX_COOLDOWN_S: rep["stop_reason"] = rep["stop_reason"] or "no volvió a 2 en 25 min tras terminar la carga"; break
            time.sleep(max(0.0, 8 - (time.time() - t)))
    except BaseException as error:  # noqa: BLE001
        rep["stop_reason"] = rep["stop_reason"] or f"error del orquestador: {type(error).__name__}: {str(error)[:300]}"
        print(rep["stop_reason"], file=sys.stderr)
    finally:
        if k6 is not None and k6.poll() is None:
            subprocess.run(["docker", "stop", container], capture_output=True)
        cleanup()
        rep["ended_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            time.sleep(120)
            start_dt = datetime.fromisoformat(rep["started_utc"]) - timedelta(minutes=2)
            end_dt = datetime.now(timezone.utc)
            rep["cloudwatch"] = LV2.metrics_v2(start_dt, end_dt)
            rep["alarm_history"] = [{"alarm": h["AlarmName"][-10:], "t": h["Timestamp"], "summary": h["HistorySummary"][:90]} for a in ("High", "Low")
                                    for h in M.aws("cloudwatch", "describe-alarm-history", "--history-item-type", "StateUpdate", "--start-date", start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "--alarm-name", next(x["AlarmName"] for x in M.aws("cloudwatch", "describe-alarms", "--alarm-name-prefix", ALARM_PREFIX)["MetricAlarms"] if f"Alarm{a}" in x["AlarmName"])).get("AlarmHistoryItems", [])]
            rep["asg_activities"] = [{"t": a["StartTime"], "status": a["StatusCode"], "cause": re.sub(r"i-[0-9a-f]{17}", "i-…", a["Cause"])[:140]} for a in M.aws("autoscaling", "describe-scaling-activities", "--auto-scaling-group-name", M.ASG_NAME, "--max-items", "30").get("Activities", []) if a["ActivityId"] not in locals().get("act0", set())]
        except BaseException as error:  # noqa: BLE001
            rep["cloudwatch_error"] = str(error)[:200]
        save()
        print(f"Resultados en perf/results/aws-v2-scale-{base}/ · parada: {rep['stop_reason'] or 'ninguna'} · hitos: {ms}")
        sys.exit(0 if not rep["stop_reason"] and rep.get("cleanup", {}).get("complete") and rep.get("fingerprint_identical") else 1)


if __name__ == "__main__":
    main()
