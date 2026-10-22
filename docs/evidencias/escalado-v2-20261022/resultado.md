# Auto Scaling de V2: 2 → 3 → 2 instancias con carga Argon2 controlada · 22-oct-2026

Una sola prueba, con la política existente (CPU media del grupo, objetivo 40 %; sin cambios de Terraform ni de política). Carga: k6 `login_rate`, 8 inicios de sesión/s (≤ 50 usuarios ficticios `k6-*`), mismo origen de tráfico que las mediciones V1/V2. Datos originales intactos (huella idéntica; usuarios ficticios borrados; EC2 de V1 encendida solo para ello y detenida).

| Hito (UTC) | Hora | Desde el inicio de la carga |
|---|---|---:|
| Inicio de la carga | 16:56:53 | 0 |
| CPU media ≈ 56-57 % por instancia (2 instancias) | desde ~17:01 | ~4 min |
| Alarma alta (`AlarmHigh`) → ALARM | 17:04:59 | **8 min 6 s** |
| Capacidad deseada 3 y lanzamiento de la instancia | 17:05:15 | 8 min 22 s |
| Instancia nueva `InService` | 17:05:20 | 8 min 27 s |
| **Tercera instancia `healthy` en el ALB** | ≈ 17:05:50 (HealthyHostCount mínimo 3 desde el minuto 17:06) | **≈ 9 min** |
| Fin de la carga (k6 detenido por el orquestador) | 17:05:54 | 8 min 59 s de k6 |
| Alarma baja → ALARM, capacidad deseada 2 | 17:22:07 | 16 min tras el fin de la carga |
| Instancia más antigua en `Terminating`/`draining` | 17:22:20 | |
| De nuevo 2 instancias `InService` y 2 destinos sanos | **17:23:26** | 1 min 19 s tras la decisión |

- k6: 4 202 inicios de sesión, 7,9/s, **0 errores**, p50 258 ms, p95 395 ms, p99 1,19 s (máx. 2,0 s); 0 respuestas 5xx del destino y 0 del ALB; destinos sanos nunca < 2.
- CPU de las 2 instancias originales ≈ 56-58 % (5 min); créditos excedentes 0; memoria disponible mín. ≈ 1 320 MB; RDS: CPU máx. 6,5 %, conexiones máx. 18, memoria liberable mín. 143 MB.
- El grupo terminó con la instancia nueva y la `e173fa`; se retiró la más antigua (política `OldestInstance`), sin intervención manual.

**Limitaciones:** (1) El orquestador falló al sondear la instancia nueva por Session Manager (aún no registrada) y cortó la carga ~55 s después de que la tercera instancia quedara sana; por eso no hay los ≥ 2 min previstos de evidencia con 3 instancias (ni reparto de solicitudes entre las 3). Los hitos de escalado se reconstruyeron con el estado del ASG, las alarmas y CloudWatch. (2) El regreso a 2 se observó con un vigilante de solo lectura (sin carga). (3) Con 2 instancias la CPU media (≈ 56 %) superó el objetivo (40 %) tras los 3 min exigidos por la alarma más el tiempo de agregación de CloudWatch.
