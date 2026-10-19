#!/usr/bin/env python3
"""Genera (NO ejecuta) el SQL del fixture de carga y de su limpieza para la base de nube.

  cloud_fixture.py up     eventos ficticios 90001-90004 (recrea solo ese rango; aborta si hay algo ajeno a "[K6]")
  cloud_fixture.py down   borra el rango 90001-90099 y los usuarios k6-*@example.com; aborta si alguno tiene datos fuera del rango

No se conecta a ninguna base. Se ejecutaría en la EC2 con la identidad migradora (el rol de la aplicación no tiene DELETE
sobre users) mediante Session Manager, solo con autorización explícita. Cada script va en una transacción.
"""
import sys

GUARD = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM events WHERE id BETWEEN 90001 AND 90099 AND name NOT LIKE '[K6]%') THEN
    RAISE EXCEPTION 'El rango 90001-90099 contiene eventos ajenos al fixture; abortado sin cambios.';
  END IF;
END $$;
"""

WIPE = """
DELETE FROM access_logs WHERE event_id BETWEEN 90001 AND 90099;
DELETE FROM tickets WHERE event_id BETWEEN 90001 AND 90099;
UPDATE event_seats SET reservation_id = NULL WHERE event_id BETWEEN 90001 AND 90099;
DELETE FROM reservations WHERE event_id BETWEEN 90001 AND 90099;
DELETE FROM event_seats WHERE event_id BETWEEN 90001 AND 90099;
DELETE FROM event_zones WHERE event_id BETWEEN 90001 AND 90099;
DELETE FROM events WHERE id BETWEEN 90001 AND 90099;
"""

UP = """
INSERT INTO events (id, name, event_date, event_time, venue, city, category, description, price, capacity, reserved_count, image_path, ticket_mode, is_demo, status)
VALUES
 (90001, '[K6] General', current_date + 30, '20:00', 'Fixture k6', 'Lima', 'Conciertos', 'Evento ficticio para pruebas de carga.', 10, 1000000, 0, NULL, 'general', true, 'published'),
 (90002, '[K6] Zonas', current_date + 30, '20:00', 'Fixture k6', 'Lima', 'Conciertos', 'Evento ficticio para pruebas de carga.', 10, 2000000, 0, NULL, 'zones', true, 'published'),
 (90003, '[K6] Asientos (flujo)', current_date + 30, '20:00', 'Fixture k6', 'Lima', 'Conciertos', 'Evento ficticio para pruebas de carga.', 10, 2000, 0, NULL, 'seats', true, 'published'),
 (90004, '[K6] Disputa de asiento', current_date + 30, '20:00', 'Fixture k6', 'Lima', 'Conciertos', 'Evento ficticio para pruebas de carga.', 10, 20, 0, NULL, 'seats', true, 'published');
INSERT INTO event_zones (event_id, name, price, capacity, reserved_count) VALUES
 (90002, 'Campo', 20, 1000000, 0), (90002, 'Tribuna', 20, 1000000, 0), (90003, 'Platea', 20, 2000, 0), (90004, 'Unica', 20, 20, 0);
INSERT INTO event_seats (event_id, zone_id, row_label, seat_number)
SELECT z.event_id, z.id, 'R' || lpad(r::text, 3, '0'), n
FROM event_zones z, generate_series(1, CASE z.event_id WHEN 90003 THEN 200 ELSE 2 END) r, generate_series(1, 10) n
WHERE z.event_id IN (90003, 90004);
"""

DOWN_GUARD = """
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM reservations r JOIN users u ON u.id = r.user_id
    WHERE u.email LIKE 'k6-%@example.com' AND r.event_id NOT BETWEEN 90001 AND 90099
  ) THEN
    RAISE EXCEPTION 'Un usuario k6 tiene reservas fuera del rango del fixture; abortado sin cambios.';
  END IF;
END $$;
"""

DOWN_USERS = """
DELETE FROM users u WHERE u.email LIKE 'k6-%@example.com' AND u.role = 'client'
  AND NOT EXISTS (SELECT 1 FROM reservations r WHERE r.user_id = u.id)
  AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.owner_user_id = u.id OR t.used_by_user_id = u.id);
"""


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"up", "down"}:
        sys.exit("Uso: cloud_fixture.py up|down")
    body = GUARD + WIPE + UP if sys.argv[1] == "up" else GUARD + DOWN_GUARD + WIPE + DOWN_USERS
    print("BEGIN;" + body + "COMMIT;")


if __name__ == "__main__":
    main()
