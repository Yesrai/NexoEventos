#!/usr/bin/env python3
"""Prueba controlada de tolerancia a fallos de AWS V2: con tráfico ligero y constante (solo lecturas: /api/events y /healthz, sin datos ni fixtures),
detiene la API (`systemctl stop nexoeventos-api`) en UNA instancia —sin detenerla ni terminarla—, mide la detección del ALB, las instancias sanas, los 5xx,
la continuidad del servicio y la recuperación, y vuelve a arrancar la API. Se aborta y restaura de inmediato si el ALB se queda sin destinos sanos o si el
ASG marca la instancia como no sana (iría a reemplazarla). Requiere NEXO_ALLOW_CLOUD_CHANGES=YES. No usa k6 ni toca Terraform.
Uso: python3 scripts/cloud/v2-failover-test.py --out docs/evidencias/tolerancia-fallos-v2-AAAAMMDD [--hold-after-detect 20]
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


def iso_ms(t: float) -> str:
    d = datetime.fromtimestamp(t, timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


TIME_KEYS = ("stop_issued_at", "stop_confirmed_at", "alb_marked_unhealthy_at", "restore_issued_at", "restore_confirmed_at", "both_healthy_again_at")


def events_utc(events: dict, t0: float) -> dict:
    """Marcas relativas (s desde T0) → UTC con milisegundos, para cruzarlas con la sonda de Azure y los registros de AWS."""
    return {k: iso_ms(t0 + events[k]) for k in TIME_KEYS if isinstance(events.get(k), (int, float))}


# Tipos de fallo (T5). «stop» = detención CONTROLADA del servicio (SIGTERM; Nginx sigue vivo y contesta 502 al instante): el de T5 1.er intento y el criterio original.
# «instance» = pérdida ABRUPTA de la instancia (ec2 stop-instances): sin respuesta de TCP; es MÁS dura que «stop» (las solicitudes al destino muerto esperan al tiempo de conexión).
FAULTS = ("stop", "instance")


def inject_fault(fault: str, victim: str) -> str:
    if fault == "stop":
        return M.ssm_output(victim, "systemctl stop nexoeventos-api")
    if fault == "instance":
        M.aws("ec2", "stop-instances", "--instance-ids", victim)
        return "stop-instances"
    raise ValueError(f"fallo desconocido: {fault}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--hold-after-detect", type=int, default=20)
    ap.add_argument("--rate", type=float, default=5.0)
    ap.add_argument("--clients", type=int, default=4, help="clientes independientes (conexiones distintas) que reparten el ritmo total")
    ap.add_argument("--allow-replacement", action="store_true",
                    help="experimento de AUTOHEALING: no aborta si el ASG marca la instancia como no sana (se espera su reemplazo) y no intenta restaurar una instancia ya terminada")
    ap.add_argument("--instances", type=int, default=2, help="instancias esperadas del ASG (2 en el 1.er intento; 6 en la variante C de T5)")
    ap.add_argument("--fault", choices=FAULTS, default="stop", help="stop (por defecto): detención CONTROLADA del servicio, como en T5 1.er intento; instance: pérdida ABRUPTA de la instancia (más dura; exige --allow-replacement)")
    ap.add_argument("--max-seconds", type=int, default=600, help="criterio de parada: tiempo máximo del experimento; al superarlo se aborta y se restaura la API")
    args = ap.parse_args()
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES":
        sys.exit("Requiere NEXO_ALLOW_CLOUD_CHANGES=YES (detiene temporalmente la API de una instancia de V2).")
    if args.fault == "instance" and not args.allow_replacement:
        sys.exit("--fault instance exige --allow-replacement (la instancia detenida no se restaura: la sustituye el ASG).")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    health0 = M.target_health()
    assert len(health0) == args.instances and all(s == "healthy" for s in health0.values()), f"V2 no tiene {args.instances} instancias sanas: {health0}"
    act0 = {a["ActivityId"] for a in M.aws("autoscaling", "describe-scaling-activities", "--auto-scaling-group-name", M.ASG_NAME, "--max-items", "20").get("Activities", [])}
    victim = sorted(health0)[0]
    other = next(i for i in health0 if i != victim)
    alb = subprocess.check_output(["terraform", "output", "-raw", "alb_dns_name"], cwd=ROOT / "infra" / "aws-v2", text=True).strip()
    ip = sorted({a[4][0] for a in socket.getaddrinfo(alb, 443, socket.AF_INET)})[0]
    real = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **k: real(ip if host == DOMAIN else host, *a, **k)

    stop, abort = threading.Event(), {"reason": None}
    requests_log: list[dict] = []
    timeline: list[dict] = []

    def traffic(worker: int) -> None:
        # Cada trabajador es un cliente independiente con su propio ritmo y elige la ruta AL AZAR (sin alternancia que pueda sincronizarse con el ALB).
        rng = random.Random(1000 + worker)
        per_worker = args.rate / args.clients
        stop.wait(rng.uniform(0, 1 / per_worker))
        while not stop.is_set():
            path = rng.choice(["/api/events", "/healthz"])
            t = time.time()
            try:
                with httpx.Client(headers={"Connection": "close"}, timeout=15) as c:
                    code = c.get(f"https://{DOMAIN}{path}").status_code
            except httpx.HTTPError:
                code = -1
            requests_log.append({"t": round(t - T0, 2), "path": path, "status": code, "ms": round((time.time() - t) * 1000), "client": worker})
            stop.wait(max(0.0, 1 / per_worker - (time.time() - t)))

    def poll() -> None:
        last = None
        while not stop.is_set():
            try:
                health = M.target_health()
                asg = M.aws("autoscaling", "describe-auto-scaling-groups", "--auto-scaling-group-names", M.ASG_NAME)["AutoScalingGroups"][0]
                asg_state = {i["InstanceId"]: (i["LifecycleState"], i["HealthStatus"]) for i in asg["Instances"]}
                snap = {"t": now(), "alb": {k[-6:]: v for k, v in health.items()}, "asg": {k[-6:]: list(v) for k, v in asg_state.items()}, "asg_desired": asg["DesiredCapacity"]}
                key = json.dumps([snap["alb"], snap["asg"]], sort_keys=True)
                if key != last:
                    timeline.append(snap); last = key
                if sum(1 for s in health.values() if s == "healthy") == 0:
                    abort["reason"] = "el ALB se quedó sin destinos sanos"
                if not args.allow_replacement and (any(h != "Healthy" or s != "InService" for s, h in asg_state.values()) or len(asg_state) != args.instances):
                    abort["reason"] = f"el ASG cambió el estado de una instancia: {asg_state}"
                if now() > args.max_seconds:
                    abort["reason"] = f"tiempo máximo excedido ({args.max_seconds} s)"
            except Exception as error:  # noqa: BLE001
                timeline.append({"t": now(), "error": str(error)[:120]})
    # el ciclo de consulta ya tarda ~2 s por las dos llamadas

    threads = [threading.Thread(target=traffic, args=(w,)) for w in range(args.clients)] + [threading.Thread(target=poll)]
    [t.start() for t in threads]
    events: dict = {"fault": args.fault, "expected_instances": args.instances, "t0_utc": iso_ms(T0), "victim": victim[-6:], "other": other[-6:], "rate_req_per_s": args.rate, "allow_replacement": args.allow_replacement, "max_seconds": args.max_seconds}
    stopped = False
    try:
        time.sleep(25)  # línea base sana
        events["baseline_s"] = 25
        events["stop_issued_at"] = now()
        inject_fault(args.fault, victim)
        stopped = True
        events["stop_confirmed_at"] = now()
        deadline = time.time() + 120
        detected = None
        while time.time() < deadline and not abort["reason"]:
            states = [x for x in timeline if x.get("alb", {}).get(victim[-6:]) in ("unhealthy", "draining", "unused")]
            if states:
                detected = states[0]["t"]; break
            time.sleep(1)
        events["alb_marked_unhealthy_at"] = detected
        if detected is not None and not abort["reason"]:
            time.sleep(args.hold_after_detect)
        events["restore_issued_at"] = now()
    finally:
        if stopped:
            try:
                M.ssm_output(victim, "systemctl start nexoeventos-api")
            except Exception as exc:  # noqa: BLE001  p. ej. el ASG ya terminó la instancia (autohealing): se registra y se conservan los resultados
                events["restore_error"] = type(exc).__name__
            events["restore_confirmed_at"] = now()
    recovered = None
    deadline = time.time() + 180
    while time.time() < deadline:
        last = [x for x in timeline if "alb" in x][-1]
        # El historial solo guarda CAMBIOS de estado: en un autohealing el estado «2 sanos» se alcanza (y queda registrado) ANTES de la restauración manual,
        # así que se compara con la inyección del fallo y no con la restauración (corregido el 4-nov-2026: antes daba `null` aunque el ASG ya hubiera repuesto la capacidad).
        reference = events["stop_issued_at"] if args.allow_replacement else events["restore_confirmed_at"]
        if all(v == "healthy" for v in last["alb"].values()) and len(last["alb"]) == args.instances and last["t"] > reference:
            recovered = last["t"]; break
        time.sleep(2)
    events["both_healthy_again_at"] = recovered
    time.sleep(15)  # tráfico posterior a la recuperación
    stop.set()
    [t.join() for t in threads]
    end = time.time()
    events["abort_reason"] = abort["reason"]
    events["utc"] = events_utc(events, T0)          # marcas absolutas (UTC, ms) de cada hito: la sincronización de relojes se evidencia aparte (scripts/ops/t5-relojes.sh)

    ok_lat = [r["ms"] for r in requests_log if r["status"] == 200]
    errors = [r for r in requests_log if r["status"] != 200]
    summary = {"requests": len(requests_log), "ok": len(ok_lat), "errors": len(errors), "error_statuses": {str(s): sum(1 for r in errors if r["status"] == s) for s in sorted({r["status"] for r in errors})},
               "by_path": {p: {"requests": sum(1 for r in requests_log if r["path"] == p), "errors": sum(1 for r in errors if r["path"] == p), "first_error_at": next((r["t"] for r in errors if r["path"] == p), None), "last_error_at": next((r["t"] for r in reversed(errors) if r["path"] == p), None)} for p in ("/api/events", "/healthz")},
               "first_error_at": errors[0]["t"] if errors else None, "last_error_at": errors[-1]["t"] if errors else None, "p95_ok_ms": sorted(ok_lat)[int(0.95 * (len(ok_lat) - 1))] if ok_lat else None,
               "availability_pct": round(100 * len(ok_lat) / max(1, len(requests_log)), 2)}
    summary.update(V.split_availability(requests_log))  # disponibilidad del tráfico funcional (/api) separada de la de los sondeos de salud
    if events.get("alb_marked_unhealthy_at") is not None:
        events["detection_after_stop_s"] = round(events["alb_marked_unhealthy_at"] - events["stop_issued_at"], 1)
    if recovered is not None and args.allow_replacement:
        events["capacity_restored_after_stop_s"] = round(recovered - events["stop_issued_at"], 1)  # autohealing: 2 destinos sanos de nuevo, medido desde el fallo
    elif recovered is not None:
        events["recovery_after_restore_s"] = round(recovered - events["restore_confirmed_at"], 1)
    # Se guarda YA lo medido por el cliente: las consultas posteriores (Nginx de una instancia que el ASG pudo terminar, CloudWatch) pueden fallar
    # y antes eso hacía perder toda la medición (repetición del 22-oct, `InvalidInstanceId`).
    (out / "resultado-parcial.json").write_text(json.dumps({"schema": 1, "events": events, "client": summary, "timeline": timeline}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "solicitudes.json").write_text(json.dumps(requests_log) + "\n", encoding="utf-8")
    # 5xx en el log de Nginx de cada instancia durante la ventana
    window = (iso(T0), iso(end + 2))
    nginx = {}
    for inst in (victim, other):
        script = (f"awk -v a='{window[0].replace('Z', '+00:00')}' -v b='{window[1].replace('Z', '+00:00')}' '{{ if (match($0,/^[0-9T:+-]+/)) {{ t=substr($0,RSTART,RLENGTH); if (t>=a && t<b && $0 ~ /path=\\/api\\//) {{ n++; if ($0 ~ /status=5/) e++ }} }} }} END{{print n+0, e+0}}' /var/log/nginx/nexoeventos-access.log")
        try:
            n, e = (M.ssm_output(inst, script).split() + ["0", "0"])[:2]
            nginx[inst[-6:]] = {"api_requests": int(n), "api_5xx": int(e)}
        except Exception as exc:  # p. ej. la instancia ya fue terminada por el ASG: se registra y se continúa
            nginx[inst[-6:]] = {"error": type(exc).__name__}
    time.sleep(120)  # métricas del ALB en CloudWatch tardan en aparecer
    lb = M.aws("elbv2", "describe-load-balancers", "--names", M.LB_NAME)["LoadBalancers"][0]["LoadBalancerArn"].split("loadbalancer/")[1]
    tg = M.aws("elbv2", "describe-target-groups", "--names", M.TG_NAME)["TargetGroups"][0]["TargetGroupArn"].split(":")[-1]
    def stat(metric, dims, statistic):
        pts = M.aws("cloudwatch", "get-metric-statistics", "--namespace", "AWS/ApplicationELB", "--metric-name", metric, "--dimensions", *[f"Name={k},Value={v}" for k, v in dims],
                    "--start-time", iso(T0 - 60), "--end-time", iso(time.time()), "--period", "60", "--statistics", statistic)["Datapoints"]
        return [int(p[statistic]) for p in sorted(pts, key=lambda p: p["Timestamp"])]
    cloudwatch = {"healthy_hosts_min_per_minute": stat("HealthyHostCount", [("LoadBalancer", lb), ("TargetGroup", tg)], "Minimum"), "unhealthy_hosts_max_per_minute": stat("UnHealthyHostCount", [("LoadBalancer", lb), ("TargetGroup", tg)], "Maximum"),
                  "target_5xx_per_minute": stat("HTTPCode_Target_5XX_Count", [("LoadBalancer", lb)], "Sum"), "elb_5xx_per_minute": stat("HTTPCode_ELB_5XX_Count", [("LoadBalancer", lb)], "Sum"), "requests_per_minute": stat("RequestCount", [("LoadBalancer", lb)], "Sum")}
    final = M.target_health()
    asg = M.aws("autoscaling", "describe-auto-scaling-groups", "--auto-scaling-group-names", M.ASG_NAME)["AutoScalingGroups"][0]
    result = {"schema": 1, "events": events, "client": summary, "nginx": nginx, "cloudwatch": cloudwatch, "timeline": timeline,
              "final": {"alb": {k[-6:]: v for k, v in final.items()}, "asg": [[i["LifecycleState"], i["HealthStatus"]] for i in asg["Instances"]], "asg_activities_new": [a["Description"][:60] for a in M.aws("autoscaling", "describe-scaling-activities", "--auto-scaling-group-name", M.ASG_NAME, "--max-items", "20").get("Activities", []) if a["ActivityId"] not in act0]}}
    (out / "resultado.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "solicitudes.json").write_text(json.dumps(requests_log) + "\n", encoding="utf-8")
    print(json.dumps({"events": events, "client": summary, "nginx": nginx, "final": result["final"]}, indent=1, ensure_ascii=False))
    sys.exit(0 if not abort["reason"] and recovered is not None else 1)


if __name__ == "__main__":
    main()
