# C-04 — Fase B (rol de volcado en RDS) — 19-nov-2026 ≈ 04:10 UTC — resultado saneado
Alcance autorizado: crear **solo** el rol `nexoeventos_backup` en `nexoeventos-academy-postgres` y verificarlo; sin ciclos de respaldo, sin escrituras en OCI, sin PAR. Credencial maestra leída **dentro de la EC2** (rol `LabRole`) y pasada a `psql` por variable de entorno; nunca impresa ni en argumentos. Salidas sin secretos.

## Antes de crear (modo `check`, solo lectura, TLS `verify-full` con el administrador)
- Base `nexoeventos`, PostgreSQL **18.3**; conexiones **9 de 81** (≈ 11 %).
- El rol **no existía**. Roles existentes: `nexoeventos_admin` (maestro gestionado por RDS), `nexoeventos_app`, `nexoeventos_migrator`, `nexoeventos_owner` y los predefinidos de RDS.
- Un solo esquema (`public`), **14 tablas y 4 secuencias, todas propiedad de `nexoeventos_owner`**.
- El SQL aplicado es **el mismo archivo probado en local** (SHA-256 idéntico).

## `pg_read_all_data` frente a `GRANT SELECT` explícitos (decisión)
Se mantiene `pg_read_all_data`: (1) **no cambia ninguna ACL** de objetos existentes (el usuario pidió no modificarlos; unos `GRANT SELECT` tocarían las 14 tablas, las 4 secuencias y el esquema), (2) una tabla futura creada por una migración quedaría fuera de un `GRANT` explícito y el respaldo fallaría por «permission denied» sin que nadie lo note, (3) el respaldo necesita leer toda la base de todos modos. Coste del enfoque: alcance de lectura más amplio que lo estrictamente listado, pero hoy solo hay un esquema.

## Creación (modo `apply`)
`CREATE ROLE nexoeventos_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2`, `GRANT pg_read_all_data`, sesión de solo lectura por defecto, `statement_timeout` 30 min, `CONNECT` a la base y sin `CREATE` en `public`. La contraseña (48 hex generados en la EC2) solo está en `/etc/nexoeventos/backup.env` (root, 0600).
- **Instantánea del catálogo antes/después idéntica:** roles y atributos, membresías, configuración por rol, ACL de las 18 tablas/secuencias, ACL del esquema y de la base (excluyendo al rol nuevo) y ACL por defecto → **ningún otro rol ni objeto cambió**. Misma comprobación pasa en local (20 verificaciones).
- Aplicación sin interrupción: `nexoeventos-api` y `nginx` `active` antes y después; `/ready` de la API → HTTP 200 (lee PostgreSQL) después.

## Verificación con el rol (modo `verify`)
| Comprobación | Resultado |
|---|---|
| Conexión | usuario `nexoeventos_backup`, `ssl=true`, URL con `sslmode=verify-full` y `sslrootcert` al paquete de CA de RDS |
| Atributos | super/createdb/createrole/replicación/bypassrls = `false`; límite de conexiones 2 |
| Membresías | solo `pg_read_all_data` |
| `pg_dump -Fc` (tubería, sin guardar volcado en claro) | cabecera `PGDMP`, 92.337 bytes |
| Huella de datos (`fingerprint.sql`) con el rol | alembic 0008; users 26; events 35; reservations 136; tickets 136; operator_assignments 2; access_logs 9; reserved_total 136 |
| Escritura | **denegada**: UPDATE, DELETE, CREATE TABLE, CREATE ROLE y `ALTER ROLE … SUPERUSER` (probados dentro de transacciones de lectura-escritura con `ROLLBACK`; UPDATE/DELETE con `WHERE false`: no tocan datos) |

## Defecto encontrado y corregido durante la fase
`backup.env` lleva `&` en la URL (`sslmode=…&sslrootcert=…`): hacer `source` del archivo la cortaba y `DATABASE_URL` quedaba sin definir. Se corrigió en `provision-backup-role.sh` y `c04-run-cycle.sh` (se lee la línea con `sed`, como hace systemd) con prueba de regresión. El servicio de systemd no estaba afectado.

## Pendiente (no hecho)
PAR de OCI (lo crea la propietaria), sonda de `If-None-Match` (escritura mínima en OCI, requiere confirmación), los 3 ciclos y la revocación. EC2 y RDS siguen `running`/`available`.
