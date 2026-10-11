# EV11 — resultado cloud E01

Ejecución `20261009t145510-f79f`, versión AWS `7955e7e`. Ventana medida: 2026-10-09 14:55:56–15:00:56 UTC (09:55:56–10:00:56 Lima). Datos exclusivamente ficticios; no se conservaron contraseñas, cookies, cuerpos privados ni tokens QR.

## Resultado HTTP

- 20/20 registros preparados correctamente antes de medir; p95 de registro 629.2 ms, excluido de la ventana.
- 20 usuarios virtuales, rampa 30 s y 300 s medidos.
- 2 520 solicitudes; 8.4 solicitudes/s.
- p50 382.3 ms; p95 421.2 ms; p99 585.1 ms.
- 2 520 respuestas correctas; 0 errores inesperados (0 %); 0 conflictos `409`.
- E01: **cumple** p95 < 2 s y errores inesperados < 1 % en el escenario definido.

| Operación | Solicitudes | p95 | Estados |
|---|---:|---:|---|
| catálogo | 1 504 | 417.6 ms | 1 504 × 200 |
| detalle | 659 | 406.8 ms | 659 × 200 |
| mis entradas | 225 | 440.1 ms | 225 × 200 |
| reserva de un cupo | 132 | 489.5 ms | 132 × 201 |

## Integridad en PostgreSQL

Comprobación posterior por SSM con el rol separado de migración, sin mostrar filas ni identificadores privados:

| Control | Resultado |
|---|---:|
| capacidad del fixture `[CARGA]` | 1 000 |
| contador reservado | 132 |
| suma de cantidades reservadas | 132 |
| reservas | 132 |
| claves de idempotencia distintas | 132 |
| entradas emitidas | 132 |
| sobreventa | no |
| reserva duplicada | no |

Cada éxito HTTP corresponde a exactamente un cupo, una reserva y una entrada. Como no se agotó el evento, esta ejecución no produjo conflictos esperados; el control concurrente de último cupo permanece cubierto por la prueba específica de la aplicación, no por E01.

## Métricas AWS

CloudWatch, sobre la ventana y minutos adyacentes:

- EC2 `CPUUtilization`: 2 puntos de monitoreo básico; promedio 3.53 %, máximo 6.05 %.
- RDS `CPUUtilization`: 7 puntos; promedio 4.66 %, máximo 5.37 %.
- RDS `DatabaseConnections`: 7 puntos; promedio 8.86, máximo 10.
- alarma de CPU EC2: estado `OK`, umbral 80 %, 2 periodos de 300 s.

La EC2 usa monitoreo básico, por lo que no existe resolución de un minuto para toda la ventana. Los grupos de CloudWatch Logs conservan retención de 7 días, pero no tenían streams: la recepción de logs **no** queda demostrada. El diagnóstico encontró que `amazon-cloudwatch-agent` no está instalado ni configurado; `LabRole` sí evaluó `logs:CreateLogStream` y `logs:PutLogEvents` como permitidos. Corregir el agente es un pendiente separado y no altera el resultado HTTP/BD de E01.
