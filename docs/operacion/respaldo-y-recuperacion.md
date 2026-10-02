# Respaldo y recuperación

## Alcance probado localmente

`scripts/test-restore-local.sh` genera un `pg_dump` en formato custom, lo restaura en la base exclusiva `nexoeventos_restore_test`, compara cantidades de eventos, reservas y entradas, y comprueba que una entrada restaurada sigue siendo descifrable. La base y el dump temporales se eliminan al finalizar. No toca otras bases.

```bash
./scripts/test-restore-local.sh
```

## Procedimiento previsto en AWS

1. Mantener backups automáticos de RDS durante siete días.
2. Para evidencia transportable, ejecutar `pg_dump --format=custom` desde la EC2 con una cuenta dedicada que solo pueda leer la base.
3. Cargar el dump en el prefijo privado `database-backups/` de S3 usando el rol de instancia, nunca claves AWS persistentes.
4. Conservar versionado y cifrado de S3; comprobar el objeto y registrar hora/tamaño sin capturar datos.
5. Restaurar a una base nueva y aislada, aplicar las migraciones faltantes y ejecutar las comprobaciones de integridad antes de conmutar la aplicación.

Los backups automáticos de RDS y el bucket Terraform aún no se han creado ni probado en AWS.

## Clave de entradas QR

El dump contiene el token QR cifrado y su hash, pero no basta para recuperarlo. `TICKET_ENCRYPTION_KEY` debe respaldarse de forma separada del dump, con acceso restringido y versionado controlado. No debe guardarse en Git, S3 junto al dump, capturas, logs ni documentos.

La V1 usa variables de entorno desde un archivo legible únicamente por el usuario del servicio. Antes del despliegue debe elegirse y comprobarse un almacén cloud permitido por Learner Lab. Si se usa Secrets Manager, se debe confirmar que `LabInstanceProfile` pueda leer solo el secreto requerido; listar el servicio no demuestra ese permiso.

Objetivos del caso, todavía no medidos en cloud: RPO máximo de 24 horas y RTO máximo de 60 minutos. La restauración local prueba integridad básica, no esos objetivos.
