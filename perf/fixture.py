#!/usr/bin/env python3
"""Fixture de pruebas de carga (ids 90001-90004) SOLO en la base local aislada del Compose.

Crea eventos ficticios con cupos enormes (no se agotan) y un evento de 20 asientos para la disputa del mismo asiento.
Rechaza cualquier base que no sea localhost:55432. Los ids 90001-90099 se borran y recrean en cada ejecución.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, time, timedelta
from urllib.parse import urlparse

import psycopg

DEFAULT_URL = "postgresql://postgres:dev-local-only-admin@127.0.0.1:55432/nexoeventos"


def guard(url: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432 or parsed.path != "/nexoeventos":
        raise SystemExit("Rechazado: el fixture solo se ejecuta contra la base local del Compose (127.0.0.1:55432/nexoeventos).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=DEFAULT_URL)
    args = parser.parse_args()
    guard(args.database_url)
    when = date.today() + timedelta(days=30)
    with psycopg.connect(args.database_url) as connection, connection.cursor() as cur:
        cur.execute("DELETE FROM access_logs WHERE event_id BETWEEN 90001 AND 90099")
        cur.execute("DELETE FROM tickets WHERE event_id BETWEEN 90001 AND 90099")
        cur.execute("UPDATE event_seats SET reservation_id = NULL WHERE event_id BETWEEN 90001 AND 90099")
        cur.execute("DELETE FROM reservations WHERE event_id BETWEEN 90001 AND 90099")
        cur.execute("DELETE FROM event_seats WHERE event_id BETWEEN 90001 AND 90099")
        cur.execute("DELETE FROM event_zones WHERE event_id BETWEEN 90001 AND 90099")
        cur.execute("DELETE FROM events WHERE id BETWEEN 90001 AND 90099")

        def event(event_id: int, name: str, mode: str, capacity: int) -> None:
            cur.execute(
                """INSERT INTO events (id, name, event_date, event_time, venue, city, category, description, price, capacity, reserved_count, image_path, ticket_mode, is_demo)
                   VALUES (%s, %s, %s, %s, 'Fixture k6', 'Lima', 'Conciertos', 'Evento ficticio para pruebas de carga.', 10, %s, 0, NULL, %s, true)""",
                (event_id, name, when, time(20, 0), capacity, mode),
            )

        def zone(event_id: int, name: str, capacity: int) -> int:
            cur.execute("INSERT INTO event_zones (event_id, name, price, capacity, reserved_count) VALUES (%s, %s, 20, %s, 0) RETURNING id", (event_id, name, capacity))
            return cur.fetchone()[0]

        def seats(event_id: int, zone_id: int, rows: int, per_row: int) -> None:
            for row in range(1, rows + 1):
                for number in range(1, per_row + 1):
                    cur.execute("INSERT INTO event_seats (event_id, zone_id, row_label, seat_number) VALUES (%s, %s, %s, %s)", (event_id, zone_id, f"R{row:03d}", number))

        event(90001, "[K6] General", "general", 1_000_000)
        event(90002, "[K6] Zonas", "zones", 2_000_000)
        zone(90002, "Campo", 1_000_000)
        zone(90002, "Tribuna", 1_000_000)
        event(90003, "[K6] Asientos (flujo)", "seats", 2_000)
        seats(90003, zone(90003, "Platea", 2_000), rows=200, per_row=10)
        event(90004, "[K6] Disputa de asiento", "seats", 20)
        seats(90004, zone(90004, "Unica", 20), rows=2, per_row=10)
    print("Fixture listo: 90001 general · 90002 zonas · 90003 asientos (2 000) · 90004 disputa (20 asientos)")


if __name__ == "__main__":
    main()
