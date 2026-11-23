-- Verificación de SOLO LECTURA del rol de volcado (ejecutar con el administrador): psql "$ADMIN_URL" -At -f deploy/backup/backup-role-verify.sql
-- Esperado: 1 fila de atributos «f|f|f|f|f|2», una sola membresía (pg_read_all_data), configuración de solo lectura y 0 objetos propios.
SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolconnlimit FROM pg_roles WHERE rolname = 'nexoeventos_backup';
SELECT g.rolname FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = 'nexoeventos_backup';
SELECT unnest(setconfig) FROM pg_db_role_setting s JOIN pg_roles r ON r.oid = s.setrole WHERE r.rolname = 'nexoeventos_backup';
SELECT count(*) AS objetos_propios FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner WHERE r.rolname = 'nexoeventos_backup';
