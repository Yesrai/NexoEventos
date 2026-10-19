#!/usr/bin/env python3
"""Verifica directamente en PostgreSQL la integridad de reservas tras una prueba (solo base local aislada).

Cada comprobación cuenta VIOLACIONES (0 = correcto). Salida JSON; código 1 si hay alguna violación.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlparse

import psycopg

DEFAULT_URL = "postgresql://postgres:dev-local-only-admin@127.0.0.1:55432/nexoeventos"

CHECKS = {
    "asiento_con_mas_de_una_entrada": "SELECT count(*) FROM (SELECT seat_id FROM tickets WHERE seat_id IS NOT NULL GROUP BY seat_id HAVING count(*) > 1) x",
    "asiento_ocupado_sin_entrada": "SELECT count(*) FROM event_seats s WHERE s.reservation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.seat_id = s.id AND t.reservation_id = s.reservation_id)",
    "entrada_con_asiento_no_marcado_ocupado": "SELECT count(*) FROM tickets t JOIN event_seats s ON s.id = t.seat_id WHERE s.reservation_id IS DISTINCT FROM t.reservation_id OR s.event_id <> t.event_id",
    "reservas_con_cantidad_distinta_de_entradas": "SELECT count(*) FROM reservations r WHERE r.quantity <> (SELECT count(*) FROM tickets t WHERE t.reservation_id = r.id)",
    "reservas_sin_entradas": "SELECT count(*) FROM reservations r WHERE NOT EXISTS (SELECT 1 FROM tickets t WHERE t.reservation_id = r.id)",
    "entradas_sin_reserva_del_mismo_evento": "SELECT count(*) FROM tickets t LEFT JOIN reservations r ON r.id = t.reservation_id WHERE r.id IS NULL OR r.event_id <> t.event_id",
    "evento_con_contador_distinto_de_entradas": "SELECT count(*) FROM events e WHERE e.reserved_count <> (SELECT count(*) FROM tickets t WHERE t.event_id = e.id)",
    "evento_vendido_por_encima_del_aforo": "SELECT count(*) FROM events WHERE reserved_count > capacity",
    "zona_con_contador_distinto_de_entradas": "SELECT count(*) FROM event_zones z WHERE z.reserved_count <> (SELECT count(*) FROM tickets t WHERE t.zone_id = z.id)",
    "zona_vendida_por_encima_del_aforo": "SELECT count(*) FROM event_zones WHERE reserved_count > capacity",
    "claves_de_idempotencia_duplicadas": "SELECT count(*) FROM (SELECT idempotency_key FROM reservations GROUP BY idempotency_key HAVING count(*) > 1) x",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=DEFAULT_URL)
    parser.add_argument("--event-ids", help="Limita los totales informativos a estos eventos (coma)", default="")
    args = parser.parse_args()
    parsed = urlparse(args.database_url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Rechazado: solo se verifica la base local aislada.")
    with psycopg.connect(args.database_url) as connection, connection.cursor() as cur:
        violations = {}
        for name, query in CHECKS.items():
            cur.execute(query)
            violations[name] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM reservations")
        reservations = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM tickets")
        tickets = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM tickets WHERE seat_id IS NOT NULL")
        seat_tickets = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pg_indexes WHERE indexname LIKE 'tickets_seat_id_key' OR indexdef ILIKE '%UNIQUE%(seat_id)%'")
        seat_unique = cur.fetchone()[0] > 0
    result = {"violations": violations, "total_violations": sum(violations.values()), "totals": {"reservations": reservations, "tickets": tickets, "seat_tickets": seat_tickets}, "seat_unique_index_present": seat_unique}
    print(json.dumps(result))
    sys.exit(1 if result["total_violations"] else 0)


if __name__ == "__main__":
    main()
