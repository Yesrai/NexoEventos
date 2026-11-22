# Procedimiento de verificación de la restauración de la aplicación y sus datos (preparado, NO ejecutado)

Preparado el 22-nov-2026. **No se ha realizado ninguna restauración real**: es un procedimiento para una sesión futura, con autorización expresa en cada paso que cambie AWS. Terraform no restaura PostgreSQL, secretos ni claves; esta guía comprueba que los datos y la aplicación recuperados son los correctos. No contiene secretos ni valores de claves.

## 1. Lo que ya existe (y su límite)
| Prueba anterior | Qué demostró | Límite |
|---|---|---|
| **R01, 10-oct-2026** (PITR a una RDS temporal) | RPO 3 min 32 s; datos verificados a los 21 min 4 s; 135/135 entradas QR descifrables; RDS temporal eliminada | Solo restauración de **datos**; sin aplicación ni DNS; únicamente informe textual (sin datos crudos en el repositorio) |
| **Recuperación en OCI, 23-oct-2026** (manual) | Aplicación restaurada desde el respaldo cifrado: 32 min 42 s desde el `apply`, 14/14 pruebas de humo, huella de 10 valores idéntica | Incluyó 1 fallo y 4 reanudaciones; **no** fue automática ni una restauración de AWS |
**Nunca se ha restaurado el servicio completo dentro de AWS.** Esta guía define cómo comprobarlo sin confundir «los datos volvieron» con «el servicio funciona».

## 2. Fuentes de restauración (elegir una por ensayo)
| Fuente | Dónde está | Requiere |
|---|---|---|
| Instantánea de RDS (17; 6 manuales, la más reciente del 20-nov) | RDS | Permisos `rds:RestoreDBInstanceFromDBSnapshot` en Academy |
| Punto en el tiempo (PITR) | RDS (retención 7 días; con la RDS apagada no avanza la ventana restaurable) | RDS con copias automáticas |
| Respaldo lógico cifrado `.cms` (5 en S3 `backups/database/`; copia externa en OCI solo del 23-oct) | S3 y OCI | **Clave privada de recuperación** (solo en poder de la propietaria; se usa en el Mac, **nunca en la nube**), `pg_restore` y una base destino |
Nota: la regla de lifecycle de S3 desplegada apunta a otro prefijo y hoy no borra los `.cms`; la nueva retención (90 días, mínimo 30) caducaría los más antiguos en enero de 2027: copiar los que interesen antes de aplicarla.

## 3. Antes de empezar (todas obligatorias)
1. Autorización expresa de la propietaria para el ensayo concreto, con presupuesto (una RDS temporal db.t3.micro cuesta ≈ 0,018 USD/h; 25 min ≈ céntimos) y ventana de tiempo respecto a la caducidad de las credenciales.
2. `rds-window.sh check` limpio; **nunca** restaurar sobre la RDS de producción: siempre un destino aislado con prefijo `restore-<RunId>`.
3. **Línea base de la fuente, tomada justo antes**: `deploy/verify-restore.sh baseline` (conteos, revisión de Alembic y huella lógica, sin imprimir datos personales) o la huella SQL de `scripts/cloud/verify-controlled-flow.py`. Los valores históricos (23-oct: reservas 135, entradas 135, usuarios 25, eventos 35, Alembic 0008) **no** sirven como línea base actual.
4. Claves originales disponibles: `TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY` del secreto compartido (no se leen ni se imprimen: la verificación las usa en la propia máquina de comprobación).

## 4. Pasos
1. **Restaurar a un destino aislado.** Instantánea o PITR: `scripts/cloud/restore-drill.sh run [--pitr|<id-de-instantánea>]` (cronometra el RPO, el tiempo hasta `available` y hasta datos comprobados; no conmuta aplicación ni DNS). Respaldo `.cms`: descifrar en el Mac con la clave privada, comprobar el SHA-256 del paquete y `pg_restore` en una base nueva del destino (el material descifrado no sale del Mac sin cifrar).
2. **Verificar los datos** con `deploy/verify-restore.sh verify <host-restaurado> <línea-base>`: exige coincidencia **exacta** de conteos por tabla, revisión de Alembic (igual a la del repositorio) y huella lógica; descifra **todas** las entradas QR y verifica su hash sin mostrar el token.
3. **Verificar el servicio (sin tocar DNS):** arrancar la aplicación contra el destino restaurado en un entorno aislado (la recuperación de `docs/operacion/recuperacion-completa.md` o V2 con un secreto de prueba separado; **no** con el secreto de producción) y ejecutar `deploy/verify-restore.sh service <mínimo-de-entradas>`, `/livez` y `/ready` (200 solo si PostgreSQL responde) y las pruebas funcionales de solo lectura de `scripts/multicloud/oci-drill/app-smoke.py` o `scripts/cloud/verify-v2-flow.py` (inicio de sesión, catálogo, reservas del cliente, QR descifrado, validación de una entrada ya usada → 409; sin ventas ni registros nuevos).
4. **Registrar tiempos** (UTC): punto recuperable, solicitud, RDS `available`, datos verificados, servicio verificado; y calcular RPO y RTO **con su alcance** (datos / servicio).
5. **Limpiar:** eliminar la RDS temporal con su recibo y verificar 0 instancias con el prefijo `restore-`; verificar RDS de producción `stopped`, 0 ALB y 0 EC2; conservar las evidencias; no dejar instantáneas finales no previstas.

## 5. Criterios de éxito (todos)
- Conteos, revisión de Alembic y huella lógica **idénticos** a la línea base.
- Entradas QR descifrables al 100 % y con hash correcto.
- `/livez` y `/ready` = 200 y pruebas funcionales de solo lectura sin fallos.
- Sin secretos, tokens, contraseñas, ARN ni IDs en logs ni evidencias.
- Recursos temporales eliminados y verificados.
Si algo falla: **no se declara restaurado**; se documenta el fallo y se repite tras corregir.

## 6. Evidencias a guardar (saneadas)
`resultado.md` con la línea de tiempo y los tiempos; salida de `verify-restore.sh verify` y `service` sin datos personales; resumen de las pruebas funcionales; verificación final de limpieza; y la lista de recursos creados y eliminados. Carpeta: `docs/evidencias/<fecha>-restauracion-aws/`.

## 7. Autorizaciones necesarias (cada una independiente)
Crear la RDS temporal (y sus costes); ejecutar SSM sobre una EC2; usar la clave privada de recuperación y los secretos originales; arrancar la aplicación de prueba; eliminar los recursos temporales; y, si se probara la conmutación de DNS o el failover AWS → OCI (`automatic=false`), una autorización aparte que **no** forma parte de este ensayo.
