# Integraciones de NexoOps — qué requieren los servicios existentes

Contexto (del repositorio): en la VM de Azure, Grafana y Zabbix se sirven por el Nginx HTTPS existente bajo `/grafana/` y `/zabbix/`; el NSG solo admite 443 desde la IP /32 autorizada. NexoOps aún **no** está desplegado (`deploy/ops-center/nginx-ops.conf` marca `/ops/` como «NO aplicado todavía»).
Hasta ahora **ninguna** integración se ha ejecutado contra un servicio real: el resultado de `check-integrations` sin configuración es `NOT_CONFIGURED`, no PASS.

## Grafana
| Requisito | Detalle |
|---|---|
| `GRAFANA_URL` | `https://<VM>/grafana` (subpath soportado) |
| `GRAFANA_TOKEN` | Token de **cuenta de servicio con rol Viewer** (Administración → Cuentas de servicio). Solo ve lo que ese rol permite. |
| `GRAFANA_CAFILE` | Si el certificado de la VM es propio, el .pem fijado (la verificación TLS nunca se desactiva). |
| Incrustar paneles | Opcional y **cambia Grafana**: `allow_embedding = true` en `grafana.ini` (y `cookie_samesite` acorde) + `NEXOOPS_GRAFANA_EMBED=1`. Requiere autorización: `instalar-t4-en-vm.sh` compara huellas de `grafana.ini` y fallaría. Sin esto, NexoOps ofrece enlaces Abrir/Editar. |
| Red | Debe alcanzarse desde donde corra NexoOps (la propia VM por `https://127.0.0.1/grafana` evita el NSG). |

## Zabbix
| Requisito | Detalle |
|---|---|
| `ZABBIX_URL` | `https://<VM>/zabbix` (el API vive en `/api_jsonrpc.php`) |
| `ZABBIX_TOKEN` | Token de API (Zabbix ≥ 5.4) de un usuario con rol **Usuario** y permiso de **solo lectura** sobre los grupos de hosts. |
| `ZABBIX_AUTH_MODE` | `bearer` (Zabbix ≥ 7.0, por defecto) o `body` (6.x). **La versión instalada se desconoce**; `check-integrations` informa `apiinfo.version`. |
| `ZABBIX_CAFILE` | Igual que Grafana. |
Solo se permiten `host.get`, `problem.get`, `event.get`, `apiinfo.version`.

## Correo
No existe SMTP en el repositorio (T4 usa Azure Monitor para alertas, sin SMTP). Se necesita un proveedor transaccional con SMTP: `NEXOOPS_SMTP_HOST/PORT/USER/PASSWORD/FROM` (587+STARTTLS o 465), remitente verificado y SPF/DKIM del dominio. Guardar la contraseña solo en el entorno del servicio (0600), nunca en el repositorio.

## Prueba real de solo lectura (cuando haya tokens)
```bash
export GRAFANA_URL=… GRAFANA_TOKEN=… ZABBIX_URL=… ZABBIX_TOKEN=… [GRAFANA_CAFILE=… ZABBIX_CAFILE=…]
export NEXOOPS_OTP_SECRET=<≥32 caracteres> NEXOOPS_ENV=dev NEXOOPS_COOKIE_SECURE=0 NEXOOPS_MAIL_MODE=outbox
PYTHONPATH=. python -m nexoops check-integrations     # solo GET / *.get; escribe integration-check.json (0600, sin secretos)
NEXOOPS_ENV=production NEXOOPS_MAIL_MODE=smtp NEXOOPS_ADMIN_EMAIL=<tu correo> … python -m nexoops send-test-mail   # envía UN correo real
```
Adjunta `integration-check.json` y la captura de la bandeja como evidencia solo si el resultado es PASS real.
