# Autohealing de V2: reemplazo automático de una EC2 · 22-oct-2026

Evidencia de **autohealing** (no de disponibilidad de la API). Se detuvo la API de UNA de las dos instancias (sin detener la EC2) con tráfico ligero (4 clientes independientes, 5 solicitudes/s, rutas al azar `/api/events` y `/healthz`) y se volvió a arrancar.

**Qué se demostró**
- El ALB retiró el destino no sano; los destinos sanos bajaron de 2 a 1 en el minuto de la caída (CloudWatch, `cloudwatch-alb.json`) y el servicio siguió atendiendo con la otra instancia.
- A las 16:38:48Z el Auto Scaling, con `health_check_type = ELB`, **retiró la instancia no sana «en respuesta a un fallo del health check de ELB» y lanzó una nueva** (`Cause` de las dos actividades de escalado), sin intervención manual. La instancia nueva quedó `InService/Healthy` y sana en el ALB hacia las 16:41 (≈ 2,5 min), y el grupo volvió a 2 instancias sanas en 2 zonas.
- Una caída de la API de ~50 s, aunque se restaure, provoca el reemplazo; la primera ejecución (~40 s, `../tolerancia-fallos-v2-20261022`) midió detección en 20 s y recuperación en 15,8 s sin reemplazo.

**Qué NO se midió correctamente (limitaciones)**
- **No se midió la disponibilidad de la API**: en esta repetición no se conservan los errores por ruta (`/api/events` frente a `/healthz`) ni los tiempos de detección y recuperación, porque el script falló al contar solicitudes en Nginx de la instancia ya terminada (`InvalidInstanceId`) antes de escribir sus resultados. Solo hay las cifras agregadas del ALB: 40 respuestas 5xx del destino en ese minuto y 0 generadas por el ALB.
- En la primera ejecución el ALB «bloqueó por paridad» el tráfico alternado: los errores fueron solo de `/healthz` y la disponibilidad del 90,9 % no representa la de la API.
- No se repetirá la prueba; no hay una cifra válida de disponibilidad de la API durante la caída.
