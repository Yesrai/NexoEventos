-- REVERSIÓN de ÚNICAMENTE el rol de volcado (no toca ningún otro rol). Ejecutar con el administrador en la base donde se creó:
--   psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -f deploy/backup/backup-role-revert.sql
-- Antes: cerrar las sesiones del rol (SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'nexoeventos_backup').
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'nexoeventos_backup';
DROP OWNED BY nexoeventos_backup;
DROP ROLE IF EXISTS nexoeventos_backup;
