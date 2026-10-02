# Configuración de producción preparada

## Estado verificable

La configuración local prepara Nginx, FastAPI persistente, cookies seguras, orígenes explícitos, CSRF, límites de autenticación y health checks. No existe todavía un dominio ni certificado emitido, por lo que HTTPS permanece preparado y no operativo.

En `APP_ENV=production` el backend se niega a iniciar si `SESSION_COOKIE_SECURE` no es verdadero, si algún origen no usa HTTPS o si faltan las claves de cifrado y derivación de seguridad.

## Secretos

`DATABASE_URL`, `TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY` son secretos. La clave de entradas debe respaldarse separada de PostgreSQL: restaurar la base sin esa versión de clave impide recuperar los QR. Los archivos reales viven fuera del repositorio con permisos `0600`; los ejemplos solo contienen marcadores.

La propuesta Terraform solicita a RDS administrar la contraseña maestra en Secrets Manager. Antes del despliegue debe verificarse que Learner Lab permita esa operación y que `LabRole` pueda leer únicamente el secreto requerido. Si se deniega, hay que elegir otro mecanismo autorizado sin guardar la contraseña en variables, planes o estado versionado.

## Límites de inicio de sesión

Los fallos se agrupan mediante HMAC del correo normalizado y la dirección de origen; esos datos no se guardan en claro. Cinco fallos dentro de quince minutos bloquean esa combinación durante quince minutos. El estado reside en PostgreSQL y se comparte entre workers. Esta protección reduce fuerza bruta básica, pero no sustituye WAF, límites perimetrales o monitoreo para una exposición real.

## Decisiones pendientes

1. Dominio público y control de su DNS.
2. Emisión y renovación del certificado TLS.
3. Confirmación de acceso de `LabRole` al secreto administrado por RDS.
4. IP administrativa `/32` o uso confirmado de Session Manager.
5. Retención definitiva de logs y responsable de alertas.
