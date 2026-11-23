-- Datos FICTICIOS solo para el laboratorio local. Evento 990001 (asientos asignados, 1 zona, 40 asientos) y 990002 (general, 20 cupos).
BEGIN;
INSERT INTO events (id, name, event_date, event_time, venue, city, category, description, price, capacity, reserved_count, ticket_mode, is_demo, status)
VALUES (990001, '[LAB] Evento asignado', current_date + 30, '20:00', 'Sede ficticia', 'Lima', 'Prueba', 'Evento ficticio del laboratorio de failover.', 50, 40, 0, 'seats', true, 'published'),
       (990002, '[LAB] Evento general', current_date + 30, '20:00', 'Sede ficticia', 'Lima', 'Prueba', 'Evento ficticio del laboratorio de failover.', 30, 20, 0, 'general', true, 'published');
INSERT INTO event_zones (event_id, name, price, capacity, reserved_count) VALUES (990001, 'Platea', 50, 40, 0);
INSERT INTO event_seats (event_id, zone_id, row_label, seat_number)
SELECT 990001, z.id, r, n FROM event_zones z, unnest(ARRAY['A','B','C','D']) r, generate_series(1,10) n WHERE z.event_id = 990001;
COMMIT;
