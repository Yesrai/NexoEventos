# Evidencia de CloudWatch que pierde resolución — decisión y procedimiento

**Fecha del análisis:** 28-oct-2026. **Regla de CloudWatch:** las métricas de 1 minuto se conservan 15 días, las de 5 minutos 63 días y las de 1 hora 455 días; después de cada plazo solo queda la resolución siguiente.

## 1. ¿Ya existe una copia local suficiente?
| Ventana | Qué contiene | Copia local existente | Suficiente para el informe | Falta |
|---|---|---|---|---|
| 9-oct (E01, V1) | CPU/BD de la carga de 20 usuarios | Resumen en [`EV11`](../evidencias/EV11/resultado-2026-10-09.md) | Sí (cifras de la tabla) | La serie de 1 min **ya se perdió** (> 15 días); solo quedan 5 min hasta ≈ 11-dic |
| 19-oct (V1 con carga) | CPU, memoria, conexiones por peldaño | Resúmenes por peldaño en `perf/results/aws-v1-aws2/` y `aws-v1-aws3/` (`baseline.json`, `nivel-*.json`) | Sí para las tablas de [`medicion-v2`](../evidencias/medicion-v2-20261022/resultado.md) | Series de 1 min para gráficos: **vencen ≈ 3-nov** |
| 22-oct (V2, escalado y fallos) | Alarmas, instancias sanas, ALB, RDS | Línea de tiempo en `perf/results/aws-v2-scale-sc1/escalado.json`, [`cloudwatch-alb.json`](../evidencias/tolerancia-fallos-v2-20261022-b/cloudwatch-alb.json) y resúmenes en `aws-v2-v2b/` | Sí para los hitos y tablas | Series de 1 min completas: **vencen ≈ 6-nov** |
| 23-oct (RDS Multi-AZ, failover) | Eventos y sondas de 1–2 s | [`failover/`](../evidencias/multicloud/aws/20261023-rds-multiaz/failover/resultado.json) (`healthz-1s.json`, `rds-2s.json`) y eventos RDS | Sí (la medición propia es de 1 s) | Métricas de RDS de 1 min: **vencen ≈ 7-nov** |

**Conclusión:** las cifras citadas en el informe están respaldadas por copias locales de resumen; **no** existe copia de las series de 1 minuto. Para tener gráficos y poder reanalizar, hay que exportarlas **antes del 3-nov-2026** (la más urgente es la de V1 del 19-oct, que es la línea base de la comparación V1 vs V2).

## 2. Procedimiento listo (solo lectura; requiere autorización porque necesita sesión activa del laboratorio)
Condiciones: no enciende ni modifica recursos; solo necesita el laboratorio activo (credenciales temporales) y permisos `cloudwatch:ListMetrics/GetMetricData`. Costo: 0 (las consultas `GetMetricData` por millar de métricas cuestan fracciones de centavo). Riesgo: iniciar el laboratorio puede **reiniciar solas la EC2 y la RDS** (ocurrió el 23-oct); hay que comprobar su estado al empezar y detenerlas si arrancaron.
```bash
# 0. (autorizado por la propietaria) iniciar el laboratorio y renovar credenciales; comprobar y, si hace falta, detener EC2/RDS
./scripts/cloud/cloud-session.sh status
# 1. Verificación local previa, sin AWS (ya pasa)
python3 scripts/observability/export-cloudwatch.py --selftest
# 2. Exportación de solo lectura de las tres ventanas por defecto (V1 19-oct, V2 22-oct, RDS 23-oct)
python3 scripts/observability/export-cloudwatch.py --profile nexoeventos-lab --out work/observability/aws-cloudwatch.json
# 3. Copia sanitizada a evidencias y, opcionalmente, carga en Zabbix (Azure) con push-history.py
```
Salida: `work/observability/aws-cloudwatch.json` (ignorado por Git, sin identificadores de cuenta) con puntos de CPU/red de EC2, CPU y conexiones de RDS, solicitudes/5xx/latencia del ALB y capacidad del ASG. Las series inexistentes se omiten y se informan.

## 3. Lo que NO se ha hecho
No se ha consultado AWS en esta sesión; el laboratorio está inactivo. Nada de lo anterior se ha ejecutado contra CloudWatch.
