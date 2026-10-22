-- Huella de datos para comparar un respaldo restaurado con su línea base (mismas consultas usadas en las verificaciones AWS).
SELECT 'alembic='||version_num FROM alembic_version
UNION ALL SELECT 'users='||count(*) FROM users
UNION ALL SELECT 'events='||count(*) FROM events
UNION ALL SELECT 'reservations='||count(*) FROM reservations
UNION ALL SELECT 'tickets='||count(*) FROM tickets
UNION ALL SELECT 'operator_assignments='||count(*) FROM operator_event_assignments
UNION ALL SELECT 'access_logs='||count(*) FROM access_logs
UNION ALL SELECT 'reserved_total='||coalesce(sum(reserved_count),0) FROM events
UNION ALL SELECT 'inventory_md5='||md5(coalesce(string_agg(id||':'||capacity||':'||reserved_count, ',' ORDER BY id),'')) FROM events
UNION ALL SELECT 'reservations_md5='||md5(coalesce(string_agg(id::text, ',' ORDER BY id::text),'')) FROM reservations;
