# EV07 — respaldo y restauración

Comprobado el 3 de octubre de 2026:

- claves QR/hash cifradas con una clave pública de recuperación y copia `0600` fuera del repositorio y de AWS;
- dump lógico creado con `pg_dump` 18.6 contra RDS 18.3;
- paquete CMS cifrado subido al bucket S3 privado, cifrado y versionado;
- copia cifrada descargada fuera de la cuenta con hash coincidente;
- descifrado y estructura interna (`database.dump`, manifiesto y checksums) verificados sin exponer datos;
- snapshot manual RDS cifrado de 20 GiB confirmado `available` después de las pruebas públicas.

No se capturaron claves, contraseñas, contenidos de la base ni tokens QR. Falta ejecutar una restauración cloud aislada desde este respaldo; la restauración local anterior sigue siendo evidencia separada.

Lectura del 7 y 9 de octubre: snapshot manual cifrado continúa `available`; el objeto cifrado en `backups/database/` permanece en S3 privado, versionado, AES-256 y con bloqueo público completo. La preparación quedó delimitada en [restauracion-preparada-2026-10-09.md](restauracion-preparada-2026-10-09.md).

**R01 ejecutada el 10 de octubre:** PITR con desfase de 3 min 32 s; copia privada disponible en 20 min 49 s; datos verificados en 21 min 4 s. Coincidieron Alembic `0005`, seis tablas, reservas y 135/135 entradas QR descifrables. La copia temporal exacta fue eliminada y el origen volvió a quedar detenido. Ver [resultado sanitizado](resultado-restauracion-2026-10-10.md). La recuperación completa del servicio sigue pendiente porque no se conmutaron aplicación, DNS ni HTTPS.

**Ensayo integral iniciado el 11 y cerrado el 12 de octubre:** alcanzó T2 con Alembic `0005`, reservas sin huérfanos y 135/135 QR descifrables, pero no alcanzó HTTPS ni el recorrido funcional. El RTO completo no quedó acreditado y el objetivo de 60 minutos no se cumplió. Los 11 recursos temporales fueron eliminados y el origen quedó detenido. Ver [resultado incompleto](resultado-recuperacion-completa-incompleta-2026-10-12.md).
