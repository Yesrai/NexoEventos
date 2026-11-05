# Fases C y D — AWS V2 desplegada y validada (4-nov-2026, saneado). V2 sigue ENCENDIDA a la espera del desmontaje (Fase E).

Horas en hora de Perú. Precondiciones: sesión nueva (temporizador reiniciado a 4:00 h por la usuaria), crédito 9,80 de 50 usados (último dato confirmado), RDS `stopped`, plan V2 regenerado y verificado **27/0/0** (`verificar-plan-v2.py`), AMI `ami-0b9d9f97ca9623d3a` `available`, estado de V2 vacío.

## C — Despliegue
| Hora | Evento |
|---|---|
| 11:22 | `start-db-instance` (solo la RDS); `available` a las 11:30 (8 min) |
| 11:30–11:32 | `terraform apply` del plan guardado: **27 creados, 0 modificados, 0 destruidos** |
| 11:33 | Los 2 destinos del ALB `healthy` (≈ 1,5 min tras el apply) con health check `/healthz` (readiness con PostgreSQL) |

**TLS `verify-full` real (observación 14), en las dos instancias:** `/etc/nexoeventos/rds-ca-bundle.pem` con 1 certificado (la CA fijada), 0644; `backend.env` 0600 root; API y nginx `active`; la URL tiene `sslmode=verify-full` y la CA fijada; la API **conecta con TLS 1.3 (`ssl=True`)**; con **otra CA** (la del sistema) la conexión es **RECHAZADA**. 0 coincidencias de secretos en el log de arranque. Límite: la prueba negativa demuestra la validación de la CA; no se probó por separado un nombre de host distinto.
**ALB:** el certificado de ACM se valida correctamente (verificación TLS 0, TLS 1.3); HTTP 80 → 301 a HTTPS; `/livez`, `/healthz`, `/` y `/api/events` → 200.

## D1 — `/livez` en instancias reales del ASG (observación 13)
`/livez` = 200 en ambas instancias antes del cambio (Nginx → `/health`, sin PostgreSQL). Cambio in situ `ami_includes_livez = true` (**0 a crear, 1 a modificar, 0 a destruir**; solo `health_check.path` `/healthz` → `/livez`): los 2 destinos siguieron `healthy` durante 2 min.

## B2 — Autohealing (observación 9) — `20261104-b2-autohealing-v2/`
Con 5 solicitudes/s (4 clientes, `/api/events` y `/healthz`, por el ALB con el certificado real) se detuvo la API de una instancia (t = 28,7 s):
- ALB la marcó `unhealthy` a los **22,6 s**; el ASG la marcó `Unhealthy` y empezó a terminarla a los ≈ 31 s; la sustituta se lanzó, se registró a los ≈ 39 s y fue `healthy` a los **138,4 s: capacidad de 2 destinos restaurada ≈ 110 s tras el fallo** (sin intervención manual; el valor lo da el historial de estados).
- Cliente: 2 112 solicitudes, **52 errores 502 (todos entre 29,8 y 50,2 s, antes de que el ALB detectara)**, 0 errores después; disponibilidad 97,5 % global (`/api/events` 97,7 %, `/healthz` 97,3 %). CloudWatch: `HealthyHostCount` mínimo **1**, nunca 0; 52 5xx de destino en 1 minuto. La instancia sana recibió 630 solicitudes sin 5xx.
- Límites: los registros de Nginx de la instancia terminada se perdieron (`CalledProcessError`); el campo `both_healthy_again_at` salió `null` por un **fallo de medición del script** (el historial solo guarda cambios y se comparaba con la restauración manual, posterior): **corregido** en `v2-failover-test.py`; el valor correcto se tomó del historial de estados. La restauración de la API en la instancia ya terminada falló (esperable) y se registró.

## D2 — Failover de RDS con V2 y `/livez` (observación 10) — `20261104-d2-failover-rds-v2/`
`reboot-db-instance --force-failover` con 6 solicitudes/s (`/api/events`, `/healthz`, `/livez`):
- Eventos de RDS: failover iniciado 11:48:56, **completado 11:49:35 (≈ 39 s)**. `describe-db-instances` marcó `rebooting` y `available` a los ≈ 92 s; **la AZ primaria reportada no cambió** (inexplicado; no se interpreta).
- **Hipótesis principal CONFIRMADA:** los 2 destinos **no pasaron a no sanos en ningún momento** y el ASG **no lanzó ni terminó instancias** (0 actividades). `/livez`: 803/803 respuestas 200.
- **Hipótesis secundaria NO confirmada:** las peticiones que usan la base **no devolvieron 503 con `Retry-After`**: 6 de 2 412 (3 `/api/events`, 3 `/healthz`) agotaron los 15 s del cliente (`ReadTimeout`) entre 30 y 56 s; disponibilidad API 99,6 %, salud 99,8 %; latencia de las respuestas correctas p95 ≈ 0,4 s, máx. 1,4 s. Es decir, la API retiene la petición mientras espera a PostgreSQL en lugar de fallar rápido. **Mejora identificada (no implementada):** acotar los tiempos de espera de conexión/consulta y el pool (`DB_POOL_TIMEOUT`, `statement_timeout`, keepalives TCP) para responder 503 con `Retry-After` en segundos.
- Límite de diseño del script: esperaba un cambio de AZ que no ocurrió y por eso agotó los 420 s (≈ 6 min de más de observación; sin efectos).

## Alarmas de V2 (observación 1, parte V2)
Las 5 alarmas (`alb-5xx-destino`, `alb-destinos-no-sanos`, `alb-latencia-p95`, `alb-sanos-bajo-lo-deseado`, `asg-en-servicio-bajo-lo-deseado`) pasaron de `INSUFFICIENT_DATA` a `OK` entre las 11:31 y las 11:34 (1 acción SNS ejecutada en cada una, la de OK) y **ninguna pasó a ALARM durante B2 ni D2** (el fallo duró ≈ 20 s, por debajo de sus periodos de evaluación). **Su activación real no se ha demostrado.**

## Estado al cierre de esta evidencia
V2 (27 recursos) y la RDS **encendidas**; V1 (EC2) `running`. Plan de destrucción de V2 preparado y verificado (`Plan: 0 to add, 0 to change, 27 to destroy`: solo recursos de V2, incluida la regla 5432 aditiva del SG de la RDS), **no ejecutado**: requiere confirmación explícita. Coste estimado de la ventana hasta ahora ≈ 0,1 USD (≈ 0,13 USD/h).
