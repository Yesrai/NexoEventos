#!/usr/bin/env python3
"""Prueba de carga de NexoEventos con datos ficticios (solo biblioteca estándar).

Escenario E01 (objetivo, no resultado): 20 usuarios virtuales durante 5 minutos,
p95 < 2 s y errores inesperados < 1 %.

Cada usuario virtual registra una cuenta cliente ficticia (@example.com, contraseña
aleatoria en memoria) fuera de la ventana medida y luego mezcla:
  60 % GET /api/events, 25 % GET /api/events/{id}, 10 % GET /api/me/tickets
  y, solo si se indica --event-id, 5 % POST de reserva de 1 cupo con Idempotency-Key.
Las respuestas 409 por cupo agotado se cuentan como resultado de negocio, no error.

Seguridad:
- Contra un host que no sea localhost exige NEXO_LOAD_TEST_APPROVED=YES.
- Límites duros: 40 usuarios, 900 s.
- No guarda cookies, contraseñas, tokens ni cuerpos de respuesta.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import random
import secrets
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

MAX_VUS = 40
MAX_DURATION = 900
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.samples: list[tuple[str, int, float, str]] = []  # endpoint, status, seconds, category
        self.setup: list[tuple[int, float]] = []

    def add(self, endpoint: str, status: int, seconds: float, category: str) -> None:
        with self.lock:
            self.samples.append((endpoint, status, seconds, category))


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


class VirtualUser(threading.Thread):
    def __init__(self, idx: int, args: argparse.Namespace, run_id: str, rec: Recorder,
                 start_at: float, measure_at: float, stop_at: float, event_ids: list[int]) -> None:
        super().__init__(daemon=True)
        self.idx, self.args, self.run_id, self.rec = idx, args, run_id, rec
        self.start_at, self.measure_at, self.stop_at, self.event_ids = start_at, measure_at, stop_at, event_ids
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.rng = random.Random(f"{run_id}-{idx}")
        self.registered = False

    def csrf(self) -> str | None:
        for cookie in self.jar:
            if cookie.name == "nexoeventos_csrf":
                return cookie.value
        return None

    def request(self, method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, float]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.args.base_url + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        req.add_header("Origin", self.args.origin)
        req.add_header("User-Agent", f"nexoeventos-loadtest/{self.run_id}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        t0 = time.perf_counter()
        try:
            with self.opener.open(req, timeout=self.args.timeout) as resp:
                resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            exc.read()
            status = exc.code
        except Exception:  # timeout, conexión rechazada, TLS
            status = 0
        return status, time.perf_counter() - t0

    def register(self) -> None:
        email = f"carga-{self.run_id}-{self.idx:03d}@example.com"
        password = secrets.token_urlsafe(24)  # solo en memoria
        status, secs = self.request("POST", "/api/auth/register",
                                    {"email": email, "display_name": f"Carga {self.idx:03d}", "password": password})
        del password
        with self.rec.lock:
            self.rec.setup.append((status, secs))
        self.registered = status == 201

    def pick(self) -> str:
        r = self.rng.random()
        reserve = self.args.event_id is not None and self.registered
        if reserve and r < self.args.reserve_ratio:
            return "reserve"
        # Con reservas: 5 % reserva, 60 % lista, 25 % detalle, 10 % entradas.
        # Sin reservas, el 5 % se redistribuye a la lista: 65/25/10.
        list_limit = self.args.reserve_ratio + 0.60 if reserve else 0.65
        detail_limit = list_limit + 0.25
        if r < list_limit:
            return "events"
        if r < detail_limit:
            return "event_detail"
        return "my_tickets" if self.registered else "events"

    def run(self) -> None:
        time.sleep(max(0.0, self.start_at - time.time()))
        self.register()
        # Todos los usuarios empiezan a medir a la vez, después de rampa y registros.
        time.sleep(max(0.0, self.measure_at - time.time()))
        while time.time() < self.stop_at:
            action = self.pick()
            if action == "events":
                endpoint, (status, secs) = "GET /api/events", self.request("GET", "/api/events")
                cat = "ok" if status == 200 else "unexpected"
            elif action == "event_detail":
                eid = self.rng.choice(self.event_ids) if self.event_ids else 1
                endpoint, (status, secs) = "GET /api/events/{id}", self.request("GET", f"/api/events/{eid}")
                cat = "ok" if status == 200 else "unexpected"
            elif action == "my_tickets":
                endpoint, (status, secs) = "GET /api/me/tickets", self.request("GET", "/api/me/tickets")
                cat = "ok" if status == 200 else "unexpected"
            else:
                headers = {"Idempotency-Key": f"carga-{uuid.uuid4()}"}
                token = self.csrf()
                if token:
                    headers["X-CSRF-Token"] = token
                endpoint = "POST /api/events/{id}/reservations"
                status, secs = self.request("POST", f"/api/events/{self.args.event_id}/reservations", {"quantity": 1}, headers)
                cat = "ok" if status in (200, 201) else ("business" if status == 409 else "unexpected")
            self.rec.add(endpoint, status, secs, cat)
            time.sleep(self.rng.uniform(self.args.think_min, self.args.think_max))
        token = self.csrf()
        if self.registered and token:
            self.request("POST", "/api/auth/logout", headers={"X-CSRF-Token": token})


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True, help="p. ej. https://nexoeventos-demo.duckdns.org o http://localhost:8000")
    p.add_argument("--origin", default=None, help="origen permitido; por defecto coincide con base-url")
    p.add_argument("--vus", type=int, default=20)
    p.add_argument("--duration", type=int, default=300, help="segundos medidos")
    p.add_argument("--ramp", type=int, default=30, help="segundos para incorporar todos los usuarios")
    p.add_argument("--event-id", type=int, default=None, help="evento ficticio dedicado a carga; sin él no se reserva")
    p.add_argument("--reserve-ratio", type=float, default=0.05)
    p.add_argument("--think-min", type=float, default=1.0)
    p.add_argument("--think-max", type=float, default=3.0)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--out", default=None, help="directorio de salida (por defecto work/carga/<run>)")
    args = p.parse_args()
    args.base_url = args.base_url.rstrip("/")
    args.origin = (args.origin or args.base_url).rstrip("/")

    host = urllib.parse.urlparse(args.base_url).hostname or ""
    if host not in ("localhost", "127.0.0.1") and os.environ.get("NEXO_LOAD_TEST_APPROVED") != "YES":
        print("Prueba contra host remoto bloqueada: exporta NEXO_LOAD_TEST_APPROVED=YES con aprobación explícita.", file=sys.stderr)
        return 2
    if not (1 <= args.vus <= MAX_VUS and 10 <= args.duration <= MAX_DURATION):
        print(f"Límites: 1-{MAX_VUS} usuarios y 10-{MAX_DURATION} s.", file=sys.stderr)
        return 2
    if not (0.0 < args.reserve_ratio <= 0.10):
        print("--reserve-ratio debe estar entre 0 y 0.10.", file=sys.stderr)
        return 2
    if args.event_id is not None and abs(args.reserve_ratio - 0.05) > 1e-9:
        print("El escenario oficial con reservas exige --reserve-ratio 0.05.", file=sys.stderr)
        return 2

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S") + "-" + secrets.token_hex(2)
    out = Path(args.out) if args.out else PROJECT_ROOT / "work" / "carga" / run_id
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)

    try:
        with urllib.request.urlopen(args.base_url + "/api/events", timeout=args.timeout) as resp:
            events = json.loads(resp.read())
            event_ids = [e["id"] for e in events]
    except Exception as exc:
        print(f"No se pudo leer el catálogo inicial: {type(exc).__name__}", file=sys.stderr)
        return 1
    if args.event_id is not None:
        chosen = next((event for event in events if event.get("id") == args.event_id), None)
        if chosen is None or not str(chosen.get("name", "")).startswith("[CARGA]"):
            print("Las reservas de carga solo se permiten sobre un evento dedicado cuyo nombre empiece por [CARGA].", file=sys.stderr)
            return 2

    rec = Recorder()
    t_start = time.time()
    setup_window = 15.0  # margen para registros (Argon2) fuera de la ventana medida
    measure_at = t_start + args.ramp + setup_window
    stop_at = measure_at + args.duration
    users = []
    for i in range(args.vus):
        start_at = t_start + (args.ramp * i / max(1, args.vus))
        users.append(VirtualUser(i + 1, args, run_id, rec, start_at, measure_at, stop_at, event_ids))
    print(f"Ejecución {run_id}: {args.vus} usuarios, rampa {args.ramp} s, {args.duration} s medidos contra {host}")
    for u in users:
        u.start()
    for u in users:
        u.join()
    started = datetime.fromtimestamp(measure_at, timezone.utc)
    finished = datetime.fromtimestamp(stop_at, timezone.utc)

    samples = rec.samples
    lat = [s[2] for s in samples]
    by_cat = defaultdict(int)
    for s in samples:
        by_cat[s[3]] += 1
    total = len(samples)
    elapsed = float(args.duration)
    per_endpoint = {}
    groups = defaultdict(list)
    for s in samples:
        groups[s[0]].append(s)
    for ep, items in sorted(groups.items()):
        times = [i[2] for i in items]
        statuses = defaultdict(int)
        for i in items:
            statuses[str(i[1])] += 1
        per_endpoint[ep] = {"n": len(items), "p50_ms": round(percentile(times, 50) * 1000, 1),
                            "p95_ms": round(percentile(times, 95) * 1000, 1), "max_ms": round(max(times) * 1000, 1),
                            "estados": dict(statuses)}
    unexpected_pct = (by_cat["unexpected"] / total * 100) if total else 100.0
    p95 = percentile(lat, 95)
    registered_ok = sum(1 for s in rec.setup if s[0] == 201)
    setup_complete = registered_ok == args.vus
    official_scenario = args.vus == 20 and args.duration == 300
    summary = {
        "run_id": run_id, "objetivo": host, "inicio_utc": started.isoformat(timespec="seconds"),
        "fin_utc": finished.isoformat(timespec="seconds"), "usuarios": args.vus, "rampa_s": args.ramp,
        "duracion_medida_s": args.duration, "reservas_habilitadas": args.event_id is not None,
        "registros": {"ok": registered_ok, "total": len(rec.setup), "completos": setup_complete,
                      "p95_ms": round(percentile([s[1] for s in rec.setup], 95) * 1000, 1)},
        "solicitudes": total, "rps_promedio": round(total / elapsed, 2) if elapsed else 0,
        "latencia_ms": {"p50": round(percentile(lat, 50) * 1000, 1), "p95": round(p95 * 1000, 1),
                        "p99": round(percentile(lat, 99) * 1000, 1),
                        "media": round(statistics.mean(lat) * 1000, 1) if lat else 0},
        "categorias": dict(by_cat), "errores_inesperados_pct": round(unexpected_pct, 3),
        "por_endpoint": per_endpoint,
        "criterio_E01": {"escenario_20vu_300s": official_scenario,
                         "p95_menor_2s": p95 < 2.0, "errores_menor_1pct": unexpected_pct < 1.0,
                         "ejecucion_valida": setup_complete,
                         "resultado": (p95 < 2.0 and unexpected_pct < 1.0 and setup_complete)
                                      if official_scenario else None},
    }
    (out / "resumen.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    lines = [
        f"# Prueba de carga {run_id}", "",
        f"- Objetivo: `{host}`; ventana medida {summary['inicio_utc']} → {summary['fin_utc']} (UTC); registros y rampa previos no se incluyen.",
        f"- Usuarios virtuales: {args.vus}; rampa {args.ramp} s; ventana medida {args.duration} s; pensamiento {args.think_min}-{args.think_max} s.",
        f"- Reservas incluidas: {'sí, evento ficticio ' + str(args.event_id) if args.event_id else 'no'}.",
        f"- Registros ficticios: {summary['registros']['ok']}/{summary['registros']['total']} (p95 {summary['registros']['p95_ms']} ms, fuera de la ventana medida).",
        f"- Solicitudes medidas: {total}; promedio {summary['rps_promedio']} solicitudes/s.",
        f"- Latencia: p50 {summary['latencia_ms']['p50']} ms, p95 {summary['latencia_ms']['p95']} ms, p99 {summary['latencia_ms']['p99']} ms.",
        f"- Categorías: {dict(by_cat)}; errores inesperados {summary['errores_inesperados_pct']} %.",
        f"- Umbrales observados: p95 < 2 s {'SÍ' if p95 < 2.0 else 'NO'}; errores < 1 % {'SÍ' if unexpected_pct < 1.0 else 'NO'}.",
        f"- Validez del ensayo ({registered_ok}/{args.vus} registros listos antes de medir): {'VÁLIDO' if setup_complete else 'INVÁLIDO'}.",
        f"- E01 (requiere exactamente 20 VU × 300 s): "
        f"{'CUMPLE' if summary['criterio_E01']['resultado'] is True else 'NO CUMPLE' if summary['criterio_E01']['resultado'] is False else 'NO EVALUADO'}.",
        "", "| Endpoint | n | p50 ms | p95 ms | máx ms | estados |", "|---|---:|---:|---:|---:|---|",
    ]
    for ep, d in per_endpoint.items():
        lines.append(f"| `{ep}` | {d['n']} | {d['p50_ms']} | {d['p95_ms']} | {d['max_ms']} | {d['estados']} |")
    lines += ["", "Datos ficticios. Sin cookies, contraseñas, tokens QR ni cuerpos de respuesta. Medido desde el cliente: incluye red y TLS."]
    (out / "resumen.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nResultados: {out}")
    return 0 if setup_complete and p95 < 2.0 and unexpected_pct < 1.0 else 3


if __name__ == "__main__":
    sys.exit(main())
