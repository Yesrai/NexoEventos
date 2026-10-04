# EV06 — RDS y persistencia

RDS PostgreSQL 18.3 privado quedó accesible desde el SG de la aplicación y no desde Internet. Alembic aplicó `0001`, `0002` y `0003` con `nexoeventos_migrator` y `SET ROLE nexoeventos_owner`; FastAPI usa `nexoeventos_app` sin atributos elevados. Una reserva y su entrada permanecieron después de reiniciar el servicio API.

La prueba pública creó datos ficticios únicamente. No se publican endpoint, contraseñas, identificadores de cuenta ni tokens QR.

Después del snapshot y del dump cifrado, AWS confirmó la instancia RDS en estado `stopped`. La advertencia de umbral de almacenamiento (máximo igual a 20 GiB asignados) queda pendiente de un plan revisado.
