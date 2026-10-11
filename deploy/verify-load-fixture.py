#!/usr/bin/env python3
"""Prepara y verifica el evento aislado usado por la carga cloud.

Se ejecuta en la EC2 con MIGRATION_DATABASE_URL ya cargada. No imprime
credenciales, usuarios, reservas, entradas ni claves de idempotencia.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date

from sqlalchemy import create_engine, text


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser()
    sub = command.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--run-label", required=True)
    prepare.add_argument("--capacity", type=int, default=1000)
    verify = sub.add_parser("verify")
    verify.add_argument("--event-id", type=int, required=True)
    verify.add_argument("--expected-successes", type=int, required=True)
    return command


def main() -> int:
    args = parser().parse_args()
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("Falta MIGRATION_DATABASE_URL.")
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
    with engine.begin() as connection:
        connection.execute(text("SET ROLE nexoeventos_owner"))
        if args.action == "prepare":
            if not (100 <= args.capacity <= 5000):
                raise SystemExit("Capacidad fuera del rango seguro.")
            connection.execute(text("SELECT pg_advisory_xact_lock(1800000000)"))
            event_id = connection.scalar(text(
                "SELECT COALESCE(MAX(id), 1799999999) + 1 FROM events "
                "WHERE id BETWEEN 1800000000 AND 1899999999"
            ))
            if event_id > 1899999999:
                raise SystemExit("Se agotó el rango reservado para fixtures de carga.")
            name = f"[CARGA] AWS E01 {args.run_label}"
            connection.execute(text("""
                INSERT INTO events
                    (id, name, event_date, event_time, venue, city, category,
                     description, price, capacity, reserved_count, image_path,
                     ticket_mode, is_demo, organizer_user_id)
                VALUES
                    (:id, :name, :event_date, '19:00', 'Entorno académico AWS',
                     'Lima', 'Tecnología', 'Evento ficticio aislado para la prueba de carga E01.',
                     1.00, :capacity, 0, NULL, 'general', true, NULL)
            """), {"id": event_id, "name": name, "event_date": date(2026, 11, 25),
                    "capacity": args.capacity})
            result = {"fixture_id": event_id, "capacity": args.capacity,
                      "reserved_count": 0, "reservations": 0, "tickets": 0}
        else:
            row = connection.execute(text("""
                SELECT e.name, e.capacity, e.reserved_count,
                       COUNT(DISTINCT r.id) AS reservations,
                       COUNT(DISTINCT r.idempotency_key) AS idempotency_keys,
                       COALESCE(SUM(r.quantity), 0) AS reserved_quantity,
                       COUNT(DISTINCT t.id) AS tickets
                FROM events e
                LEFT JOIN reservations r ON r.event_id = e.id
                LEFT JOIN tickets t ON t.reservation_id = r.id
                WHERE e.id = :event_id
                GROUP BY e.id, e.name, e.capacity, e.reserved_count
            """), {"event_id": args.event_id}).mappings().one_or_none()
            if row is None or not row["name"].startswith("[CARGA]"):
                raise SystemExit("El fixture no existe o no es un evento [CARGA].")
            result = {key: int(row[key]) for key in (
                "capacity", "reserved_count", "reservations", "idempotency_keys",
                "reserved_quantity", "tickets"
            )}
            result["fixture_id"] = args.event_id
            result["expected_successes"] = args.expected_successes
            checks = {
                "sin_sobreventa": result["reserved_count"] <= result["capacity"],
                "contador_coincide": result["reserved_count"] == result["reserved_quantity"],
                "sin_idempotencias_duplicadas": result["reservations"] == result["idempotency_keys"],
                "una_entrada_por_cupo": result["tickets"] == result["reserved_quantity"],
                "exitos_medidos_coinciden": result["reserved_quantity"] == args.expected_successes,
            }
            result["checks"] = checks
            if not all(checks.values()):
                print(json.dumps(result, sort_keys=True))
                raise SystemExit(1)
    engine.dispose()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
