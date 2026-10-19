#!/usr/bin/env python3
"""Verificación controlada de la versión PÚBLICA de AWS V1 con un evento y cuentas ficticias dedicadas.

Evento [ENSAYO] id 90101 (copia de la estructura del 1028): publicado pero con is_demo=false, por lo que NO aparece en el catálogo
público (que lista solo is_demo=true) y sigue siendo accesible por id. Cuentas ensayo-*@example.com. No toca reservas ni eventos
existentes; al terminar borra solo lo identificado por el id 90101 y el prefijo ensayo-, y compara una huella previa/posterior.

Requiere NEXO_ALLOW_CLOUD_CHANGES=YES y perfil AWS válido. No imprime contraseñas, cookies ni tokens QR.
Uso: python3 scripts/cloud/verify-controlled-flow.py [--out docs/evidencias/validacion-publica-AAAAMMDD]
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://nexoeventos-demo.duckdns.org"
EVENT = 90101
SOURCE = 1028
HEADERS = {"Origin": BASE}
MIG = 'set -euo pipefail; set -a; . /etc/nexoeventos/migration.env; set +a; DB_URL=${MIGRATION_DATABASE_URL/postgresql+psycopg:/postgresql:}\n'

FINGERPRINT = """
SELECT 'reservations='||count(*)||':'||md5(coalesce(string_agg(id::text, ',' ORDER BY id::text),'')) FROM reservations;
SELECT 'tickets='||count(*) FROM tickets;
SELECT 'users='||count(*) FROM users WHERE email NOT LIKE 'ensayo-%@example.com';
SELECT 'events='||count(*)||':'||md5(coalesce(string_agg(id||':'||capacity||':'||reserved_count||':'||status||':'||event_date, ',' ORDER BY id),'')) FROM events WHERE id <> 90101;
SELECT 'event_seats='||count(*)||' ocupados='||count(reservation_id) FROM event_seats WHERE event_id <> 90101;
SELECT 'zonas_reservadas='||coalesce(sum(reserved_count),0) FROM event_zones WHERE event_id <> 90101;
SELECT 'queue_entries='||count(*) FROM queue_entries WHERE event_id <> 90101;
SELECT 'access_logs='||count(*) FROM access_logs WHERE event_id <> 90101;
SELECT 'alembic='||version_num FROM alembic_version;
"""

SETUP = f"""BEGIN;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM events WHERE id = {EVENT}) THEN RAISE EXCEPTION 'El evento de ensayo ya existe'; END IF;
  IF NOT EXISTS (SELECT 1 FROM events WHERE id = {SOURCE}) THEN RAISE EXCEPTION 'Falta el evento origen'; END IF;
END $$;
INSERT INTO events (id, name, event_date, event_time, venue, city, category, description, price, capacity, reserved_count, image_path, ticket_mode, is_demo, status, venue_id, layout_id)
SELECT {EVENT}, '[ENSAYO] Verificación pública', event_date, event_time, venue, city, category, 'Evento ficticio de verificación; no es una función real.', price, capacity, 0, image_path, ticket_mode, false, 'published', venue_id, layout_id FROM events WHERE id = {SOURCE};
INSERT INTO event_zones (event_id, name, price, capacity, reserved_count) SELECT {EVENT}, name, price, capacity, 0 FROM event_zones WHERE event_id = {SOURCE};
INSERT INTO event_seats (event_id, zone_id, row_label, seat_number)
SELECT {EVENT}, nz.id, s.row_label, s.seat_number FROM event_seats s JOIN event_zones oz ON oz.id = s.zone_id JOIN event_zones nz ON nz.event_id = {EVENT} AND nz.name = oz.name WHERE s.event_id = {SOURCE};
COMMIT;"""

CLEANUP = f"""BEGIN;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM events WHERE id = {EVENT} AND name NOT LIKE '[ENSAYO]%') THEN RAISE EXCEPTION 'El id {EVENT} no es el evento de ensayo; abortado'; END IF;
  IF EXISTS (SELECT 1 FROM reservations r JOIN users u ON u.id = r.user_id WHERE r.event_id = {EVENT} AND u.email NOT LIKE 'ensayo-%@example.com') THEN RAISE EXCEPTION 'Hay reservas ajenas en el evento de ensayo; abortado'; END IF;
END $$;
DELETE FROM access_logs WHERE event_id = {EVENT} OR operator_user_id IN (SELECT id FROM users WHERE email LIKE 'ensayo-%@example.com');  -- incluye el intento denegado sobre otro evento
DELETE FROM tickets WHERE event_id = {EVENT};
UPDATE event_seats SET reservation_id = NULL WHERE event_id = {EVENT};
DELETE FROM reservations WHERE event_id = {EVENT};
DELETE FROM queue_entries WHERE event_id = {EVENT};
DELETE FROM event_seats WHERE event_id = {EVENT};
DELETE FROM event_zones WHERE event_id = {EVENT};
DELETE FROM events WHERE id = {EVENT} AND name LIKE '[ENSAYO]%';
DELETE FROM users u WHERE u.email LIKE 'ensayo-%@example.com' AND NOT EXISTS (SELECT 1 FROM reservations r WHERE r.user_id = u.id) AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.owner_user_id = u.id OR t.used_by_user_id = u.id);
COMMIT;"""


def ssm(sql: str, comment: str) -> str:
    iid = subprocess.check_output(["aws", "ec2", "describe-instances", "--filters", "Name=tag:Name,Values=nexoeventos-academy-app", "Name=instance-state-name,Values=running", "--query", "Reservations[0].Instances[0].InstanceId", "--output", "text"], text=True).strip()
    script = MIG + 'psql "$DB_URL" -v ON_ERROR_STOP=1 -At <<\'SQL\'\n' + sql + "\nSQL\n"
    cid = subprocess.check_output(["aws", "ssm", "send-command", "--instance-ids", iid, "--document-name", "AWS-RunShellScript", "--comment", comment, "--parameters", json.dumps({"commands": [script]}), "--timeout-seconds", "300", "--query", "Command.CommandId", "--output", "text"], text=True).strip()
    for _ in range(100):
        time.sleep(3)
        r = subprocess.run(["aws", "ssm", "get-command-invocation", "--command-id", cid, "--instance-id", iid, "--output", "json"], capture_output=True, text=True)
        if r.returncode:
            continue
        d = json.loads(r.stdout)
        if d["Status"] not in ("Pending", "InProgress", "Delayed"):
            if d["Status"] != "Success":
                raise RuntimeError(f"SSM {comment}: {d['Status']} {d['StandardErrorContent'][-300:]}")
            return d["StandardOutputContent"]
    raise RuntimeError("SSM timeout")


def check(results: list, name: str, ok: bool, detail: str = "") -> None:
    results.append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"{'OK   ' if ok else 'FALLÓ'} {name}{' — ' + detail if detail else ''}", flush=True)


class User:
    def __init__(self, label: str, run: str) -> None:
        self.email = f"ensayo-{label}-{run}@example.com"
        self.password = secrets.token_urlsafe(18)
        self.http = httpx.Client(base_url=BASE, headers=HEADERS, timeout=40)

    def csrf(self) -> dict:
        return {"X-CSRF-Token": self.http.cookies.get("nexoeventos_csrf", "")}

    def register(self) -> int:
        return self.http.post("/api/auth/register", json={"email": self.email, "display_name": "Ensayo ficticio", "password": self.password}).status_code

    def login(self) -> int:
        return self.http.post("/api/auth/login", json={"email": self.email, "password": self.password}).status_code

    def post(self, path: str, body: dict | None = None, key: bool = False):
        return self.http.post(path, json=body, headers={**self.csrf(), **({"Idempotency-Key": uuid.uuid4().hex} if key else {})})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "evidencias" / f"validacion-publica-{datetime.now().strftime('%Y%m%d')}"))
    parser.add_argument("--skip-ui", action="store_true")
    args = parser.parse_args()
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES":
        sys.exit("Requiere NEXO_ALLOW_CLOUD_CHANGES=YES (crea y borra datos de ensayo identificados).")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run = uuid.uuid4().hex[:8]
    results: list[dict] = []
    before = ssm(FINGERPRINT, "ensayo: huella previa (lectura)")
    created = False
    try:
        created = True  # la limpieza está protegida por nombre/prefijo y es idempotente: se intenta aunque la creación falle a medias
        ssm(SETUP, "ensayo: crear evento ficticio 90101")
        catalog = httpx.get(f"{BASE}/api/events", timeout=30).json()
        check(results, "El evento de ensayo NO aparece en el catálogo público", EVENT not in [e["id"] for e in catalog], f"{len(catalog)} eventos públicos")
        detail = httpx.get(f"{BASE}/api/events/{EVENT}", timeout=30).json()
        check(results, "El evento de ensayo es accesible por id con sus asientos y zonas", len(detail["seats"]) > 0 and len(detail["zones"]) > 0, f"{len(detail['seats'])} asientos, {len(detail['zones'])} zonas")
        client, operator = User("cli", run), User("op", run)
        check(results, "Registro de cuenta ficticia de cliente y de operador (201)", client.register() == 201 and operator.register() == 201)
        ssm(f"UPDATE users SET role='operator' WHERE email='{operator.email}' AND role='client';\nINSERT INTO operator_event_assignments (operator_user_id, event_id) SELECT id, {EVENT} FROM users WHERE email='{operator.email}';", "ensayo: asignar operador ficticio")
        check(results, "Inicio de sesión del cliente y de la operadora", client.login() == 200 and operator.login() == 200)
        check(results, "Sesión válida en 40 lecturas consecutivas (2 workers)", {client.http.get("/api/auth/session").status_code for _ in range(40)} == {200})
        seats = [s["id"] for s in detail["seats"] if s.get("available", True)][:2]
        key = uuid.uuid4().hex
        body = {"quantity": 2, "seat_ids": seats}
        r1 = client.http.post(f"/api/events/{EVENT}/reservations", json=body, headers={**client.csrf(), "Idempotency-Key": key})
        r2 = client.http.post(f"/api/events/{EVENT}/reservations", json=body, headers={**client.csrf(), "Idempotency-Key": key})
        check(results, "Reserva simulada de 2 asientos (201) y repetición idempotente (200, misma reserva)", r1.status_code == 201 and r2.status_code == 200 and r1.json()["reservation_id"] == r2.json()["reservation_id"], f"total {r1.json().get('total')}")
        mine = client.http.get("/api/me/reservations").json()
        tickets = client.http.get("/api/me/tickets").json()
        check(results, "Mis entradas: 1 reserva y 2 entradas con QR", len(mine) == 1 and len(tickets) == 2 and all(len(t["qr_token"]) >= 20 for t in tickets))
        tok = tickets[0]["qr_token"]
        v1 = operator.http.post("/api/operator/validate", json={"event_id": EVENT, "qr_token": tok}, headers=operator.csrf())
        v2 = operator.http.post("/api/operator/validate", json={"event_id": EVENT, "qr_token": tok}, headers=operator.csrf())
        check(results, "Validación por operadora asignada: aceptada la primera vez y rechazada la segunda (409)", v1.status_code == 200 and v2.status_code == 409, f"{v1.status_code}/{v2.status_code}")
        wrong = operator.http.post("/api/operator/validate", json={"event_id": 1028, "qr_token": tickets[1]["qr_token"]}, headers=operator.csrf())
        check(results, "La operadora no puede validar en un evento no asignado (403)", wrong.status_code == 403, str(wrong.status_code))
        check(results, "Un cliente no puede validar entradas (403)", client.http.post("/api/operator/validate", json={"event_id": EVENT, "qr_token": tickets[1]["qr_token"]}, headers=client.csrf()).status_code == 403)
        # fila virtual y disputa de asiento con cuentas ficticias
        ssm(f"UPDATE events SET queue_enabled=true, queue_max_active=2, queue_pass_minutes=10 WHERE id={EVENT};", "ensayo: activar fila virtual en el evento de ensayo")
        users = [User(f"q{i}", run) for i in range(5)]
        for u in users:
            assert u.register() == 201
        no_pass = users[0].http.post(f"/api/events/{EVENT}/reservations", json={"quantity": 1, "seat_ids": [seats[0]]}, headers={**users[0].csrf(), "Idempotency-Key": uuid.uuid4().hex})
        check(results, "Con fila activa, reservar sin turno se rechaza", no_pass.status_code in (403, 409, 423), str(no_pass.status_code))
        joined = []
        threads = [threading.Thread(target=lambda u=u: joined.append(u.post(f"/api/events/{EVENT}/queue").status_code)) for u in users]
        [t.start() for t in threads]; [t.join() for t in threads]
        states = [u.http.get(f"/api/events/{EVENT}/sales").json()["queue"] for u in users]
        admitted = [i for i, s in enumerate(states) if s["status"] == "admitted"]
        waiting = sorted(s["position"] for s in states if s["status"] == "waiting")
        check(results, "Fila virtual: 5 cuentas entran a la vez; 2 admitidas y 3 en espera con posiciones 1..3", set(joined) == {200} and len(admitted) == 2 and waiting == [1, 2, 3], f"admitidas={len(admitted)} posiciones={waiting}")
        free = next(s["id"] for s in httpx.get(f"{BASE}/api/events/{EVENT}", timeout=30).json()["seats"] if s.get("available", True))
        codes: list[int] = []
        threads = [threading.Thread(target=lambda u=u: codes.append(u.http.post(f"/api/events/{EVENT}/reservations", json={"quantity": 1, "seat_ids": [free]}, headers={**u.csrf(), "Idempotency-Key": uuid.uuid4().hex}).status_code)) for u in users]
        [t.start() for t in threads]; [t.join() for t in threads]
        check(results, "Disputa del mismo asiento: exactamente 1 ganador; el resto 409 o sin turno", codes.count(201) == 1 and all(c in (201, 409, 403, 423) for c in codes), str(sorted(codes)))
        if not args.skip_ui:
            env = {**os.environ, "E2E_BASE": BASE, "E2E_RUN": run, "E2E_CLIENT_PASSWORD": secrets.token_urlsafe(18), "PATH": "/opt/homebrew/opt/node@24/bin:" + os.environ["PATH"]}
            ui = subprocess.run(["node", str(ROOT / "scripts" / "cloud" / "verify-public-ui.mjs"), str(out / "ui")], env=env, capture_output=True, text=True)
            lines = [l for l in ui.stdout.splitlines() if l.startswith(("OK", "FALL", "Sin exc", "Excep"))]
            for l in lines:
                if l.startswith("Sin exc"):
                    check(results, "UI: sin excepciones de página", True)
                elif l.startswith("Excep"):
                    check(results, "UI: " + l, False)
                else:
                    check(results, "UI: " + l.split(" ", 1)[1].split(" — ")[0].strip()[:110], l.startswith("OK"))
            check(results, "UI pública: recorrido catálogo → 3D → registro sin excepciones", ui.returncode == 0)
    finally:
        if created:
            ssm(CLEANUP, "ensayo: limpieza del evento y cuentas ficticias")
        after = ssm(FINGERPRINT, "ensayo: huella posterior (lectura)")
        same = before == after
        check(results, "Limpieza: la huella del inventario, reservas, entradas y usuarios es idéntica a la previa", same)
        leftovers = ssm(f"SELECT 'evento='||count(*) FROM events WHERE id={EVENT}; SELECT 'cuentas='||count(*) FROM users WHERE email LIKE 'ensayo-%@example.com';", "ensayo: restos (lectura)").split()
        check(results, "No quedan evento ni cuentas de ensayo", leftovers == ["evento=0", "cuentas=0"], " ".join(leftovers))
        summary = {"schema": 1, "when_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "base": BASE, "run": run, "event_id": EVENT, "passed": all(r["ok"] for r in results), "results": results, "fingerprint_before": before.split(), "fingerprint_after": after.split()}
        (out / "resultado.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nResultado: {'TODO OK' if summary['passed'] else 'HAY FALLOS'} · evidencia en {out}")
        sys.exit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
