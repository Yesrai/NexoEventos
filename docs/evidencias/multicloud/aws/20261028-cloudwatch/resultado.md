# CloudWatch: series originales recuperadas (AWS, solo lectura)

- **Procedencia:** CloudWatch `GetMetricData` (solo lectura), perfil de laboratorio, `us-east-1`, exportado el 2026-10-28 (~21:04Z) con `scripts/observability/export-cloudwatch.py` (esquema 2). Sin Cost Explorer, sin cambios en recursos.
- **Archivo:** `series-originales.json` (40 series originales por recurso con ID enmascarado `…abcd`; `points_derivados` solo para Zabbix, no es dato original). SHA-256 de la exportación: `74aa13356d8d33065f08df9b4e78b67191cd31234453a33e46fa6feeab62fd41`.
- **Gráficos:** `graficos/` (40 SVG, sin interpolación; rótulo con fuente, periodo UTC, resolución observada y n.º de puntos). Los huecos rompen la línea.
- **Marcas de tiempo:** epoch UTC. **Unidades** (documentadas por AWS para cada métrica, no devueltas por la exportación): CPUUtilization = %, DatabaseConnections = recuentos, RequestCount/HTTPCode_Target_5XX_Count = recuentos por minuto (Sum), TargetResponseTime = segundos, NetworkIn/Out = bytes por periodo, GroupInServiceInstances = instancias.

## Ventanas y resolución observada (original, no agregada por nosotros)
| Ventana UTC | Contenido | Resolución | Puntos |
|---|---|---|---|
| 19-oct 00:00–20-oct 00:00 (V1) | RDS CPU y conexiones | **60 s** | 1340 / 1341 |
| | EC2 de V1 CPU, red | 300 s (monitoreo básico de EC2) | 121 por métrica |
| 22-oct 14:00–23:00 (V2) | RDS CPU, conexiones | 60 s | 217 / 218 |
| | ALB RequestCount, TargetResponseTime | 60 s (solo minutos con datos: 140 / 57) | |
| | ASG GroupInServiceInstances | 60 s | 212 |
| | EC2 (11 series: instancias del ASG ya terminadas) | 300 s | 2–34 por serie |
| 23-oct 00:00–03:00 | RDS CPU, conexiones | 60 s | 103 |
| | EC2 | 300 s | 12 por métrica |

La ventana de V1 no tiene datos de ALB/ASG porque V1 no los tenía (0 puntos, esperado). La del 23-oct no tiene ALB/ASG porque V2 ya no existía.

## Lectura verificable de las series (cálculo sobre el JSON)
- **RDS V1 (19-oct):** CPU 3,4–16,6 %; conexiones máx. 11.
- **RDS V2 (22-oct):** CPU máx. 15,1 %; conexiones máx. 22 (coincide con la medición documentada: 15 % y 22).
- **ALB (22-oct):** 40 630 solicitudes en 14:00–23:00Z (la medición de carga documentó 35 366 en su ventana; el resto es otro tráfico del mismo día). TargetResponseTime máx. 0,301 s (Average por minuto).
- **5xx del destino:** 25 a las 16:03Z y 40 a las 16:38Z; coinciden con las dos pruebas de tolerancia a fallos documentadas (`tolerancia-fallos-v2-20261022` y `-b`), no con la medición de carga (0 5xx en su ventana).
- **ASG:** 0 → 2 (15:10Z) → 3 (17:05Z) → 2 (17:22Z) → 0 (17:31Z, destrucción), coherente con `escalado-v2-20261022`.
- **RDS 23-oct (00–03Z):** CPU máx. 40,5 %; conexiones máx. 3 (actividad de failover/respaldo; no se atribuye aquí a un evento concreto sin cruzar con `20261023-rds-multiaz`).

## Límites
- No hay métrica de memoria de EC2 (requiere agente, no desplegado). Las EC2 del ASG solo existen mientras vivieron.
- Los datos de 1 min de 19-oct de resolución 1 min caducan hacia el 3-nov (después solo quedan a 5 min); esta copia ya los conserva.
- No se recuperó el periodo del failover Multi-AZ en una ventana propia más allá de 23-oct 00–03Z; no se amplió para no inventar correspondencias.
