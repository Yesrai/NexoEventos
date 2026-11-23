-- Instantánea de SOLO LECTURA del catálogo para demostrar que crear el rol de volcado NO cambia a los demás roles, sus permisos ni los objetos existentes.
-- Se ejecuta con el administrador ANTES y DESPUÉS: psql "$ADMIN_URL" -At -f deploy/backup/c04-db-snapshot.sql. Solo imprime líneas «clave|valor» (nombres, conteos y hashes; sin datos ni secretos).
-- Todo lo relativo a nexoeventos_backup se EXCLUYE de los hashes, de modo que «antes» y «después» deben ser idénticos salvo `rol_backup_existe` y `conexiones`.
SELECT 'db|' || current_database() || '|' || split_part(version(), ' ', 2);
SELECT 'conexiones|' || (SELECT count(*) FROM pg_stat_activity) || '|max=' || current_setting('max_connections');
SELECT 'rol_backup_existe|' || count(*) FROM pg_roles WHERE rolname = 'nexoeventos_backup';
SELECT 'roles_lista|' || coalesce(string_agg(rolname, ',' ORDER BY rolname), '') FROM pg_roles WHERE rolname !~ '^pg_' AND rolname <> 'nexoeventos_backup';
SELECT 'roles_hash|' || md5(coalesce(string_agg(format('%s:%s%s%s%s%s%s%s:%s', rolname, rolsuper::int, rolinherit::int, rolcreaterole::int, rolcreatedb::int, rolcanlogin::int, rolreplication::int, rolbypassrls::int, rolconnlimit), ',' ORDER BY rolname), ''))
  FROM pg_roles WHERE rolname <> 'nexoeventos_backup';
SELECT 'membresias_hash|' || md5(coalesce(string_agg(format('%s>%s', roleid::regrole, member::regrole), ',' ORDER BY roleid::regrole::text, member::regrole::text), ''))
  FROM pg_auth_members WHERE member::regrole::text <> 'nexoeventos_backup';
SELECT 'config_roles_hash|' || md5(coalesce(string_agg(format('%s:%s', setrole::regrole, setconfig::text), ',' ORDER BY setrole::regrole::text), ''))
  FROM pg_db_role_setting WHERE setrole <> 0 AND setrole::regrole::text <> 'nexoeventos_backup';
SELECT 'esquemas|' || coalesce(string_agg(nspname, ',' ORDER BY nspname), '') FROM pg_namespace WHERE nspname !~ '^(pg_|information_schema)';
SELECT 'objetos|tablas=' || count(*) FILTER (WHERE relkind IN ('r', 'p')) || ',secuencias=' || count(*) FILTER (WHERE relkind = 'S') || ',vistas=' || count(*) FILTER (WHERE relkind IN ('v', 'm'))
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname !~ '^(pg_|information_schema)';
SELECT 'propietarios|' || coalesce(string_agg(DISTINCT relowner::regrole::text, ','), '')
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname !~ '^(pg_|information_schema)' AND relkind IN ('r', 'p', 'S');
SELECT 'acl_objetos_hash|' || md5(coalesce(string_agg(format('%s.%s:%s', n.nspname, c.relname, coalesce(c.relacl::text, '-')), ',' ORDER BY n.nspname, c.relname), ''))
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname !~ '^(pg_|information_schema)' AND c.relkind IN ('r', 'p', 'S', 'v', 'm');
SELECT 'acl_esquemas_hash|' || md5(coalesce(string_agg(format('%s:%s', nspname, coalesce(nspacl::text, '-')), ',' ORDER BY nspname), '')) FROM pg_namespace WHERE nspname !~ '^(pg_|information_schema)';
SELECT 'acl_base_hash|' || md5(coalesce(string_agg(format('%s|%s|%s', grantor::regrole, grantee::regrole, privilege_type), ',' ORDER BY grantor::regrole::text, grantee::regrole::text, privilege_type), ''))
  FROM (SELECT (aclexplode(datacl)).* FROM pg_database WHERE datname = current_database()) x WHERE grantee::regrole::text <> 'nexoeventos_backup';
SELECT 'acl_por_defecto_hash|' || md5(coalesce(string_agg(format('%s:%s:%s', defaclrole::regrole, defaclobjtype, defaclacl::text), ',' ORDER BY defaclrole::regrole::text, defaclobjtype), '')) FROM pg_default_acl;
