# Actualización AWS V1 mediante Ansible — 7 de octubre de 2026

## Resultado real

Se desplegó y verificó el commit `7955e7e` sobre la infraestructura V1 existente, sin `terraform apply`, `destroy`, SSH ni ampliación de IAM. El sitio respondió por HTTPS, la API quedó en Alembic `0005` y el catálogo expuso 27 eventos ficticios con entradas generales o por zonas; no se habilitaron asientos numerados ni 3D.

## Protección previa

- Snapshot RDS `nexoeventos-academy-preupdate-20261008t0113z`: `available`, cifrado, 20 GiB.
- Dump `pg_dump 18.6`: 22 206 bytes antes de cifrar; catálogo legible con `pg_restore 18.6`.
- Paquete CMS: 22 762 bytes, S3 privado con SSE AES256 y copia externa `0600`.
- El paquete externo descifró al mismo SHA-256 que el dump de origen. El cliente `pg_restore` local era anterior y no interpretó el formato 1.16; la comprobación de catálogo se hizo con la versión 18.6 de EC2.
- Línea base: 3 usuarios, 3 eventos, 1 reserva, 1 entrada, 1 asignación, 5 accesos y 1 cupo reservado.

## Migración y datos

Las migraciones `0004` y `0005` fueron aditivas. La versión anterior puede leer sus tablas históricas porque las columnas nuevas tienen valores por defecto o son anulables, pero cambiar `current/previous` **no revierte la base**. El respaldo y snapshot son la vía de recuperación de datos.

La siembra se corrigió antes de desplegar: `ON CONFLICT (id) DO NOTHING`. No cambia cupos, reservas, propietarios, precio, fecha, modalidad ni zonas de un ID existente. La base posterior conservó los conteos históricos y añadió 27 eventos; `seat_mode_events=0` y `event_seats=0`.

## Verificación

- `HTTP → HTTPS`: 301; `/`: 200; `/healthz`: 200; `/api/events`: 200.
- Registro de cliente: 201; reserva ficticia: 201; una entrada privada creada.
- Operador asignado al evento ficticio de prueba: login 200; primera validación 200; segundo ingreso 409.
- La entrada pasó a usada; logout 204 y sesión posterior 401.
- QR no impreso; cookies mantenidas solo en memoria.
- Capturas públicas sin sesión: `docs/evidencias/EV10/EV10-sitio-actualizado-2026-10-07-{desktop,mobile}.png`.

## Incidencias corregidas

1. Worker Ansible inestable en macOS: ejecución limitada a un fork y mitigación local de Objective-C.
2. Metadatos AppleDouble `._*.py` en el tar: excluidos y verificados; habían impedido que Alembic cargara migraciones.
3. API detenida después de una ejecución idempotente: reinicio explícito tras cambiar `current`.
4. Nginx sin permiso de recorrido: solo los padres y archivos públicos del frontend quedaron `755/644`; backend y secretos mantienen restricciones.

Los fallos previos activaron el rollback de código y no dejaron cambios parciales de esquema; se comprobó que la base seguía en `0003` antes del intento exitoso.

## Cierre pendiente por falta de tokens

El 9 de octubre la usuaria informó que apagó AWS al agotarse los tokens. No se hicieron nuevas llamadas. Por tanto quedan pendientes de comprobación:

- estados finales reales de EC2 y RDS;
- versiones/marcadores S3 temporales creados por Ansible;
- archivo CMS temporal cifrado y releases fallidas en EC2;
- recepción final de CloudWatch y costo observado de la ventana.

Al recuperar acceso se debe empezar en solo lectura, limpiar únicamente los temporales identificados de esta sesión y confirmar de nuevo `stopped`. El snapshot, el objeto `backups/database/` y la copia externa deben conservarse.
