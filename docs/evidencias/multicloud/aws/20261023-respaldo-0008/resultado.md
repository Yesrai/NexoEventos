# Respaldo lógico cifrado, PostgreSQL 18 / Alembic 0008 — 2026-10-23 (UTC)

Procedimiento reproducible: `scripts/cloud/db-backup-cms.py` (en la EC2 de V1 vía SSM: `pg_dump -Fc --no-owner --no-acl` → `openssl cms -encrypt` AES-256-CBC/DER con el certificado público de recuperación de AWS; sin texto plano en disco; subida a `backups/database/` del bucket privado de la cuenta; descarga a `work/backups/external/`). Datos crudos: `respaldo-0008.json`.

- Archivo: `nexoeventos-alembic0008-20261023T150946Z.cms`, 92.063 bytes (volcado en claro 91.495 bytes), `pg_dump` 18.6 contra RDS 18.3.
- SHA-256 del CMS: `91c4ca41…319c3e`; coincide entre EC2 y copia local. SHA-256 del volcado en claro: `67b6876f…65669a`.
- Descifra con la clave privada de AWS y comienza con `PGDMP`; `pg_restore -l` (PostgreSQL 18, sin escribir el volcado en disco) lista 104 entradas. **La restauración completa aún no se ha probado** (pendiente del simulacro).
- Huella de datos antes y después del volcado idéntica y igual a la línea base 0008: reservations 135 (md5 `cbe0c1c2…`), tickets 135, users 25, events 35 (md5 `0733e3db…`), access_logs 9, alembic 0008.
- Identidad usada para leer: la de migración de la EC2 (solo `pg_dump`/SELECT); no hay un rol de solo lectura dedicado todavía.
- Ventana AWS: RDS Multi-AZ arrancada (330 s hasta `available`) y EC2 de V1; ambas detenidas después. Estado final verificado: EC2 `stopped`, RDS `stopped` (440 s tras la orden).
- No se transfirió nada a OCI; Terraform sin cambios.
