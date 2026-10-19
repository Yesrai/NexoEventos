#!/usr/bin/env python3
"""Ejecuta los escenarios k6 contra la pila Docker LOCAL y aislada (scripts/docker-dev.sh up). Sin AWS.

Registra por escenario: VUs, solicitudes/s, latencias p50/p95/p99, errores inesperados, reservas y conflictos,
CPU/memoria de los contenedores e integridad verificada en PostgreSQL. Resultados ligeros en perf/results/<etiqueta>/.
Uso: python3 perf/run_local.py --profile smoke|progressive [--scenarios catalog,detail,...] [--label nombre]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_BASE = "http://127.0.0.1:8001"            # desde el Mac
K6_BASE = "http://host.docker.internal:8001"    # desde el contenedor de k6
K6_IMAGE = "grafana/k6:2.3.0"
CONTAINERS = {"backend": "nexoeventos-dev-backend-1", "db": "nexoeventos-dev-db-1"}
ALL = ["catalog", "detail", "availability", "reserve", "same_seat"]
SEEDED_VUS = {"smoke": {"catalog": 2, "detail": 2, "availability": 2, "reserve": 2, "same_seat": 5},
              "progressive": {"catalog": 50, "detail": 50, "availability": 50, "reserve": 40, "same_seat": 50}}
DISPUTE_SEATS = {"smoke": 3, "progressive": 20}
PY = str(ROOT / "backend" / ".venv" / "bin" / "python")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def to_mib(text: str) -> float:
    value, unit = re.match(r"([\d.]+)\s*([KMG]i?B)", text).groups()
    return float(value) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "kB": 1 / 1024, "MB": 1, "GB": 1024}[unit]


class Sampler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.samples: dict[str, list[tuple[float, float]]] = {name: [] for name in CONTAINERS}
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            out = run(["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}", *CONTAINERS.values()]).stdout
            for line in out.strip().splitlines():
                name, cpu, mem = line.split("|")
                key = next((k for k, v in CONTAINERS.items() if v == name), None)
                if key:
                    self.samples[key].append((float(cpu.strip("%")), to_mib(mem.split("/")[0].strip())))
            self.stop.wait(1.5)

    def summary(self) -> dict:
        result = {}
        for name, values in self.samples.items():
            if values:
                cpus, mems = [v[0] for v in values], [v[1] for v in values]
                result[name] = {"cpu_pct_avg": round(sum(cpus) / len(cpus), 1), "cpu_pct_max": round(max(cpus), 1), "mem_mib_max": round(max(mems), 1), "samples": len(values)}
        return result


def environment() -> dict:
    info = run(["docker", "info", "--format", "{{.NCPU}}|{{.MemTotal}}"]).stdout.strip().split("|")
    version = run(["docker", "exec", CONTAINERS["db"], "postgres", "--version"]).stdout.strip()
    return {"kind": "local-docker (isolated)", "docker_vm_cpus": int(info[0]), "docker_vm_mem_gib": round(int(info[1]) / 2**30, 1),
            "backend": "uvicorn, 1 worker, container read-only", "database": version, "k6": K6_IMAGE, "note": "Mac local; no equivale a t3.small ni a RDS."}


def precheck() -> None:
    try:
        urllib.request.urlopen(f"{HOST_BASE}/health", timeout=5).read()
    except Exception:
        sys.exit("El backend local no responde en 127.0.0.1:8001. Ejecuta: scripts/docker-dev.sh up")
    if run(["docker", "inspect", CONTAINERS["db"]]).returncode != 0:
        sys.exit("No encuentro la base local del Compose (nexoeventos-dev-db-1).")
    events = json.loads(urllib.request.urlopen(f"{HOST_BASE}/api/events", timeout=10).read())
    if len([e for e in events if e["id"] < 90000]) < 20:  # catálogo demo ficticio en la base local aislada
        seed = run([PY, str(ROOT / "scripts" / "seed-demo-catalog.py"), "--database-url", "postgresql+psycopg://postgres:dev-local-only-admin@127.0.0.1:55432/nexoeventos"])
        if seed.returncode != 0:
            sys.exit(f"No se pudo sembrar el catálogo demo local: {seed.stderr[-300:]}")


def integrity() -> dict:
    proc = run([PY, str(ROOT / "perf" / "check_integrity.py")])
    return json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {"error": proc.stderr[-300:]}


def one(scenario: str, profile: str, outdir: Path) -> dict:
    if scenario in {"reserve", "same_seat"}:
        fixture = run([PY, str(ROOT / "perf" / "fixture.py")])
        if fixture.returncode != 0:
            sys.exit(fixture.stderr or fixture.stdout)
    script = (ROOT / "perf" / "k6" / "nexo.js").read_text(encoding="utf-8")
    sampler = Sampler()
    sampler.start()
    started = datetime.now(timezone.utc)
    proc = subprocess.run(["docker", "run", "--rm", "-i", "--add-host=host.docker.internal:host-gateway", K6_IMAGE, "run", "--quiet",
                           "-e", f"BASE_URL={K6_BASE}", "-e", f"SCENARIO={scenario}", "-e", f"PROFILE={profile}", "-e", f"RUN_ID={uuid.uuid4().hex[:8]}", "-"],
                          input=script, capture_output=True, text=True)
    sampler.stop.set()
    sampler.join(timeout=5)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("K6SUMMARY ")), None)
    if not line:
        sys.exit(f"k6 no produjo resumen ({scenario}):\n{proc.stderr[-800:]}")
    k6 = json.loads(line[len("K6SUMMARY "):])
    counters = k6["counters"]
    result = {
        "schema": 1, "scenario": scenario, "profile": profile, "started_at": started.isoformat(timespec="seconds"),
        "duration_s": round(k6["duration_ms"] / 1000, 1), "vus_max": int(k6["vus_max"]["max"]), "iterations": int(k6["iterations"]["count"]),
        "requests": int(k6["requests"]["count"]), "rps": round(k6["requests"]["rate"], 1),
        "latency_ms": {"p50": round(k6["latency_ms"]["med"], 1), "p95": round(k6["latency_ms"]["p(95)"], 1), "p99": round(k6["latency_ms"]["p(99)"], 1), "avg": round(k6["latency_ms"]["avg"], 1), "max": round(k6["latency_ms"]["max"], 1)},
        "latency_ms_by_op": {op: {"p50": round(v["med"], 1), "p95": round(v["p(95)"], 1), "p99": round(v["p(99)"], 1), "max": round(v["max"], 1)} for op, v in (k6.get("latency_by_op") or {}).items() if v and v.get("max", 0) > 0},
        "unexpected_errors": counters["errores_inesperados"], "failed_request_rate": round(k6["failed_rate"]["rate"], 4),
        "reservations": {"created": counters["reservas_ok"], "idempotent_replays": counters["reservas_repetidas_idempotentes"], "expected_conflicts": counters["conflictos_esperados"]},
        "checks": {"passed": int(k6["checks"]["passes"]) if k6["checks"] else 0, "failed": int(k6["checks"]["fails"]) if k6["checks"] else 0},
        "resources": sampler.summary(), "k6_thresholds": k6["thresholds"], "k6_exit_code": proc.returncode,
    }
    observations = []
    login = result["latency_ms_by_op"].get("login")
    if login and login["p95"] > 2000:
        observations.append(f"Inicio de sesión p95 {login['p95']} ms con {result['vus_max']} inicios simultáneos (> 2000 ms): Argon2 con un solo worker; no afecta la integridad.")
    result["observations"] = observations
    verdict = {"k6_thresholds_ok": all(k6["thresholds"].values()), "checks_ok": result["checks"]["failed"] == 0}
    if scenario in {"reserve", "same_seat"}:
        result["integrity"] = integrity()
        verdict["integrity_ok"] = result["integrity"].get("total_violations") == 0
    if scenario == "same_seat":
        attempts = counters["intentos_mismo_asiento"]
        expected_ok = DISPUTE_SEATS[profile]
        result["same_seat"] = {"seats_contested": expected_ok, "attempts": attempts, "winners": counters["reservas_ok"], "rejected_409": counters["conflictos_esperados"]}
        verdict["one_winner_per_seat"] = counters["reservas_ok"] == expected_ok and counters["conflictos_esperados"] == attempts - expected_ok
    result["verdict"] = verdict
    result["passed"] = all(verdict.values())
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{scenario}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["smoke", "progressive"], default="smoke")
    parser.add_argument("--scenarios", default=",".join(ALL))
    parser.add_argument("--label", default=None)
    args = parser.parse_args()
    precheck()
    label = args.label or f"local-{args.profile}-{datetime.now().strftime('%Y%m%d-%H%M')}"
    outdir = ROOT / "perf" / "results" / label
    results = []
    for scenario in args.scenarios.split(","):
        print(f"▶ {scenario} ({args.profile})", flush=True)
        r = one(scenario, args.profile, outdir)
        results.append(r)
        res = r["resources"]
        by_op = r["latency_ms_by_op"]
        if by_op:
            print("   por operación: " + " · ".join(f"{op} p50 {v['p50']} / p95 {v['p95']} / p99 {v['p99']} ms" for op, v in by_op.items()), flush=True)
        print(f"   VUs {r['vus_max']} · {r['rps']} req/s · p50 {r['latency_ms']['p50']} / p95 {r['latency_ms']['p95']} / p99 {r['latency_ms']['p99']} ms · errores inesperados {r['unexpected_errors']} · "
              f"reservas {r['reservations']['created']} (+{r['reservations']['idempotent_replays']} repetidas) · conflictos {r['reservations']['expected_conflicts']} · "
              f"CPU backend {res.get('backend', {}).get('cpu_pct_max', '-')}% / mem {res.get('backend', {}).get('mem_mib_max', '-')} MiB · {'OK' if r['passed'] else 'FALLÓ'}", flush=True)
    previous = json.loads((outdir / "summary.json").read_text()) if (outdir / "summary.json").exists() else {"results": {}}
    summary = {"schema": 1, "label": label, "profile": args.profile, "environment": environment(), "results": {**previous["results"], **{r["scenario"]: {k: r[k] for k in ("vus_max", "rps", "latency_ms", "latency_ms_by_op", "unexpected_errors", "reservations", "passed")} for r in results}}}
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Resultados en perf/results/{label}/")
    sys.exit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()
