#!/usr/bin/env bash
# Huella de datos transaccionales de una BASE DESECHABLE local (contenedor nexo-rehearsal). Solo lectura.
set -euo pipefail
[[ "${REHEARSAL_CONTAINER:-nexo-rehearsal}" == nexo-rehearsal* ]] || { echo "Solo contenedores de ensayo." >&2; exit 2; }
docker exec -i "${REHEARSAL_CONTAINER:-nexo-rehearsal}" psql -U postgres -d "${REHEARSAL_DB:-nexoeventos}" -At <<'SQL'
select 'alembic', version_num from alembic_version;
select 'reservations', count(*), md5(coalesce(string_agg(r::text, '|' order by r.id::text), '')) from reservations r;
select 'tickets', count(*), md5(coalesce(string_agg(t::text, '|' order by t.id::text), '')) from tickets t;
select 'users', count(*), md5(coalesce(string_agg(u::text, '|' order by u.id), '')) from users u;
select 'event_seats', count(*), md5(coalesce(string_agg(s::text, '|' order by s.id), '')) from event_seats s;
select 'inventario_con_reservas', md5(coalesce(string_agg(e.id || ':' || e.reserved_count || ':' || e.capacity, '|' order by e.id), '')) from events e where e.id in (select event_id from reservations);
SQL
