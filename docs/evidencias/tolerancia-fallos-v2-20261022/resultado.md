# Tolerancia a fallos de AWS V2 · 22-oct-2026

Con tráfico ligero y constante (5 solicitudes/s, solo lecturas `/api/events` y `/healthz`, una conexión por solicitud contra el ALB), se detuvo la API (`systemctl stop nexoeventos-api`) de UNA de las dos instancias (la EC2 no se detuvo ni se terminó) y se volvió a arrancar. Sin datos ni fixtures.

| Evento | Tiempo (s desde el inicio) |
|---|---:|
| Orden de detener la API | 28,8 |
| ALB marca la instancia `unhealthy` | 48,8 (**20,0 s** tras la orden) |
| Orden de restaurar la API | 69,3 |
| Ambas instancias `healthy` otra vez | 88,4 (**15,8 s** tras restaurar) |

- Instancias sanas en el ALB (CloudWatch, mínimo por minuto): 2 → **1** durante ~40 s → 2; nunca 0.
- Errores: 25 respuestas 502 de 275 solicitudes, todas entre 30,1 y 47,7 s (antes de que el ALB retirara el destino); 0 errores después de la detección y 0 5xx del propio ALB (`HTTPCode_Target_5XX_Count` = 25).
- ASG: ambas instancias `InService/Healthy` todo el tiempo y **sin actividades nuevas** (no hubo reemplazo).
- Estado final: 2 destinos `healthy`, 2 instancias `InService`.

**Limitación de la prueba (honestidad de la evidencia):** las solicitudes alternaban `/api/events` y `/healthz` y el ALB (`least_outstanding_requests`, un solo cliente secuencial) quedó «bloqueado por paridad»: todo `/api/events` fue a la instancia sana (138 solicitudes, 0 errores) y `/healthz` fue a la instancia detenida. Por eso los 25 errores son solo de `/healthz` y la disponibilidad del 90,9 % no representa la de la API; sí son válidos el tiempo de detección, la recuperación, la retirada del destino y la ausencia de reemplazo. Para medir el efecto sobre la API conviene repetir con rutas en orden aleatorio.
