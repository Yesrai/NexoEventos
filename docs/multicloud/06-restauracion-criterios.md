# 6. Restauración aislada y criterios de aceptación

Script: `scripts/multicloud/restore-drill.sh` (modo `docker` para pruebas locales; modo `local` en la VM de recuperación de OCI con PostgreSQL instalado). Línea base: `docs/multicloud/baseline-restauracion.json` (valores **observados**: respaldo del 19-oct con esquema 0005 y estado 0008 del 22-oct) y consulta común `scripts/multicloud/fingerprint.sql`.

## Criterios de aceptación (todos obligatorios)
| # | Criterio | Cómo se comprueba |
|---|---|---|
| 1 | Integridad de la copia | SHA-256 y tamaño del cifrado = manifiesto |
| 2 | Descifrado con la clave independiente de OCI | `openssl cms -decrypt`; con otra clave debe fallar |
| 3 | Volcado íntegro | SHA-256 del volcado en claro = el del manifiesto (registrado en AWS) |
| 4 | Catálogo válido | `pg_restore --list` sin errores |
| 5 | Restauración sin errores | `pg_restore --exit-on-error` en una base nueva y aislada |
| 6 | Huella idéntica | alembic, usuarios, eventos, reservas, entradas, asignaciones, accesos, `reserved_total`, `inventory_md5` y `reservations_md5` = línea base (135 reservas, 135 entradas, 25 usuarios; `0008` con 35 eventos o `0005` con 31) |
| 7 | Aislamiento y limpieza | la restauración no toca producción; el material en claro vive en un directorio 0700 que se destruye al salir; la VM de OCI se destruye tras el simulacro |
| 8 | Tiempo | se registra la duración total (RTO medido) y el momento del respaldo (RPO) |
| 9 | Evidencia | `docs/evidencias/multicloud/oci/AAAAMMDD-restauracion/` con resultado, versiones y tiempos, sin claves ni datos personales |

Casos negativos que deben fallar (probados en local): archivo alterado, clave equivocada, línea base distinta.
**Pendiente (OCI real):** instalar PostgreSQL 18 en la VM (requiere NAT o imagen preparada), ejecutar el simulacro con el CMS real y registrar el RTO; la comprobación de descifrado de entradas QR requiere la clave de entradas (`TICKET_ENCRYPTION_KEY`), que no se incluye en este simulacro.
