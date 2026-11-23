# TLS hacia RDS: de `require` a `verify-full` (implementación local, sin desplegar)

**Hallazgo real:** `deploy/bootstrap-rds-secrets.sh` generaba las URL de la aplicación, de las migraciones y del aprovisionamiento con `?sslmode=require`: el tráfico va **cifrado**, pero el cliente **no valida el certificado ni el nombre del servidor**, de modo que un intermediario con cualquier certificado sería aceptado. El servidor ya exige TLS (`rds.force_ssl = 1`, verificado por API el 29-oct).

**Cambios locales (no desplegados):**
1. `backend/app/database.py`: `enforce_tls_policy()` se ejecuta en `build_engine`. Para una base **remota** exige `sslmode=verify-full` y un `sslrootcert` existente; el mensaje no incluye la contraseña. Sockets Unix y `localhost` quedan exentos (desarrollo, pruebas, recuperación con PostgreSQL local). **No hay interruptor para desactivar la verificación.**
2. `deploy/bootstrap-rds-secrets.sh`: las tres URL usan `sslmode=verify-full&sslrootcert=<paquete de CA>`; aborta si el paquete no está instalado.
3. `deploy/install-rds-ca-bundle.sh` (nuevo, **no ejecutado**): descarga el paquete de CA de RDS y exige un SHA-256 fijado (`NEXO_RDS_CA_SHA256`).
4. `backend/tests/test_database_tls.py` (8 pruebas) y `scripts/test-db-tls-verification.sh`.

**Pruebas locales (todas OK, `salida-prueba.txt`):** con un PostgreSQL temporal con TLS y una CA propia: `require` conecta sin validar; `verify-full` con la CA correcta conecta con TLS; con **otra CA** rechaza; con un nombre que **no está en el certificado** (127.0.0.1) rechaza; sin TLS (`disable`) rechaza. Backend completo: 52/52.

**Compatibilidad / despliegue (requiere autorización):** el paquete de CA debe estar en cada instancia antes de actualizar las URL (si no, la aplicación no arranca: es deliberado). Hay que fijar el SHA-256 del paquete tras revisarlo (descarga pendiente de tu permiso). En V1 el certificado del endpoint de RDS lo emite la CA `rds-ca-rsa2048-g1` (leída por API). No se probó contra una RDS real porque está detenida y no se debe encender.
