#!/usr/bin/env bash
# Permisos de la base RESTAURADA para el rol de la aplicación. Uso (como root en la VM, o con PSQL propio en pruebas):  db-permissions.sh readonly|readwrite
# ORDEN (defecto del 19-nov): 1) se eliminan los ajustes previos de solo lectura (idempotente: una reanudación no debe heredar el modo de un intento fallido) · 2) se conceden los permisos (GRANT)
# MIENTRAS la sesión aún permite escribir · 3) solo entonces se activa el modo de solo lectura · 4) se COMPRUEBA en sesiones NUEVAS (el ajuste solo rige en sesiones nuevas) que el rol puede leer y
# NO puede modificar nada. En readonly el rol solo recibe SELECT (sin INSERT/UPDATE/DELETE ni secuencias): aunque la aplicación (o alguien con el rol) desactivara default_transaction_read_only,
# los permisos de la base se lo seguirían impidiendo.
# Variables: PSQL (comando psql completo; por defecto «runuser -u postgres -- /usr/pgsql-18/bin/psql»), DB (nexoeventos), APPROLE (nexoeventos_app).
set -euo pipefail
MODE="${1:?readonly|readwrite}"; DB="${DB:-nexoeventos}"; ROLE="${APPROLE:-nexoeventos_app}"
[[ "$MODE" == readonly || "$MODE" == readwrite ]] || { echo "Modo inválido" >&2; exit 2; }
read -r -a P <<<"${PSQL:-runuser -u postgres -- /usr/pgsql-18/bin/psql}"
q() { "${P[@]}" -v ON_ERROR_STOP=1 -qAt "$@"; }
# 1) limpiar ajustes de solo lectura de un intento anterior (desde la base de mantenimiento, no desde la restaurada)
q -d postgres -c "ALTER DATABASE \"$DB\" RESET default_transaction_read_only" -c "ALTER ROLE \"$ROLE\" RESET default_transaction_read_only" >/dev/null
# 2) permisos (la sesión de administración NO está en solo lectura: sin ajustes en vigor)
if [[ "$MODE" == readonly ]]; then
  q -d "$DB" >/dev/null <<SQL
GRANT USAGE ON SCHEMA public TO "$ROLE";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO "$ROLE";
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM "$ROLE";
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM "$ROLE";
REVOKE CREATE ON SCHEMA public FROM "$ROLE";
SQL
else
  q -d "$DB" >/dev/null <<SQL
GRANT USAGE ON SCHEMA public TO "$ROLE";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "$ROLE";
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO "$ROLE";
SQL
fi
# 3) modo de solo lectura (segunda capa) DESPUÉS de los permisos
if [[ "$MODE" == readonly ]]; then
  q -d postgres -c "ALTER DATABASE \"$DB\" SET default_transaction_read_only = on" -c "ALTER ROLE \"$ROLE\" SET default_transaction_read_only = on" >/dev/null
fi
# 4) comprobación en sesiones NUEVAS, con la identidad del rol de la aplicación
as_role() { q -d "$DB" -c "SET ROLE \"$ROLE\"" "$@"; }
tab="$(q -d "$DB" -c "select relname from pg_class where relkind='r' and relnamespace='public'::regnamespace order by 1 limit 1")"
as_role -c "select count(*) from \"$tab\"" >/dev/null || { echo "FALLÓ: el rol de la aplicación no puede LEER" >&2; exit 3; }
if [[ "$MODE" == readonly ]]; then
  [[ "$(q -d "$DB" -c "SHOW default_transaction_read_only")" == on ]] || { echo "FALLÓ: la base no quedó en solo lectura en una sesión nueva" >&2; exit 4; }
  col="$(q -d "$DB" -c "select attname from pg_attribute where attrelid='public.\"$tab\"'::regclass and attnum>0 and not attisdropped order by attnum limit 1")"
  for stmt in "INSERT INTO \"$tab\" DEFAULT VALUES" "UPDATE \"$tab\" SET \"$col\" = \"$col\" WHERE false" "DELETE FROM \"$tab\" WHERE false" "TRUNCATE \"$tab\"" "CREATE TABLE zz_no(i int)"; do
    # incluso desactivando el modo de solo lectura de la sesión, los PERMISOS del rol lo impiden (y el motivo debe ser de permisos, no un error cualquiera)
    out="$(as_role -c "SET default_transaction_read_only = off" -c "SET transaction_read_only = off" -c "$stmt" 2>&1 >/dev/null)" && { echo "FALLÓ: el rol de la aplicación PUDO ejecutar: ${stmt%% *}" >&2; exit 5; }
    grep -qiE "permission denied|must be owner|read-only" <<<"$out" || { echo "FALLÓ: la sentencia (${stmt%% *}) falló por un motivo distinto de los permisos: no se puede dar por comprobado" >&2; exit 6; }
  done
  # y, en el catálogo, NINGUNA tabla ni secuencia del esquema concede escritura al rol (GRANT de un no propietario no da error, solo aviso: por eso se comprueba el catálogo)
  bad="$(q -d "$DB" -c "select count(*) from pg_class c where c.relnamespace='public'::regnamespace and ((c.relkind='r' and (has_table_privilege('$ROLE', c.oid, 'INSERT') or has_table_privilege('$ROLE', c.oid, 'UPDATE') or has_table_privilege('$ROLE', c.oid, 'DELETE') or has_table_privilege('$ROLE', c.oid, 'TRUNCATE'))) or (c.relkind='S' and (has_sequence_privilege('$ROLE', c.oid, 'USAGE') or has_sequence_privilege('$ROLE', c.oid, 'UPDATE'))))")"
  [[ "$bad" == 0 ]] || { echo "FALLÓ: $bad tabla(s)/secuencia(s) conceden escritura al rol de la aplicación" >&2; exit 7; }
  echo "OK    permisos de solo lectura: el rol puede LEER y NO puede INSERT/UPDATE/DELETE/TRUNCATE/CREATE (ni desactivando el modo de solo lectura); ninguna tabla ni secuencia le concede escritura; sesión nueva en solo lectura (ni desactivando el modo de solo lectura); sesión nueva en solo lectura"
else
  echo "OK    permisos de lectura/escritura concedidos al rol de la aplicación"
fi
