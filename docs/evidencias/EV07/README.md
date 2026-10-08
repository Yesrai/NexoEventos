# EV07 — respaldo y restauración

Comprobado el 3 de octubre de 2026:

- claves QR/hash cifradas con una clave pública de recuperación y copia `0600` fuera del repositorio y de AWS;
- dump lógico creado con `pg_dump` 18.6 contra RDS 18.3;
- paquete CMS cifrado subido al bucket S3 privado, cifrado y versionado;
- copia cifrada descargada fuera de la cuenta con hash coincidente;
- descifrado y estructura interna (`database.dump`, manifiesto y checksums) verificados sin exponer datos;
- snapshot manual RDS cifrado de 20 GiB confirmado `available` después de las pruebas públicas.

No se capturaron claves, contraseñas, contenidos de la base ni tokens QR. Falta ejecutar una restauración cloud aislada desde este respaldo; la restauración local anterior sigue siendo evidencia separada.

Lectura del 7 de octubre: snapshot manual cifrado continúa `available`; el objeto cifrado en `backups/database/` permanece en S3 privado, versionado, AES-256 y con bloqueo público completo. La restauración sigue sin ejecutarse.
