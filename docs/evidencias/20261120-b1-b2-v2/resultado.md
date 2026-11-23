# B1 + B2 de AWS V2 — 20-nov-2026 (UTC) — resultado saneado

Ejecutado con `scripts/v2-ops/rds-window.sh chain --minutes 75 --not-after 22:55Z --creds-until 2026-11-21T01:25Z` (autorizado explícitamente; Mac en corriente alterna; credenciales vigentes; margen de 75 + 45 min verificado antes de empezar). Sin cambios en IAM, DNS, secretos, redes ni datos; sin B3; sin failover AWS→OCI. Identificadores y direcciones enmascarados.

## Línea de tiempo
| Hora (UTC) | Hecho |
|---|---|
| 22:40:21 | Watchdog armado (apagado de seguridad a las **23:55:21**; latido máximo 20 min); verificado antes de encender |
| 22:40:22 | `start-db-instance` sobre `nexoeventos-academy-postgres` (solo esa RDS) |
| 22:45:30 | RDS `available` (B1, ≈ 5 min 8 s) |
| 22:45:38 | Plan regenerado y **revisado**: exactamente 8 creaciones permitidas + 1 modificación del ASG (0→2), 0 destrucciones, 0 sustituciones |
| 22:45:38–22:47:54 | `terraform apply` **solo del plan guardado** (≈ 2 min 16 s) |
| 22:48:13 | 2 destinos sanos en `us-east-1a` y `us-east-1b` |
| 22:48:15 | HTTPS vía ALB sin cambiar DNS (`--resolve`): `/livez` = 200, `/api/events` = 200 → **B2 completo** |

## Recursos creados por el plan (solo acciones; ver `plan-revisado-acciones.txt`)
ALB, 2 listeners (HTTP→HTTPS y HTTPS), panel de CloudWatch, 4 alarmas del ALB (5xx, destinos no sanos, destinos sanos bajo lo deseado, latencia p95) y la modificación del ASG (mínimo y deseada 0→2; máximo sin cambio = 3).

## Estado verificado a las 22:48:35Z (solo lectura)
RDS `available` (Multi-AZ) · ASG 2/2/3 con 2 instancias `InService/Healthy` (t3.small, una por zona) · ALB `active`, `internet-facing`, 2 zonas · 2 destinos `healthy` en el puerto 80 con health check `/livez` · EC2 de V1 `stopped` · alarmas de V2 con 1 acción cada una (`OK` o `INSUFFICIENT_DATA` por falta de tráfico) · watchdog armado.

## Limitaciones
Es la prueba de **despliegue** (B1+B2): no se midió disponibilidad bajo fallo, ni autohealing, ni failover de RDS con V2 (B3 y siguientes requieren autorización aparte). La entrega de correos de las alarmas no se ha probado.

## Archivos
`rds-window-log-sanitizado.txt` (registro de la ventana), `plan-revisado-acciones.txt` (acciones del plan aplicado).

---
# Cierre y limpieza (parada anticipada autorizada) — 20-nov-2026 (UTC)

Ordenada por la propietaria; ejecutada con `NEXO_ALLOW_CLOUD_CHANGES=YES scripts/v2-ops/rds-window.sh stop-now --also-v2` (ASG → 0, eliminación del ALB con etiquetas verificadas, `stop-db-instance` verificado). Sin `terraform destroy`; sin cambios en IAM, DNS, secretos ni datos. Registro en `limpieza-log-sanitizado.txt`.

## Línea de tiempo de la limpieza
| Hora (UTC) | Hecho |
|---|---|
| 23:30:30 | ASG de 2 a 0 |
| 23:31:14 | Sin EC2 de V2 en ejecución (las 2 quedaron `terminated`) |
| 23:31:15–23:31:16 | ALB `nexoeventos-academy-v2-alb` eliminado tras verificar las etiquetas `Project=NexoEventos` y `Stack=v2` |
| 23:31:17 | `stop-db-instance`; 3 avisos de «parada AVANZANDO» (Multi-AZ) |
| **23:37:58** | **RDS detenida y verificada (`PARADA_VERIFICADA`, 401 s)** |
| ≈ 23:40 | Watchdog cancelado a mano (archivo de parada) y latido retirado; 0 procesos y 0 archivos de control pendientes |

## Estado final verificado en solo lectura (23:38Z y 23:44Z)
RDS `stopped` (no solo `stopping`) · ASG mín 0 / deseada 0 / máx 3 / 0 instancias · 0 ALB · EC2 de V2 `terminated` · EC2 de V1 `stopped` · **0 EC2 en ejecución, arrancando o parándose** · 0 NAT · 0 IP elásticas · `rds-window.sh check`: 5 OK y «Watchdog: no armado».

## Qué se probó realmente (B1 + B2)
Encendido controlado de la RDS con watchdog (≈ 5 min 8 s hasta `available`); regeneración y **revisión estricta del plan** (8 creaciones + 1 modificación del ASG, 0 destrucciones); `apply` solo del plan guardado (≈ 2 min 16 s); 2 destinos sanos en `us-east-1a` y `us-east-1b` a las 22:48:13Z; HTTPS por el ALB con `/livez` = 200 y `/api/events` = 200 a las 22:48:15Z (sin cambiar DNS); limpieza completa (ASG → ALB → RDS) verificada. **No se probó:** autohealing, failover de RDS con V2, carga, entrega de correos de las alarmas, B3.

## Duración y coste (estimación con tarifas públicas, no verificada con la facturación)
RDS encendida 22:40:22–23:37:58 (≈ 58 min) · EC2 de V2 22:45:53–23:31:14 (≈ 45 min, 2 instancias) · ALB ≈ 22:47–23:31 (≈ 44 min). **≈ 0,10 USD** frente al máximo operativo autorizado de 1,50 USD. El saldo real debe leerlo la propietaria en el panel.

## Recursos que permanecen (no son cómputo)
5 alarmas de V2 y el panel de CloudWatch (≈ 0,5 USD/mes; el panel entra en la capa gratuita), grupo de destino y plantilla de lanzamiento (sin coste), 2 AMI y sus instantáneas, RDS detenida (almacenamiento) y respaldos. **La RDS volverá a arrancar sola 7 días después de la parada: hacia el 27-nov 23:37 UTC**; hay que volver a detenerla si no se usa.

## Diferencias entre AWS y el estado de Terraform (NO corregidas a propósito)
La limpieza de emergencia eliminó el ALB por la API, no por Terraform. Un `plan` de solo lectura (sin aplicar) muestra ahora, con `asg_enabled = true` (**3 a crear, 6 a modificar, 0 a destruir**) y con `asg_enabled = false` (**3 a crear, 5 a modificar, 0 a destruir**):
- **Crear:** `aws_lb.main`, `aws_lb_listener.http_redirect` y `aws_lb_listener.https` (existen en el estado pero ya no en AWS).
- **Modificar:** el panel y las 4 alarmas del ALB (siguen en AWS; sus dimensiones cambiarán al recrear el ALB) y, con `on`, el ASG (0 → 2).
**Consecuencia para la próxima sesión:** la revisión estricta de `chain` espera exactamente «8 creaciones + 1 modificación» y **bloqueará** este plan (3 + 6). No se debe ejecutar `terraform apply` a ciegas. Opciones, a decidir y autorizar entonces: (a) un `apply -refresh-only` (solo estado, sin cambios en AWS) y adaptar la revisión de `chain` al caso «reanudar» (3 creaciones + 6 modificaciones) con sus pruebas; o (b) un `destroy` dirigido y autorizado de los 5 recursos de monitoreo residuales para volver al plan de 8 creaciones. Ninguna se aplicó.

## Para volver a desplegar V2
Se conservan sin cambios: `infra/aws-v2`, `scripts/v2-ops/` (incluido el parche de `hhmm_epoch` y sus 43 pruebas simuladas), `work/terraform-envs/academy-v2-{common,on,off}.tfvars`, el estado local de Terraform, la AMI vigente, la plantilla de lanzamiento y estas evidencias. Pasos: sesión nueva de Academy → `rds-window.sh check` → resolver la deriva anterior → `chain` con horas nuevas (75 + 45 min antes de la caducidad).
