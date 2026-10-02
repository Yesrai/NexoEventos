# Persistencia y reservas

## Implementado

- PostgreSQL como fuente del catálogo y el detalle de eventos.
- Migración Alembic `0001` con esquema y tres eventos ficticios reproducibles.
- Reserva simulada transaccional con bloqueo de fila `SELECT … FOR UPDATE`.
- Restricción de base para impedir que `reserved_count` supere `capacity`.
- Clave de idempotencia única por propietario y hash canónico de evento y cantidad.
- Reintento idéntico devuelve la reserva existente sin descontar cupos.
- Reuso de clave con otros datos devuelve HTTP 409.
- No hay endpoint GET público de reservas.

## Separación de privilegios

`nexoeventos_owner` posee el esquema y no puede iniciar sesión. `nexoeventos_app` puede conectarse, leer eventos, actualizar únicamente `events.reserved_count` y leer/insertar reservas. No puede crear objetos, insertar eventos ni borrar reservas.

En una base nueva, `scripts/provision-database-roles.py` prepara ambos roles usando una identidad administrativa de migraciones y solicita una contraseña exclusiva para la aplicación. Alembic ejecuta `SET ROLE nexoeventos_owner`; el proceso FastAPI usa únicamente `nexoeventos_app`. El procedimiento no incorpora contraseñas al código ni a argumentos de proceso.

Las migraciones `0002` y `0003` agregan autenticación/roles/entradas y limitación de intentos, respectivamente. Las entradas, sesiones y reservas se vinculan al propietario; no existe un endpoint público para enumerarlas.

## Deliberadamente pendiente

- Pagos reales; las reservas actuales son simuladas.
- Prueba de persistencia y restauración en RDS.
- Medición de rendimiento y capacidad en cloud.
