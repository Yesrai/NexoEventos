# T5 — 2.º intento (variante C, 23-nov-2026, 01:34–01:53 UTC): **ABORTADO sin medición — la SCP de Academy deniega el ASG de 6 instancias**
**No es un PASS ni un resultado de los criterios:** la prueba oficial **no llegó a ejecutarse** (no hubo tráfico, ni fallo inyectado, ni compilación de evidencia). Criterios sin cambios; expediente FAIL del 1.er intento íntegro.

## Qué ocurrió (UTC)
| Hora | Hecho |
|---|---|
| 01:34 | puertas de solo lectura 8/8 y `rds-window.sh check` OK; sesión viva; estado `PARADA_VERIFICADA` |
| 01:38 | Azure encendida (NTP sincronizado, apagado → 04:34), unidad de sonda rápida instalada sin habilitar |
| 01:38–01:41 | `rds-window.sh chain --scenario t5c` (NEXO_EXPECTED_TARGETS=6): watchdog armado, RDS disponible 01:41:51 |
| 01:42:00 | plan regenerado y **ACEPTADO por el revisor `t5c`** (3 crear, 8 modificar, 0 destruir) |
| 01:42–01:44 | `terraform apply` del plan guardado: ALB (2 m 23 s), listeners, alarmas, **plantilla de lanzamiento y grupo de destino actualizados** |
| **01:44:28** | **`UpdateAutoScalingGroup` → 403 «explicit deny in a service control policy»** (`p-bsgibq7u`): el ASG no pasó a mín 6 / deseada 6 / máx 7 |
| 01:45 | estado real parcial: ALB activo; **ASG 0/0/3 y 0 instancias**; TG con 5 s/3 s, `weighted_random` y mitigación `on`; plantilla versión 2 (pool 3+2); RDS disponible |
| 01:45–01:52 | limpieza segura (decisión tuya: prioridad a la limpieza): ASG 0, ALB eliminado, **RDS `stopped` verificada (342 s)**; watchdog cancelado |
| 01:53 | Azure desasignada y apagado restaurado **exactamente** |

## Qué se sabe y qué NO
- **Se sabe:** una SCP (política de la organización de Academy, no del usuario) **deniega explícitamente** esta llamada de `UpdateAutoScalingGroup`. La misma API **sí** funcionó con mín 2 / deseada 2 / máx 3 (intento 1, 00:21Z) y 2→3→2 (4-nov): la denegación **depende de los parámetros**, no de la acción.
- **NO se sabe qué parámetro (o combinación) la dispara** (¿máx 7?, ¿mín/deseada 6?, ¿suma de vCPU?): la SCP no es legible con este rol, no hay documentación pública de ese límite y **no lo he probado** con llamadas manuales porque excederían el `apply` del plan revisado que autorizaste. **No presento ninguna cifra de «límite de Academy» como hecha.**

## Estado real resultante (para evitar confusiones)
AWS: **ASG 0/0/3**, 0 EC2, **sin ALB**, **RDS `stopped`**, V1 `stopped`. **Quedan aplicados en AWS (y en el estado de Terraform):** el grupo de destino con health check 5 s/3 s, `weighted_random` y mitigación de anomalías `on`, y la **versión 2 de la plantilla de lanzamiento (pool de BD 3+2)**. Son benignos con 0 instancias y con N = 2 (pool 3+2 = 2×2×5 = 20 conexiones); `terraform plan` con los valores por defecto/«on» da hoy 3 a crear, 8 a modificar, 0 a destruir (revierte el TG y la plantilla si se aplicara tal cual), y con la variante C 3 crear + 6 modificar (el revisor `t5c` lo bloquea a propósito: ya no coincide con el plan original). **Se debe decidir** si mantenerlos (variante C futura) o revertirlos por plan revisado.
Coste del intento ≈ USD 0,1 de AWS (RDS ≈ 11 min + ALB ≈ 8 min) + Azure ≈ 0,2.

## Opciones (requieren tu decisión; no se ejecutó nada más)
1. **Diagnóstico mínimo y sin costo de la SCP** (autorización específica): `update-auto-scaling-group --max-size 7` **solo** (no lanza instancias; reversible a 3) para saber si el máximo es el problema. Si se permite, queda por probar mín/deseada 6 (solo dentro de una ventana, porque lanza instancias). Si se deniega, se prueban máx 6, 5, 4 (sin costo).
2. **Variante a otro N que Academy permita** (4 ó 5), una vez conocido el límite: P(≤4 fallos) ≈ 27 % (N=4) según el modelo, sin ATW.
3. **Cerrar T5 como FAIL documentado**: detección y recuperación cumplen; la disponibilidad (95,21 %) no, por el límite del mecanismo; la variante C **no es viable en Academy** si el límite se confirma.
4. **Variante B** (3 instancias, sabido que Academy lo permite): solo experimento de ATW, P ≈ 9–30 %.
