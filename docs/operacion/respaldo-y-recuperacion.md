# Respaldo y recuperación

## Evidencia local

`scripts/test-restore-local.sh` crea un dump custom, restaura exclusivamente `nexoeventos_restore_test`, compara eventos/reservas/entradas y verifica que una entrada restaurada siga descifrándose con la clave local ignorada por Git. Elimina la base y el dump temporales. No toca otras bases.

```bash
./scripts/test-restore-local.sh
```

## Capas previstas en AWS

1. Backups automáticos RDS con retención de siete días.
2. Snapshot final habilitado en Terraform con nombre explícito válido, inicialmente `nexoeventos-academy-final-20261126`. Antes de una futura eliminación se debe comprobar que ese nombre no exista; nunca ejecutar `destroy` sin plan y aprobación separados.
3. Exportación lógica mediante `scripts/create-portable-backup.sh` y un rol PostgreSQL dedicado de solo lectura. El paquete contiene `pg_dump`, commit y checksums, y se cifra con AES-256/PBKDF2 mediante una contraseña solicitada sin eco.
4. Una copia del paquete cifrado debe transferirse a almacenamiento protegido **fuera de la cuenta de origen**. El repositorio y el bucket de la misma cuenta no satisfacen esta independencia. La ubicación concreta sigue pendiente de decisión de la propietaria.
5. S3 privado/versionado de la cuenta conserva copias operativas de corto plazo; no reemplaza la copia externa.

El snapshot puede seguir facturándose después de eliminar RDS. Con la tarifa pública consultada en `us-east-1`, el límite conservador para 20 GiB es USD 1.90/mes; la facturación real usa bloques incrementales y la asignación de backups mientras la instancia exista. Para recuperar: crear una nueva RDS desde el snapshot, mantenerla privada, validar SG/subredes, rotar credenciales, aplicar migraciones posteriores y ejecutar pruebas antes de cambiar la aplicación.

## Claves QR

El dump contiene tokens QR cifrados y hashes, no el secreto en claro. `TICKET_ENCRYPTION_KEY` es imprescindible para recuperar entradas ya emitidas y se conserva por un canal protegido distinto del dump, del estado Terraform y de la cuenta AWS origen. `SECURITY_HASH_KEY` también se respalda separadamente. Nunca se incluyen en Git, S3 junto al dump, capturas, logs o el paquete portable.

Ensayo de recuperación:

1. descifrar una copia del paquete en un directorio temporal protegido;
2. restaurar en una base aislada con `pg_restore --no-owner --no-acl`;
3. crear identidades limitadas nuevas y aplicar migraciones;
4. cargar la clave QR desde su respaldo separado, sin imprimirla;
5. verificar conteos, propietario de reservas, descifrado de una entrada ficticia y validación única;
6. eliminar con seguridad el material temporal.

Los objetivos del caso son RPO 24 h y RTO 60 min; todavía no son mediciones cloud. La prueba local demuestra integridad básica, no esos objetivos.
