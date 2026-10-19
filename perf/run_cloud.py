#!/usr/bin/env python3
"""Lanzador k6 para AWS V1: UN peldaño por ejecución, con guardas estrictas. NO se ejecuta sin autorización explícita.

Guardas (todas deben cumplirse):
  - NEXO_LOAD_TEST_APPROVED debe ser igual a --run-id (la autorización se escribe a propósito en cada ejecución);
  - host exactamente <nombre>.duckdns.org por HTTPS (o 127.0.0.1 con --local-rehearsal, solo para ensayar este lanzador);
  - máximo 50 usuarios virtuales y 30 min por invocación; el peldaño se corta solo si p95 > 2 s o errores > 1 %;
  - los datos de reserva solo existen en los eventos 90001-90004 (perf/cloud_fixture.py up) y los usuarios k6-<run>-N.
La integridad (perf/check_integrity.py) se ejecuta en la EC2 con la identidad migradora; aquí queda marcada como pendiente.
Uso: NEXO_LOAD_TEST_APPROVED=<run-id> python3 perf/run_cloud.py --base-url https://x.duckdns.org --run-id <run-id> --step 10
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
K6_IMAGE = "grafana/k6:2.3.0"
STEPS = {"smoke": (1, 60), "10": (10, 120), "20": (20, 150), "40": (40, 150), "50": (50, 120)}  # (usuarios, segundos de meseta)
ALL = ["catalog", "detail", "availability", "reserve", "same_seat"]
CHOICES = ALL + ["mix"]  # mix: perfil mixto (30 % catálogo, 25 % detalle, 20 % disponibilidad, 25 % reserva) con exactamente N usuarios
MAX_TOTAL_SECONDS = 30 * 60
DISPUTE_SEATS = 20
HOST_RE = re.compile(r"^[a-z0-9-]+\.duckdns\.org$")


def scenario_seconds(scenario: str, hold: int, vus: int = 10) -> int:
    if scenario == "same_seat":
        return 180
    setup = 10 + int(vus * 0.6) if scenario in {"reserve", "mix"} else 5  # registro de usuarios ficticios (Argon2)
    return 30 + hold + 5 + setup  # rampa + meseta + bajada + preparación


def validate(args: argparse.Namespace) -> tuple[str, str, str]:
    """Devuelve (url para el Mac, url para k6, origen). Sale con error si alguna guarda falla."""
    if os.environ.get("NEXO_LOAD_TEST_APPROVED") != args.run_id:
        sys.exit("Rechazado: NEXO_LOAD_TEST_APPROVED debe ser exactamente el --run-id autorizado.")
    if not re.fullmatch(r"[a-z0-9]{4,16}", args.run_id):
        sys.exit("Rechazado: --run-id debe ser alfanumérico en minúsculas (4-16).")
    url = urlparse(args.base_url)
    if args.local_rehearsal:
        if url.hostname not in {"127.0.0.1", "localhost"}:
            sys.exit("Rechazado: --local-rehearsal solo admite 127.0.0.1.")
        return args.base_url, f"http://host.docker.internal:{url.port}", "http://localhost:5173"
    if url.scheme != "https" or not url.hostname or not HOST_RE.match(url.hostname) or url.path not in ("", "/") or url.port:
        sys.exit("Rechazado: la URL debe ser https://<nombre>.duckdns.org sin puerto ni ruta.")
    return args.base_url.rstrip("/"), args.base_url.rstrip("/"), f"https://{url.hostname}"


def precheck_fixture(host_url: str, scenario: str) -> None:
    """Lectura previa: el fixture existe y, para la disputa, sus 20 asientos siguen libres (se consumen en cada ejecución)."""
    if scenario not in {"reserve", "same_seat", "mix"}:
        return
    for event_id in (90001, 90002, 90003, 90004):
        try:
            detail = json.loads(urllib.request.urlopen(f"{host_url}/api/events/{event_id}", timeout=15).read())
        except Exception:
            sys.exit(f"Falta el fixture del evento {event_id}: ejecutar perf/cloud_fixture.py up (autorizado) antes de {scenario}.")
        if scenario == "same_seat" and event_id == 90004 and not all(seat["available"] for seat in detail["seats"]):
            sys.exit("Los asientos de la disputa (90004) ya se usaron: recrear el fixture (cloud_fixture.py up) antes de repetir same_seat.")


def run_one(scenario: str, vus: int, hold: int, k6_base: str, origin: str, run_id: str) -> dict:
    script = (ROOT / "perf" / "k6" / "nexo.js").read_text(encoding="utf-8")
    started = datetime.now(timezone.utc)
    cmd = ["docker", "run", "--rm", "-i", "--add-host=host.docker.internal:host-gateway", K6_IMAGE, "run", "--quiet",
           "-e", f"BASE_URL={k6_base}", "-e", f"ORIGIN={origin}", "-e", f"SCENARIO={scenario}", "-e", "PROFILE=step",
           "-e", f"STEP_VUS={vus}", "-e", f"STEP_SECONDS={hold}", "-e", f"RUN_ID={run_id}-{scenario.replace('_', '-')}", "-"]  # un conjunto de usuarios por escenario
    proc = subprocess.run(cmd, input=script, capture_output=True, text=True)
    ended = datetime.now(timezone.utc)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("K6SUMMARY ")), None)
    if not line:
        sys.exit(f"k6 no produjo resumen ({scenario}); revisa que el peldaño no haya abortado:\n{proc.stderr[-600:]}")
    k6 = json.loads(line[len("K6SUMMARY "):])
    c = k6["counters"]
    result = {
        "schema": 1, "scenario": scenario, "profile": "step", "started_at": started.isoformat(timespec="seconds"), "ended_at": ended.isoformat(timespec="seconds"),
        "duration_s": round(k6["duration_ms"] / 1000, 1), "vus_max": int((k6["vus_max"] or {}).get("max", 0)), "iterations": int(k6["iterations"]["count"]),
        "requests": int(k6["requests"]["count"]), "rps": round(k6["requests"]["rate"], 1),
        "latency_ms": {"p50": round(k6["latency_ms"]["med"], 1), "p95": round(k6["latency_ms"]["p(95)"], 1), "p99": round(k6["latency_ms"]["p(99)"], 1), "avg": round(k6["latency_ms"]["avg"], 1), "max": round(k6["latency_ms"]["max"], 1)},
        "latency_ms_by_name": {n: {"p50": round(v["med"], 1), "p95": round(v["p(95)"], 1), "p99": round(v["p(99)"], 1), "max": round(v["max"], 1)} for n, v in (k6.get("latency_by_name") or {}).items() if v and v.get("max", 0) > 0},
        "latency_ms_by_op": {op: {"p50": round(v["med"], 1), "p95": round(v["p(95)"], 1), "p99": round(v["p(99)"], 1), "max": round(v["max"], 1)} for op, v in (k6.get("latency_by_op") or {}).items() if v and v.get("max", 0) > 0},
        "unexpected_errors": c["errores_inesperados"], "failed_request_rate": round(k6["failed_rate"]["rate"], 4),
        "reservations": {"created": c["reservas_ok"], "idempotent_replays": c["reservas_repetidas_idempotentes"], "expected_conflicts": c["conflictos_esperados"]},
        "checks": {"passed": int(k6["checks"]["passes"]) if k6["checks"] else 0, "failed": int(k6["checks"]["fails"]) if k6["checks"] else 0},
        "k6_thresholds": k6["thresholds"], "k6_exit_code": proc.returncode,
        "metrics_window_utc": [started.isoformat(timespec="seconds"), ended.isoformat(timespec="seconds")],  # para consultar CloudWatch con esta ventana
    }
    verdict = {"k6_thresholds_ok": all(k6["thresholds"].values()), "checks_ok": result["checks"]["failed"] == 0}
    if scenario == "same_seat":
        attempts = c["intentos_mismo_asiento"]
        result["same_seat"] = {"seats_contested": DISPUTE_SEATS, "attempts": attempts, "winners": c["reservas_ok"], "rejected_409": c["conflictos_esperados"]}
        verdict["one_winner_per_seat"] = c["reservas_ok"] == DISPUTE_SEATS and c["conflictos_esperados"] == attempts - DISPUTE_SEATS
    result["verdict"] = verdict
    result["passed"] = all(verdict.values())
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--step", choices=list(STEPS), required=True)
    parser.add_argument("--scenarios", default=",".join(ALL))
    parser.add_argument("--hold", type=int, default=None, help="solo con --local-rehearsal: acorta la meseta para ensayar")
    parser.add_argument("--label", default=None)
    parser.add_argument("--local-rehearsal", action="store_true")
    parser.add_argument("--integrity-url", default=None, help="solo con --local-rehearsal: base desechable para verificar integridad aquí")
    parser.add_argument("--plan", action="store_true", help="muestra el plan y sale sin generar tráfico")
    args = parser.parse_args()
    scenarios = args.scenarios.split(",")
    if not set(scenarios) <= set(CHOICES):
        sys.exit("Escenario desconocido.")
    vus, hold = STEPS[args.step]
    if args.hold is not None:
        if not args.local_rehearsal:
            sys.exit("--hold solo se admite con --local-rehearsal.")
        hold = args.hold
    total = sum(scenario_seconds(s, hold, vus) for s in scenarios)
    if vus > 50 or total > MAX_TOTAL_SECONDS:
        sys.exit(f"Rechazado: {vus} usuarios / {total} s superan el límite (50 usuarios, {MAX_TOTAL_SECONDS} s).")
    host_url, k6_base, origin = validate(args)
    print(f"Plan: {args.step} → {vus} usuarios, meseta {hold} s, escenarios {scenarios}, ≈ {total // 60} min {total % 60} s máximos, destino {urlparse(host_url).hostname}")
    if args.plan:
        return
    label = args.label or f"aws-v1-{args.run_id}-{args.step}"
    outdir = ROOT / "perf" / "results" / label
    outdir.mkdir(parents=True, exist_ok=True)
    results = []
    for scenario in scenarios:
        print(f"▶ {scenario}", flush=True)
        precheck_fixture(host_url, scenario)
        r = run_one(scenario, vus, hold, k6_base, origin, args.run_id)
        if scenario in {"reserve", "same_seat", "mix"}:
            if args.local_rehearsal and args.integrity_url:
                proc = subprocess.run([sys.executable, str(ROOT / "perf" / "check_integrity.py"), "--database-url", args.integrity_url, "--event-ids", "90001,90002,90003,90004"], capture_output=True, text=True)
                r["integrity"] = json.loads(proc.stdout.strip().splitlines()[-1])
                r["verdict"]["integrity_ok"] = r["integrity"]["total_violations"] == 0
                r["passed"] = all(r["verdict"].values())
            else:
                r["integrity"] = {"status": "pendiente: ejecutar perf/check_integrity.py en la EC2 con la identidad migradora antes de dar el peldaño por válido"}
        (outdir / f"{scenario}.json").write_text(json.dumps(r, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        results.append(r)
        print(f"   {r['vus_max']} VUs · {r['rps']} req/s · p50 {r['latency_ms']['p50']} / p95 {r['latency_ms']['p95']} / p99 {r['latency_ms']['p99']} ms · errores {r['unexpected_errors']} · {'OK' if r['passed'] else 'FALLÓ'}", flush=True)
        if not r["passed"]:
            print("Peldaño no superado: no se continúa con más escenarios ni se sube de peldaño.")
            break
    summary = {"schema": 1, "label": label, "profile": "step", "step": args.step,
               "environment": {"kind": "local-rehearsal" if args.local_rehearsal else "aws-v1", "k6": K6_IMAGE, "generator": "Mac del autor, vía Internet" if not args.local_rehearsal else "Mac local"},
               "results": {r["scenario"]: {k: r[k] for k in ("vus_max", "rps", "latency_ms", "latency_ms_by_name", "latency_ms_by_op", "unexpected_errors", "reservations", "passed", "metrics_window_utc")} for r in results}}
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Resultados en perf/results/{label}/")
    sys.exit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()
