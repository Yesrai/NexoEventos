#!/usr/bin/env python3
"""Ráfagas de 20 y (si es seguro) 50 inicios de sesión SIMULTÁNEOS contra AWS V1 con cuentas ficticias `ensayo-rafaga-*`.

Mide latencia p50/p95/p99, errores, respuesta de /ready y del catálogo durante la ráfaga y, en la instancia (muestreo cada ~4 s por Session Manager),
memoria de la API (RSS), memoria disponible mínima, CPU y conexiones a PostgreSQL. Detiene la escalera si hay errores graves, memoria disponible
< 300 MB, /ready con 3 sondeos seguidos > 2 s o CPU > 85 % sostenida. Limpia solo las cuentas creadas y compara la huella de la base antes/después.
Requiere NEXO_ALLOW_CLOUD_CHANGES=YES. Uso: python3 scripts/cloud/verify-login-burst.py [--sizes 20,50]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ladder", ROOT / "scripts" / "cloud" / "run-k6-ladder.py")
ladder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ladder)
BASE = "https://nexoeventos-demo.duckdns.org"
HEADERS = {"Origin": BASE}
MEM_MIN_MB, READY_MAX_MS = 300, 2000


def pct(values: list[float], q: float) -> int:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))])


def burst(users: list[tuple[str, str]], size: int) -> dict:
    sampler_id = ladder.ssm_start(ladder.sampler_script(60), f"login-burst {size}: muestreo")
    time.sleep(8)  # el muestreador arranca antes de la ráfaga
    stop, probes = threading.Event(), {"ready": [], "catalogo": []}

    def probe() -> None:
        with httpx.Client(base_url=BASE, headers=HEADERS, timeout=60) as c:
            while not stop.is_set():
                for name, path in (("ready", "/healthz"), ("catalogo", "/api/events")):
                    t = time.perf_counter()
                    try:
                        code = c.get(path).status_code
                    except httpx.HTTPError:
                        code = -1
                    probes[name].append(((time.perf_counter() - t) * 1000, code))
                stop.wait(0.15)

    pt = threading.Thread(target=probe)
    pt.start()
    time.sleep(1)
    barrier = threading.Barrier(size)
    clients = [httpx.Client(base_url=BASE, headers=HEADERS, timeout=120) for _ in range(size)]
    lat, codes = [0.0] * size, [0] * size

    def one(i: int) -> None:
        barrier.wait()
        t = time.perf_counter()
        try:
            codes[i] = clients[i].post("/api/auth/login", json={"email": users[i][0], "password": users[i][1]}).status_code
        except httpx.HTTPError:
            codes[i] = -1
        lat[i] = (time.perf_counter() - t) * 1000

    t0, e0 = time.time(), time.perf_counter()
    with ThreadPoolExecutor(size) as pool:
        list(pool.map(one, range(size)))
    wall = time.perf_counter() - e0
    t1 = time.time()
    time.sleep(2)
    stop.set()
    pt.join()
    for c in clients:
        c.close()
    samples = ladder.parse_samples(ladder.ssm_wait(*sampler_id, limit=240))
    stats = ladder.cpu_stats(samples, t0, t1 + 2)
    res = {"size": size, "errors": sum(1 for c in codes if c != 200), "status_codes": {str(c): codes.count(c) for c in sorted(set(codes))},
           "latency_ms": {"p50": pct(lat, .5), "p95": pct(lat, .95), "p99": pct(lat, .99), "max": round(max(lat))}, "wall_s": round(wall, 2), "logins_per_s": round(size / wall, 1),
           "instance": stats, "api_rss_peak_mb": stats.get("api_rss_max_mb"), "mem_avail_min_mb": stats.get("mem_avail_min_mb"), "cpu_max_pct": stats.get("cpu_max_pct")}
    for name, values in probes.items():
        ms = [v[0] for v in values]
        res[name] = {"sondeos": len(ms), "p95_ms": pct(ms, .95), "max_ms": round(max(ms)), "no200": sum(1 for v in values if v[1] != 200)}
    slow = [v[0] > READY_MAX_MS for v in probes["ready"]]
    res["ready_degraded"] = any(all(slow[i:i + 3]) and len(slow[i:i + 3]) == 3 for i in range(len(slow)))
    reasons = []
    if res["errors"]:
        reasons.append(f"{res['errors']} errores de login")
    if (res["mem_avail_min_mb"] or 1e9) < MEM_MIN_MB:
        reasons.append(f"memoria disponible mínima {res['mem_avail_min_mb']} MB < {MEM_MIN_MB}")
    if res["ready_degraded"] or res["ready"]["no200"]:
        reasons.append("/healthz degradado")
    if (stats.get("cpu_2min_max_avg_pct") or 0) > 85:
        reasons.append("CPU > 85 %")
    res["ok"], res["stop_reasons"] = not reasons, reasons
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="20,50")
    args = ap.parse_args()
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES":
        sys.exit("Requiere NEXO_ALLOW_CLOUD_CHANGES=YES.")
    sizes = [int(x) for x in args.sizes.split(",")]
    run = uuid.uuid4().hex[:8]
    prefix = f"ensayo-rafaga-{run}-"
    out = ROOT / "perf" / "results" / "login-burst-aws"
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"schema": 1, "run": run, "target": BASE, "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bursts": [], "stopped_reason": None}
    before = ladder.sql(ladder.FINGERPRINT, "login-burst: huella previa (lectura)")
    leftovers = ladder.sql("SELECT 'cuentas='||count(*) FROM users WHERE email LIKE 'ensayo-rafaga-%';", "login-burst: restos previos (lectura)")
    assert "cuentas=0" in leftovers, leftovers
    users: list[tuple[str, str]] = []
    try:
        with httpx.Client(base_url=BASE, headers=HEADERS, timeout=60) as c:
            for i in range(max(sizes)):
                email, pw = f"{prefix}{i}@example.com", secrets.token_urlsafe(18)
                assert c.post("/api/auth/register", json={"email": email, "display_name": "Ensayo ráfaga", "password": pw}).status_code == 201, "registro"
                users.append((email, pw))
        print(f"{len(users)} cuentas ficticias creadas ({prefix}*)", flush=True)
        for size in sizes:
            time.sleep(10)
            r = burst(users, size)
            report["bursts"].append(r)
            print(f"  {size:>2} simultáneos: p50 {r['latency_ms']['p50']} / p95 {r['latency_ms']['p95']} / p99 {r['latency_ms']['p99']} ms · errores {r['errors']} · API RSS pico {r['api_rss_peak_mb']} MB · mem libre mín {r['mem_avail_min_mb']} MB · CPU máx {r['cpu_max_pct']} % · /healthz p95 {r['ready']['p95_ms']} ms (máx {r['ready']['max_ms']}) · {'OK' if r['ok'] else 'PARADA: ' + '; '.join(r['stop_reasons'])}", flush=True)
            if not r["ok"]:
                report["stopped_reason"] = f"{size}: " + "; ".join(r["stop_reasons"])
                break
    except BaseException as error:  # noqa: BLE001
        report["stopped_reason"] = f"error: {type(error).__name__}: {str(error)[:200]}"
        print(report["stopped_reason"], file=sys.stderr)
    finally:
        try:
            ladder.sql(f"BEGIN; DELETE FROM users u WHERE u.email LIKE '{prefix}%@example.com' AND u.email LIKE 'ensayo-rafaga-%' AND NOT EXISTS (SELECT 1 FROM reservations r WHERE r.user_id = u.id) AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.owner_user_id = u.id); COMMIT;", "login-burst: limpiar cuentas de ensayo")
            left = ladder.sql("SELECT 'cuentas='||count(*) FROM users WHERE email LIKE 'ensayo-rafaga-%'; SELECT 'rate_limits='||count(*) FROM auth_rate_limits;", "login-burst: restos (lectura)").split()
            after = ladder.sql(ladder.FINGERPRINT, "login-burst: huella posterior (lectura)")
            report["cleanup"] = {"leftovers": left, "complete": left[0] == "cuentas=0"}
            report["fingerprint_before"], report["fingerprint_after"], report["fingerprint_identical"] = before.split("\n"), after.split("\n"), before == after
            print(f"Limpieza: {report['cleanup']} · huella idéntica: {before == after}", flush=True)
        except BaseException as error:  # noqa: BLE001
            report["cleanup"] = {"error": f"{type(error).__name__}: {str(error)[:200]}"}
            print("ERROR DE LIMPIEZA:", report["cleanup"], file=sys.stderr)
        for r in report["bursts"]:
            r.get("instance", {}).pop("samples", None)
        (out / "resultado.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Resultado en perf/results/login-burst-aws/resultado.json · detenida por: {report['stopped_reason'] or 'ninguna'}")
        sys.exit(0 if not report["stopped_reason"] and report.get("fingerprint_identical") else 1)


if __name__ == "__main__":
    main()
