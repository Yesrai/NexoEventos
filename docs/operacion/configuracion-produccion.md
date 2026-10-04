# Configuración de producción preparada

La configuración local incluye Nginx, FastAPI persistente sin `--reload`, cookies `Secure`, orígenes HTTPS explícitos, CSRF, límite de autenticación y health/readiness sin detalles sensibles. En producción el backend rechaza el arranque si faltan claves, cookies seguras u orígenes HTTPS.

Amazon Linux 2023 es la plataforma elegida. El instalador reproducible valida el SO, usa DNF, conserva Python del sistema, crea un `venv` Python 3.11 y fija Node 24.21.0/dependencias. Uvicorn corre como `nexoeventos`, sin shell ni privilegios; systemd usa endurecimiento y lee un archivo root-only antes de cambiar de usuario.

## Secretos

`DATABASE_URL`, `TICKET_ENCRYPTION_KEY`, `SECURITY_HASH_KEY` y token DuckDNS se solicitan sin eco. Se escriben atómicamente bajo `/etc/nexoeventos`, `root:root 0600`; no entran en `user_data`, Terraform, Git o capturas. Migración y aplicación usan usuarios/archivos distintos. La identidad maestra RDS solo prepara roles y no se persiste.

Terraform solicita a RDS administrar el secreto maestro. El archivo local de FastAPI no resuelve el permiso de `secretsmanager:GetSecretValue`. El bootstrap consulta el ARN y prueba la lectura con el perfil real; si AWS la deniega, no intenta cambiar IAM y permite que la propietaria introduzca el secreto manualmente sin eco. El 3 de octubre de 2026 se comprobó en la EC2 real que el rol de instancia puede leer ese secreto; la credencial se usó en memoria y no se persistió.

## DNS y certificados

La decisión es DuckDNS + Let's Encrypt. La usuaria confirmó el 2 de octubre que `nexoeventos-demo.duckdns.org` quedó agregado a su cuenta. Esto confirma el nombre, no la resolución hacia una EC2 ni HTTPS: ambos se comprobaron el 3 de octubre de 2026: DuckDNS resolvió a la IPv4 de la EC2 y Let's Encrypt emitió un certificado válido hasta el 1 de enero de 2027. El timer actualizará la IP y Certbot emitirá/renovará el certificado.

El token no se solicita por chat ni se guarda en Git, argumentos, logs o capturas. El token que finalmente se instaló el 3 de octubre se introdujo mediante prompt sin eco; su valor no se conserva en esta documentación. Solo debe rotarse si existe evidencia de exposición o como mantenimiento planificado.

ACM sí admite actualmente certificados públicos exportables para EC2 y otras cargas; ya no es correcto afirmar que siempre requiera ALB/CloudFront. El certificado exportable predeterminado tiene costo y ciclo de 198 días desde el cambio anunciado en 2026. Para V1 se elige ACME gratuito por costo y menor dependencia de permisos AWS, no por una imposibilidad técnica de ACM.

## Controles en cloud (actualizado el 3 de octubre de 2026)

Comprobados en la EC2 real: token DuckDNS instalado mediante prompt sin eco en un archivo `root:root 0600`; lectura del secreto maestro con el rol de instancia; instalador AL2023; resolución DNS y emisión TLS con prueba externa; Session Manager sin SSH. Pendiente: responsable y retención final de alertas/logs. La lista original se conserva como referencia histórica:

1. Rotar personalmente el token DuckDNS si corresponde e introducirlo mediante el prompt sin eco.
2. Lectura del secreto maestro con el rol de instancia o uso manual controlado.
3. Ejecución del instalador y verificación de paquetes en la AMI real.
4. Resolución DNS, emisión/renovación TLS y prueba externa.
5. IP administrativa `/32` o Session Manager si su permiso se confirma.
6. Responsable y retención final de alertas/logs.
