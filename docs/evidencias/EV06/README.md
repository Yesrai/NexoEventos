# EV06 — RDS y persistencia

RDS PostgreSQL 18.3 privado quedó accesible desde el SG de la aplicación y no desde Internet. El 7-oct Alembic avanzó de `0003` a `0005` con `nexoeventos_migrator` y `SET ROLE nexoeventos_owner`; FastAPI usa `nexoeventos_app` sin atributos elevados. Los conteos históricos de usuarios, reservas, entradas, asignaciones y cupos se conservaron; se añadieron 27 eventos ficticios sin habilitar asientos numerados. Una reserva y su entrada permanecieron después de reiniciar el servicio API.

La prueba pública creó datos ficticios únicamente. No se publican endpoint, contraseñas, identificadores de cuenta ni tokens QR.

Después del snapshot y del dump cifrado, AWS confirmó la instancia RDS en estado `stopped`. La advertencia de umbral de almacenamiento (máximo igual a 20 GiB asignados) queda pendiente de un plan revisado.

Lectura API del 7 de octubre: continúa `stopped`, privada, cifrada, Single-AZ, PostgreSQL 18.3 y 20 GiB. El máximo remoto sigue en 20 GiB; el plan parcial propone desactivarlo explícitamente con 0. La base desplegada permanece en `0003`; las migraciones locales `0004` y `0005` requieren respaldo y aplicación controlada antes de publicar el backend nuevo.
