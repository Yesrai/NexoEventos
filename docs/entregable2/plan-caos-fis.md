# Caos, fallos y AWS FIS — estado y plan (SIN ejecutar; requiere autorización)

## 1. Qué se ejecutó realmente
| Caso | ¿Ejecutado? | Evidencia | Resultado medido | Límite |
|---|---|---|---|---|
| A. Fallo de una instancia EC2 | **Parcial**: se detuvo la **API/Nginx** de una instancia (no se terminó la EC2) | `tolerancia-fallos-v2-20261022/` | Detección 20,0 s; 25 de 275 solicitudes con 502 | Fallo de proceso, no de máquina |
| B. Pérdida de salud de un destino del ALB | **Sí** | Resultado, capturas 07, 08 y 09 | Destino `unhealthy` a 20 s; sanos 2→1→2 | UnHealthy no visible en la repetición de 16:38 |
| C. Sustitución por Auto Scaling | **Sí** | `tolerancia-fallos-v2-20261022-b/` | Retirada y reemplazo ≈ 2,5 min, grupo vuelve a 2 | Disponibilidad de la API no medida en la repetición |
| D. Failover RDS Multi-AZ | **Sí** (forzado por el usuario) | `20261023-rds-multiaz/failover/`, captura 11 | ≈ 14 s sin respuesta; huella idéntica | Una ejecución, sin carga de escritura concurrente |
| E. Caída completa de una zona de disponibilidad | **NO** | Ninguna | — | No se afirma |
| F. AWS Fault Injection Service | **NO** (no hay rastro en repositorio ni evidencias) | Ninguna | — | No se afirma |

## 2. ¿Es necesaria una prueba adicional?
Criterio 4 de la rúbrica pide «solución técnicamente coherente, redundante y justificada»; los casos A–D ya están medidos. E y F elevarían la evidencia, pero **no son indispensables**: se pueden presentar como **diseño no probado** con su límite declarado. Además, V2 está destruida, así que cualquier prueba de AZ/FIS exige **redesplegar ALB + ASG + RDS Multi-AZ activa**.
Viabilidad en Academy: FIS necesita un rol de servicio asumible por `fis.amazonaws.com`; en la lista de servicios de confianza de `LabRole` leída el 29-oct (≈ 50) no vi ese servicio, y el proyecto no puede crear roles. Es **probable que FIS no sea utilizable**; no está comprobado.

## 3. Plan propuesto (NO ejecutar sin autorización explícita)
1. **Objetivo/hipótesis:** con V2 en 2 zonas, retirar el tráfico de una zona (p. ej. quitar la subred de una zona del ASG y detener sus destinos) mantiene el servicio con ≥ 1 destino sano; el ASG relanza en la otra zona.
2. **Recursos afectados:** redesplegar V2 (ALB, ASG 2–3 EC2, TG, políticas), RDS activa; la prueba toca solo las EC2/subred de una zona. Sin tocar la RDS.
3. **Riesgo:** interrupción breve de la API durante la detección (≈ 20–60 s); sin riesgo de pérdida de datos (no se tocan escrituras ni la RDS); riesgo de dejar recursos encendidos.
4. **Coste máximo estimado (tarifas públicas, no verificado):** ≈ 0,15 USD/h para V2 + RDS Multi-AZ; 3 h → ≈ 0,5 USD. FIS (si estuviera permitido): ≈ 0,10 USD por minuto de acción.
5. **Tiempo máximo:** 3 h (redespliegue ≈ 25 min, prueba ≈ 15 min, destrucción ≈ 10 min); con apagado verificado al final.
6. **Reversión:** `terraform destroy` del plan V2 y `stop-db-instance`; verificación de EC2/ALB/ASG = 0 y RDS `stopped`.
7. **Evidencia que se obtendría:** `HealthyHostCount`/5xx de CloudWatch y registros con hora de cada paso; capturas de ALB/ASG **vivos**.
8. **Alternativa de menor riesgo (recomendada):** no ejecutar; documentar E y F como diseño y límite, y presentar A–D como lo medido.
9. **Requisito que lo justifica:** criterio 4 (tolerancia a fallos): solo mejora la cobertura de «pérdida de zona». No es necesario para alcanzar 4/4 si E y F se declaran sin probar.
