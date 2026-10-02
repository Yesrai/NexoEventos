# Despliegue de aplicación en Amazon Linux 2023

La V1 usa la AMI Amazon Linux 2023 `x86_64`; no usa instrucciones de Ubuntu. `deploy/install-amazon-linux-2023.sh` falla si detecta otro sistema y utiliza [DNF](https://docs.aws.amazon.com/linux/al2023/ug/package-management.html). Instala Nginx, systemd nativo, Python 3.11 en un `venv`, PostgreSQL client y AWS CLI v2. No cambia `/usr/bin/python3`, tal como exige la [guía de Python de AL2023](https://docs.aws.amazon.com/linux/al2023/ug/python.html). Node.js 24.21.0 se descarga del distribuidor oficial y se valida con un SHA-256 fijado, porque el repositorio AL2023 no garantiza exactamente la versión de `.nvmrc`.

Las dependencias directas se declaran en `backend/requirements-production.txt` y el cierre completo está fijado en `backend/requirements-production.lock`; Certbot tiene su propio lock, el frontend usa `package-lock.json` y Terraform `infra/aws/.terraform.lock.hcl`. La ejecución real sobre una EC2 AL2023 sigue pendiente del `apply` autorizado; la compatibilidad local comprobada abarca sintaxis, compilación, tests y las versiones/paquetes publicados para AL2023.

## Secuencia reproducible

1. Confirma identidad/cuenta con `scripts/terraform-account.sh` y revisa el plan aprobado.
2. Copia el commit aprobado a `/opt/nexoeventos`; no copies `.env`, `work/`, estados ni planes.
3. Ejecuta como root `/opt/nexoeventos/deploy/install-amazon-linux-2023.sh`. No inicia la aplicación.
4. Reclama personalmente el subdominio DuckDNS. Introduce el token solo en el prompt de `bootstrap-rds-secrets.sh`; nunca en Git, historial de shell, capturas o argumentos.
5. Ejecuta `bootstrap-rds-secrets.sh <rds-id> <región> <dominio-completo>`. El script intenta leer el secreto maestro administrado por RDS con el rol de instancia. Si se deniega, lo informa y solicita el valor manualmente sin eco; no cambia IAM. La credencial maestra se usa en memoria para preparar roles y no se guarda.
6. Carga como root `/etc/nexoeventos/migration.env`, ejecuta `backend/.venv/bin/alembic upgrade head` y descarga la variable del entorno. El archivo queda `root:root 0600` y no lo consume el servicio.
7. Inicia `nexoeventos-api.service`. systemd lee `/etc/nexoeventos/backend.env` antes de bajar privilegios a `nexoeventos`; el usuario de la aplicación no puede leer ni modificar el archivo.
8. Ejecuta `deploy/configure-https.sh <dominio>`. Primero publica HTTP únicamente para ACME, ejecuta Certbot de forma interactiva y luego instala la plantilla HTTPS. Verifica externamente antes de declarar HTTPS operativo.

## Identidades y secretos

| Identidad | Uso | Persistencia |
|---|---|---|
| maestro RDS | crear roles iniciales | no se guarda; lectura de Secrets Manager o entrada sin eco |
| `nexoeventos_owner` | propietario `NOLOGIN` de objetos | PostgreSQL |
| `nexoeventos_migrator` | Alembic mediante `SET ROLE` | `/etc/nexoeventos/migration.env`, root 0600 |
| `nexoeventos_app` | FastAPI con permisos limitados | `/etc/nexoeventos/backend.env`, root 0600 |
| usuario Linux `nexoeventos` | proceso Uvicorn sin privilegios | sin shell y sin sudo |

`TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY` son distintos y deben respaldarse por separado de la base. El archivo local resuelve el arranque de la aplicación, pero **no concede** acceso al secreto maestro administrado por RDS: ese permiso se comprueba en el paso 5 y sigue pendiente hasta disponer de la instancia/rol reales.

## DuckDNS y HTTPS

La consulta DNS del 2 de octubre de 2026 devolvió NXDOMAIN para `nexoeventos-demo.duckdns.org`, `nexoeventos-demo-2026.duckdns.org` y `nexoeventos-upeu-demo.duckdns.org`. Esto no confirma que el nombre esté libre en el registro interno de DuckDNS. La persona usuaria debe iniciar sesión en [DuckDNS](https://www.duckdns.org/), intentar añadir primero `nexoeventos-demo` y comunicar únicamente el FQDN aceptado, nunca el token.

El timer `nexoeventos-duckdns.timer` actualiza la IP cada cinco minutos mediante la [API oficial de DuckDNS](https://www.duckdns.org/spec.jsp). El token reside en `/etc/nexoeventos/duckdns.env` (`root:root`, `0600`) y se pasa a `curl` por entrada estándar, no por argumentos ni logs. Certbot/Let's Encrypt es la opción V1 gratuita.

La afirmación histórica de que ACM no podía usarse con EC2 sin ALB/CloudFront ya no es correcta: ACM ofrece [certificados públicos exportables](https://docs.aws.amazon.com/acm/latest/userguide/acm-exportable-certificates.html) para cargas como EC2. AWS [redujo la validez pública a 198 días en febrero de 2026](https://aws.amazon.com/about-aws/whats-new/2026/02/aws-certificate-manager-updates-default/); la opción exportable tiene costo y requiere despliegue/renovación. Por costo y permisos no comprobados se conserva ACME/Let's Encrypt para V1, sin afirmar que ACM sea técnicamente imposible.

## Red y logs

FastAPI escucha solo en `127.0.0.1:8000`; PostgreSQL no es público. El SG expone 443 y deja 80 para redirección/ACME. SSH permanece cerrado salvo un `/32` temporal explícito. Uvicorn no genera access log; Nginx no debe recibir secretos en URL. No se registran contraseñas, cookies o tokens QR completos.
