# EV08 — recepción real de logs y alarma

Fecha de ejecución: 10 de octubre de 2026, 23:37 Lima (11-oct 04:37 UTC). Versión de aplicación desplegada: `7955e7e`; automatización de observabilidad preparada desde `984bb83` con cambios locales revisados en esta sesión.

## Resultado comprobado

- Identidad esperada y región `us-east-1`: comprobadas, sin registrar el ID de cuenta.
- Plataforma: Amazon Linux 2023; paquete efectivo `amazon-cloudwatch-agent-1.300071.0-1.amzn2023.x86_64`.
- Rol efectivo de la instancia: la simulación autorizó `logs:CreateLogStream` y `logs:PutLogEvents`; no se modificó IAM.
- Agente: estado `running` y configuración `configured` comprobados por SSM.
- Fuentes reales: `/var/log/nexoeventos/api.log`, `/var/log/nginx/nexoeventos-access.log` y `/var/log/nginx/nexoeventos-error.log`.
- Recepción: un stream de FastAPI y un stream de Nginx, ambos con `lastEventTimestamp` posterior a la instalación. Una solicitud ficticia `GET /_observability/ev08-<fecha>` devolvió HTTP 204 y tuvo exactamente una coincidencia en CloudWatch Logs.
- Minimización: el formato Nginx conserva fecha, método, ruta sin query string, estado, bytes, tiempo e ID de solicitud. Omite IP, cookies, autorización, referencia, agente de usuario y cuerpo. Uvicorn mantiene `--no-access-log`.
- Escaneo de la ventana: cero coincidencias para contraseña, Authorization, Cookie, cookies de sesión/CSRF, `token=`, Bearer y `DUCKDNS_TOKEN`. Se contaron coincidencias sin guardar mensajes.
- Retención: los grupos conservan 7 días, administrados por Terraform. El agente no define `retention_in_days` ni requiere `logs:PutRetentionPolicy`.

## Alarma comprobada

La alarma estaba `OK`. Detecta el promedio de `CPUUtilization` de la EC2 por encima de 80 % durante dos periodos consecutivos de 300 segundos, es decir, 10 minutos de evaluación. Usa `treat_missing_data=missing`. `ActionsEnabled=True`, pero tiene cero `AlarmActions`, cero `OKActions` y cero `InsufficientDataActions`: **observa, pero no notifica a nadie**.

## Limitaciones

- No se capturó el contenido de mensajes ni identificadores innecesarios; esta evidencia textual proviene de API/SSM y no sustituye una captura de consola si la rúbrica la exige.
- La RDS permaneció detenida. Se comprobó el proceso FastAPI mediante `/health`; no se repitió E01 ni R01.
- La primera configuración usaba `initial_position`, propiedad rechazada por el esquema efectivo. Se retiró y el log histórico de FastAPI se rotó antes de la primera ingesta; la copia local se conservó en la instancia.

Configuración reproducible: `ansible/playbooks/observability.yml`. Verificación: `scripts/cloud/verify-observability.sh`.
