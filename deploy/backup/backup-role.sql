-- Rol de VOLCADO de mínimo privilegio para el respaldo periódico (backup_cycle.py → pg_dump). Se ejecuta UNA vez, con el usuario administrador de la base
-- (en RDS: el rol maestro, que es rds_superuser), por la propietaria; esta carpeta NO lo ejecuta por sí sola. Idempotente; la contraseña NO está en el archivo:
--   NEXO_BACKUP_PASSWORD="$(openssl rand -base64 32)" psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -f deploy/backup/backup-role.sql
-- (la contraseña llega por variable de entorno al `psql`, no por argumentos de línea de órdenes, y debe guardarse en el archivo de entorno 0600 de la EC2).
-- Qué puede hacer: LEER todas las tablas y secuencias (pg_read_all_data, PostgreSQL ≥ 14), que es lo que necesita pg_dump y fingerprint.sql.
-- Qué NO puede: escribir, crear ni borrar objetos, cambiar roles, replicar, crear bases ni saltarse la seguridad por filas; la sesión es de solo lectura por
-- defecto, con un máximo de 2 conexiones y tiempos límite. A diferencia del rol de migración (propietario del esquema), no puede modificar datos si se filtra.
\set ON_ERROR_STOP on
\set backup_password `printenv NEXO_BACKUP_PASSWORD`
SELECT (:'backup_password' = '') AS sin_contrasena \gset
\if :sin_contrasena
  \echo 'Falta NEXO_BACKUP_PASSWORD en el entorno: no se crea nada.'
  \quit
\endif
SELECT format('CREATE ROLE nexoeventos_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2 PASSWORD %L', :'backup_password')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexoeventos_backup') \gexec
GRANT pg_read_all_data TO nexoeventos_backup;
ALTER ROLE nexoeventos_backup SET default_transaction_read_only = on;
ALTER ROLE nexoeventos_backup SET statement_timeout = '30min';
ALTER ROLE nexoeventos_backup SET idle_in_transaction_session_timeout = '5min';
SELECT format('GRANT CONNECT ON DATABASE %I TO nexoeventos_backup', current_database()) \gexec
REVOKE CREATE ON SCHEMA public FROM nexoeventos_backup;
