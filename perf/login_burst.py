#!/usr/bin/env python3
"""Ráfagas de inicios de sesión SIMULTÁNEOS contra la API en un contenedor LOCAL con memoria limitada y 2 workers (sin AWS).

Emula el límite práctico de la EC2 t3.small (contenedor con tope de memoria, por defecto 1536 MB y 8 CPUs del VM de Docker) y una
base PostgreSQL desechable en el Compose local. Mide por tamaño de ráfaga: latencia p50/p95/p99/máx del login, logins/s, errores,
memoria máxima del contenedor (cgroup) y muertes por falta de memoria (OOM). Reproduce el riesgo visto en AWS: Argon2 usa ~64 MiB por
operación y cada worker puede ejecutar hasta 40 a la vez.
Uso: python3 perf/login_burst.py --label antes [--sizes 10,20,50] [--rounds 3] [--memory-mb 1536] [--max-concurrent N]
  --max-concurrent N  exporta ARGON2_MAX_CONCURRENT=N a la API (solo tiene efecto si el código lo soporta).
Requiere: docker compose del proyecto; reconstruye la imagen del backend con el código actual.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DB, PORT, NAME = "nexoeventos_burst", 8032, "nexo-burst-api"
BASE = f"http://127.0.0.1:{PORT}"
HEADERS = {"Origin": "http://localhost:5173"}
PASSWORD = "Ensayo-local-ráfaga-1234"
NETWORK = "nexoeventos-dev_default"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def cg(path: str) -> str:
    return run(["docker", "exec", NAME, "cat", path]).stdout.strip()


class Sampler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop_flag, self.mem = threading.Event(), []

    def run(self) -> None:
        while not self.stop_flag.is_set():
            value = cg("/sys/fs/cgroup/memory.current")
            if value.isdigit():
                self.mem.append(int(value) / 2**20)
            self.stop_flag.wait(0.02)


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def oom_kills() -> int:
    for line in cg("/sys/fs/cgroup/memory.events").splitlines():
        if line.startswith("oom_kill "):
            return int(line.split()[1])
    return 0


def container_state() -> str:
    """Estado del contenedor: si el proceso principal murió por falta de memoria, Docker lo marca como OOMKilled."""
    return run(["docker", "inspect", "-f", "{{.State.Status}} oom={{.State.OOMKilled}} exit={{.State.ExitCode}}", NAME]).stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--sizes", default="10,20,50")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--memory-mb", type=int, default=1536)
    ap.add_argument("--max-concurrent", type=int, default=None)
    args = ap.parse_args()
    sizes = [int(x) for x in args.sizes.split(",")]
    env_file = ROOT / ".env"
    if not env_file.exists():
        sys.exit("Falta .env local: ejecuta scripts/docker-dev.sh up una vez.")
    key = next(l.split("=", 1)[1].strip() for l in env_file.read_text().splitlines() if l.startswith("TICKET_ENCRYPTION_KEY="))
    compose = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
    print("Preparando base desechable y construyendo la imagen con el código actual…", flush=True)
    run(compose + ["up", "-d", "db"], cwd=ROOT)
    for _ in range(60):
        if run(["docker", "exec", "nexoeventos-dev-db-1", "pg_isready", "-U", "postgres"]).returncode == 0:
            break
        time.sleep(1)
    run(["docker", "exec", "nexoeventos-dev-db-1", "psql", "-U", "postgres", "-q", "-c", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)", "-c", f"CREATE DATABASE {DB} OWNER nexoeventos_owner", "-c", f"GRANT CONNECT ON DATABASE {DB} TO nexoeventos_app"])
    build = run(compose + ["build", "backend"], cwd=ROOT)
    if build.returncode:
        sys.exit(f"Falló la construcción de la imagen: {build.stderr[-300:]}")
    mig = run(["docker", "run", "--rm", "--network", NETWORK, "-e", f"MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:dev-local-only-admin@db:5432/{DB}", "nexoeventos-dev-backend", "alembic", "upgrade", "head"])
    if mig.returncode:
        sys.exit(f"No se pudo migrar: {mig.stderr[-300:]}")
    run(["docker", "rm", "-f", NAME])
    env = ["-e", f"DATABASE_URL=postgresql+psycopg://nexoeventos_app:dev-local-only-app@db:5432/{DB}", "-e", f"TICKET_ENCRYPTION_KEY={key}", "-e", "FRONTEND_ORIGINS=http://localhost:5173", "-e", "APP_ENV=development"]
    if args.max_concurrent is not None:
        env += ["-e", f"ARGON2_MAX_CONCURRENT={args.max_concurrent}"]
    start = run(["docker", "run", "-d", "--name", NAME, "--network", NETWORK, "--memory", f"{args.memory_mb}m", "--memory-swap", f"{args.memory_mb}m", "-p", f"127.0.0.1:{PORT}:8000", *env,
                 "nexoeventos-dev-backend", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", str(args.workers)])
    if start.returncode:
        sys.exit(f"No arrancó la API: {start.stderr[-300:]}")
    result = {"schema": 1, "label": args.label, "environment": {"container_memory_limit_mb": args.memory_mb, "workers": args.workers, "docker_vm_cpus": 8, "argon2": "pwdlib recommended: Argon2id m=64 MiB, t=3, p=4",
                                                                  "max_concurrent_env": args.max_concurrent, "note": "Contenedor local con tope de memoria; compara antes/después, no equivale a la t3.small."}, "bursts": []}
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{BASE}/ready", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        users = [f"rafaga-{i}@example.com" for i in range(max(sizes))]
        with httpx.Client(base_url=BASE, headers=HEADERS, timeout=60) as c:
            for email in users:
                assert c.post("/api/auth/register", json={"email": email, "display_name": "Ráfaga", "password": PASSWORD}).status_code == 201, "registro"
        sampler = Sampler()
        sampler.start()
        time.sleep(1.0)
        for size in sizes:
            lat_all, errors, walls, peaks, idle, codes_seen = [], 0, [], [], [], {}
            ooms0 = oom_kills()
            for _ in range(args.rounds):
                time.sleep(3)
                n0 = len(sampler.mem)
                idle.append(sampler.mem[-1] if sampler.mem else 0)
                barrier = threading.Barrier(size)
                clients = [httpx.Client(base_url=BASE, headers=HEADERS, timeout=120) for _ in range(size)]
                lat, codes = [0.0] * size, [0] * size

                def one(i: int) -> None:
                    barrier.wait()
                    t = time.perf_counter()
                    try:
                        resp = clients[i].post("/api/auth/login", json={"email": users[i], "password": PASSWORD})
                        codes[i] = resp.status_code
                    except httpx.HTTPError:
                        codes[i] = -1  # conexión cortada (p. ej. proceso muerto por falta de memoria)
                    lat[i] = (time.perf_counter() - t) * 1000

                t0 = time.perf_counter()
                with ThreadPoolExecutor(size) as pool:
                    list(pool.map(one, range(size)))
                walls.append(time.perf_counter() - t0)
                time.sleep(0.3)
                for c in clients:
                    c.close()
                lat_all += lat
                errors += sum(1 for c in codes if c != 200)
                for c in codes:
                    codes_seen[str(c)] = codes_seen.get(str(c), 0) + 1
                peaks.append(max(sampler.mem[n0:] or [0]))
                if errors:
                    for _ in range(50):  # espera a que el worker reinicie tras un OOM
                        try:
                            if httpx.get(f"{BASE}/ready", timeout=1).status_code == 200:
                                break
                        except httpx.HTTPError:
                            time.sleep(0.5)
            burst = {"size": size, "rounds": args.rounds, "logins": len(lat_all), "errors": errors, "status_codes": codes_seen, "container": container_state(), "oom_kills": oom_kills() - ooms0,
                     "latency_ms": {"p50": round(pct(lat_all, .5)), "p95": round(pct(lat_all, .95)), "p99": round(pct(lat_all, .99)), "max": round(max(lat_all))},
                     "throughput_logins_per_s": round(size / statistics.mean(walls), 1), "burst_wall_s": round(statistics.mean(walls), 2),
                     "mem_idle_mb": round(statistics.mean(idle)), "mem_peak_mb": round(max(peaks)), "mem_peak_delta_mb": round(max(peaks) - statistics.mean(idle))}
            result["bursts"].append(burst)
            print(f"  {size:>2} simultáneos: p50 {burst['latency_ms']['p50']} / p95 {burst['latency_ms']['p95']} / p99 {burst['latency_ms']['p99']} ms · {burst['throughput_logins_per_s']} logins/s · memoria pico {burst['mem_peak_mb']} MB (+{burst['mem_peak_delta_mb']}) · errores {errors} {codes_seen} · contenedor: {burst['container']}", flush=True)
        sampler.stop_flag.set()
    finally:
        run(["docker", "rm", "-f", NAME])
        run(["docker", "exec", "nexoeventos-dev-db-1", "psql", "-U", "postgres", "-q", "-c", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"])
    out = ROOT / "perf" / "results" / f"login-burst-{args.label}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "resultado.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Resultado en perf/results/login-burst-{args.label}/resultado.json")


if __name__ == "__main__":
    main()
