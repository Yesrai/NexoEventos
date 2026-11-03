# Matriz de alarmas, monitoreo y experimentos (documento de trabajo) — 3-nov-2026

Cada elemento se clasifica en cinco niveles independientes: **C** definido en código · **D** desplegado realmente · **E** con evidencia de funcionamiento · **R** probado con una alarma o evento real · **P** pendiente. «Definido en Terraform» **no** implica desplegado ni funcionando. Las cifras de los experimentos se recalculan con `scripts/cloud/validate-chaos-result.py` (solo lee `docs/evidencias/`) y las comprueba `backend/tests/test_chaos_evidence.py`.

## 1. Alarmas y monitoreo de AWS
| Elemento | C | D | E | R | Estado real y pendiente |
|---|---|---|---|---|---|
| Alarma `ec2_cpu_high` (V1; CPU > 80 % durante 2 × 300 s) | sí (`infra/aws/storage_observability.tf`) | sí (EV08, 10-oct: estado `OK`) | sí (lectura por API) | **no: nunca ha saltado** | **Sin acciones**: nadie recibe aviso (EV08: 0 `AlarmActions`). Ahora el código admite acciones SNS (`enable_alarms` + `alarm_email`, desactivado) |
| Alarmas internas de escalado (política de CPU objetivo 40 %: `AlarmHigh`/`AlarmLow`) | sí (`infra/aws-v2/compute.tf`) | sí, **V2 ya destruida** | sí (`escalado-v2-20261022/`) | **sí**: `AlarmHigh` a las 17:04:59 UTC (8 min 6 s tras la carga), `AlarmLow` a las 17:22:07 | Solo histórico; no se puede re-capturar |
| Política por solicitudes por destino (`ALBRequestCountPerTarget`) | sí (condicional, `scale_requests_per_target`) | no consta | no | no | No hay evidencia de que se activara |
| Métricas del ALB y del Target Group (`HealthyHostCount`, `UnHealthyHostCount`, 5xx, latencia) | sí (panel `v2-medicion`, `observability.tf`) | sí (histórico) | sí: series originales y capturas 07, 08, 09 | sí (picos de 5xx y caídas a 1 destino sano en las dos pruebas de fallo) | Son **métricas**, no alarmas |
| Alarmas de 5xx, destinos no sanos / bajos y latencia p95 de V2 | **sí, nuevo y opcional** (`infra/aws-v2/alarms.tf`, `enable_alarms = false`) | **no** | no | no | **Antes no existía ninguna.** Validación solo estática; coste ≈ 0,10 USD/alarma/mes |
| Estado de salud de las EC2 (status checks) | — | — | sí: captura A1 («3/3 comprobaciones») | no | Sin alarma de status check |
| CloudWatch Logs (`/nexoeventos/<env>/api` y `/nginx`, 7 días) | sí | sí | **sí**: EV08 (recepción real, 1 coincidencia de una petición ficticia, sin secretos) | sí (ingesta real) | Sin filtros de métricas ni alarmas sobre los logs |
| Reemplazo de instancias por el ASG | sí (`health_check_type = ELB`) | sí (histórico) | sí (`tolerancia-fallos-v2-20261022-b/`: causa «fallo del health check de ELB») | **sí** (22-oct ≈ 16:38) | **Sin notificación** de reemplazo (no hay notificaciones del ASG) |
| `FreeStorageSpace` de la RDS | alarma **nueva y opcional** (`infra/aws/alarms.tf`, umbral 2 GiB) | **no** | **no: la métrica no está en las 40 series exportadas** | no | **Pendiente**: lectura de solo lectura de la ventana del 28-oct. El aviso «20 GiB / umbral 20 GiB» (A16) es de **configuración**, no una medición |
| CPU y conexiones de la RDS | sí (panel V2; alarma de CPU nueva y opcional) | histórico | sí (`DatabaseConnections` y CPU exportados) | no | Sin alarma desplegada |
| Eventos de la RDS (failover, inicio, detención) | — | — | sí (capturas 10, 11 y A16) | sí | Sin suscripción de eventos a SNS |
| CloudTrail | opcional (`enable_cloudtrail = false`) | **no hay trail** (A9) | historial de 90 días (A8) | — | Pendiente de decisión y de permisos de Academy |

## 2. Azure
| Elemento | C | D | E | R | Estado real y pendiente |
|---|---|---|---|---|---|
| `alerta-vm-cpu` (CPU > 80 % durante 15 min, gravedad 2, evaluación cada 5 min) | sí (`infra/azure/modules/monitor/main.tf`) | sí (captura B3) | sí (B3, B8, B9, `azure-alerta-cpu-disparada.json`) | **sí**: activada 28-oct 14:41:12 UTC con 94,9 % y resuelta 15:02:59 UTC | El grupo de acciones aparece **desencadenado** a las 9:41 y 10:02 (UTC−5, B9) |
| **Correo de esa alerta** | sí (grupo `ag-nexoeventos-obs`, 1 receptor) | sí (B4: «Verificado») | **no** | **no demostrado** | El receptor **se verificó a las 15:23 UTC, después** de la alerta (14:41) y de su resolución (15:02): con el correo sin verificar no cabía esperar entrega. Es una explicación coherente con las fechas, **no una prueba**. La prueba manual de notificación dio `409 Free subscription not supported` |
| `alerta-vm-mem` (memoria disponible < 400 MiB) | sí | sí (captura B1: listado de recursos) | no | no (nunca saltó) | — |
| `alerta-vm-up` (disponibilidad < 1 durante 5 min, gravedad 1) | sí | sí | no | no | Riesgo **no verificado**: podría dispararse al desasignar la VM a propósito |
| Registro de actividad y Log Analytics | sí | el espacio de trabajo existe (captura B1); la configuración de diagnóstico no se verificó | no | — | Sin evidencia de recepción de datos en esta auditoría |
| Presupuesto con alertas 50/80/100 % | sí | no hay evidencia propia | no | no | Solo avisa; no detiene gasto |
| Zabbix (triggers) | sí (plantillas exportadas) | sí (VM de la ventana del 28-oct) | sí (`zabbix-umbrales-triggers.txt`) | **sí**: «NexoEventos no disponible» (High) por la caída de AWS V1 a las 14:23:31 UTC y «CPU alta» a las 14:29:41 UTC | Las 5 alertas de la caída de V1 **fallaron** al inicio («No message defined for media type»); la entrega se demostró después con el problema y las recuperaciones de CPU, **solo en un registro local** (no hubo correo desde Zabbix) |
| Grafana (13.2.4) | sí | sí | sí (`grafana.txt`: orígenes Azure Monitor y Zabbix) | consultas reales a Azure Monitor | **Sin capturas de los paneles** |
| VM de monitoreo | — | **desasignada** (IP estática y disco siguen costando) | — | — | No encender sin autorización |

## 3. OCI
| Elemento | C | D | E | R | Estado real |
|---|---|---|---|---|---|
| Logs, métricas, alarmas y notificaciones de OCI | **no definidos** en `infra/oci` | no | no | no | **No existe monitoreo nativo de OCI**; es una limitación, no un fallo |
| Eventos de objetos del bucket | — | «Emit object events: Disabled» (OCI-02) | sí | — | Desactivado |
| Registro de auditoría de OCI | — | activo por defecto según la documentación de Oracle | **sin captura** | — | No verificado |
| Supervisión de la recuperación | script `oci-drill` | sí | **sí**: `tiempos-orquestador.txt`, `tiempos-aprovisionamiento.txt`, `smoke.json` | sí (23-oct) | Medición propia del orquestador, no un servicio de monitoreo |
| Validación de integridad | script | sí | **sí**: huella de 10 valores idéntica a la línea base; solo cambia `access_logs` 9 → 10 | sí | — |
| Disponibilidad durante la recuperación | — | — | `/healthz` y 14 pruebas de humo | sí | Sin monitoreo posterior: la VM se destruyó |
| Métricas de OCI en Zabbix | — | — | 734 puntos históricos importados (etiquetados como históricos) | — | No son métricas en vivo de OCI |

## 4. Experimentos de Chaos Engineering: resultado verificado contra los datos crudos
| Exp. | Qué se provocó | Cifras recalculadas | Estado | Límite |
|---|---|---|---|---|
| **A** Caída de la API (22-oct ≈ 16:03 UTC) | Parar la API de 1 de 2 instancias ≈ 40 s | 275 solicitudes, 25 × 502 (**todas `/healthz`**); detección **20,0 s**; recuperación **15,8 s** | **Completo** | El 90,9 % **no** es disponibilidad de la API: el ALB envió todo `/api/events` a la instancia sana |
| **B** Autohealing del ASG (22-oct ≈ 16:38 UTC) | Mismo fallo ≈ 50 s | Reemplazo ≈ 2,5 min; **40** × 5xx del destino y 0 del ELB (solo datos agregados) | **Incompleto** | `resultado.json` **no existe**: el script falló con `InvalidInstanceId`. Corregido después (`resultado-parcial.json`, consulta tolerante); **el experimento no se repitió** |
| **C** Escalado | 8 inicios de sesión/s | Alarma a **8 min 6 s**; 2 → 3 → 2; 4.202 inicios sin errores | **Completo con límite** | Carga cortada ≈ 55 s después de la 3.ª instancia sana; sin reparto entre 3 |
| **D** Failover de RDS (23-oct 01:08 UTC = 22-oct 20:08 Lima) | `reboot --force-failover` | PostgreSQL **14,1 s**; `/healthz` **13,1 s** (225 muestras); datos idénticos | **Completo** | **Sobre V1**, no V2; 2 timeouts aislados posteriores sin explicar |
| **E** Recuperación en OCI (23-oct) | Simulacro manual | 14/14 pruebas; huella de **10** valores; **32 min 42 s** desde el `apply` | **Completo con límite** | **Incluye 1 fallo y 4 reanudaciones registradas** (no es una ejecución limpia); manual, no failover automático |
| **F** Restauración de datos en AWS (R01, 10-oct) | PITR a una RDS temporal, verificación y eliminación | RPO 3 min 32 s; datos verificados a los 21 min 4 s; 135/135 QR | **Ejecutado (informe textual)** | No se conmutó la aplicación; no es la restauración completa del servicio; sin datos crudos en el repositorio |

## 5. Experimentos pendientes y su clasificación
| Experimento | Clasificación | Motivo |
|---|---|---|
| V2 durante una caída de PostgreSQL / failover con V2 (valida `/livez` y la guardia `ami_includes_livez`) | **Recomendable** si hay créditos | Cierra el riesgo de que el ASG reemplace instancias sanas; V1 ya demostró el failover. ≈ 0,5 USD y requiere redesplegar V2, la RDS y la AMI |
| Reemplazo de instancias con la AMI nueva | **Obligatorio solo si se afirma que el health check corregido está desplegado** | Si no, se declara «corregido en código y probado en local» |
| Repetir el autohealing con el script corregido | **Recomendable** | Convierte la B en «Completo»; mismo coste |
| Caída de una zona de disponibilidad | **Opcional** | El diseño usa 2 zonas; no es necesario para el criterio si se declara sin probar |
| AWS FIS | **Inviable o demasiado riesgoso en Academy** | Exige un rol de servicio de FIS que `LabRole` probablemente no permite |
| Restauración completa de AWS (servicio, no solo datos) | **Recomendable** | R01 solo restauró datos; con la recuperación en OCI ya hay un simulacro completo en otra nube |
| Prueba de notificaciones (correo de Azure) | **Recomendable, la de más valor por coste** | Cerraría el único punto de monitoreo «no demostrado»; una ventana de ≈ 1 h (≈ 0,11 USD/h) con el correo ya verificado |

## 6. Problemas encontrados y corregidos localmente en esta ronda
1. V2 no tenía **ninguna alarma de disponibilidad** (solo las del escalado) y la RDS ninguna de espacio libre: `infra/aws-v2/alarms.tf` e `infra/aws/alarms.tf` (opcionales, desactivadas por defecto, sin coste mientras estén desactivadas).
2. La alarma de CPU de V1 **no avisaba a nadie**: ahora admite acciones SNS (vacías por defecto, sin cambio de estado).
3. Las cifras de los experimentos **no se podían reproducir**: `scripts/cloud/validate-chaos-result.py` y 5 pruebas.
4. Las comprobaciones estáticas de IaC cubren las alarmas (44 comprobaciones).
Ninguna de estas correcciones está desplegada ni validada en AWS.

## 7. Especificación de cada alarma preparada (código local, **no desplegadas**; `enable_alarms = false` por defecto)
Comprobaciones de cada una: (1) métrica y espacio de nombres, (2) dimensiones, (3) umbral justificado, (4) periodo y evaluaciones, (5) datos ausentes, (6) acción, (7) compatibilidad con Academy, (8) coste, (9) prueba, (10) evidencia. Coste general: ≈ 0,10 USD por alarma y mes (capa gratuita: 10 alarmas), SNS por correo gratuito, eventos de RDS y avisos del ASG gratuitos. **Compatibilidad con Academy: no verificada** (depende de que `LabRole` permita `cloudwatch:PutMetricAlarm`, `sns:CreateTopic/Subscribe/SetTopicAttributes`, `rds:AddSourceIdentifierToSubscription` y `autoscaling:PutNotificationConfiguration`); se comprueba con el primer `plan`/`apply` dirigido.
| Alarma (archivo) | Métrica y dimensión | Umbral y evaluación | Datos ausentes | Cómo se probaría | Evidencia de activación y recuperación |
|---|---|---|---|---|---|
| `ec2_cpu_high` (V1, existente; ahora con acciones) | `AWS/EC2` `CPUUtilization`, `InstanceId` | > 80 % en 2 × 300 s (la de EV08) | `missing` | Carga de CPU controlada en la EC2 (≈ 15 min) | Historial de la alarma + correo confirmado por la propietaria |
| `ec2_status_check_failed` (V1) | `AWS/EC2` `StatusCheckFailed`, `InstanceId` | ≥ 1 en 3 × 60 s | `notBreaching` (EC2 detenida no salta) | No se provoca (requiere fallo de hardware/SO); solo `set-alarm-state` para la cadena de notificación | Historial; marcado como **estado forzado** |
| `rds_free_storage_low` (V1) | `AWS/RDS` `FreeStorageSpace` (Minimum), `DBInstanceIdentifier` | < 2 GiB (10 % de 20 GiB; configurable, mínimo 512 MiB) en 2 × 300 s | `missing` (RDS detenida) | No se agota el disco; `set-alarm-state` forzado | **No habrá activación real**; sí la **lectura histórica** de la métrica |
| `rds_cpu_high` (V1) | `AWS/RDS` `CPUUtilization`, `DBInstanceIdentifier` | > 80 % media en 3 × 300 s | `missing` | Carga de lectura controlada (opcional) | Historial |
| `aws_db_event_subscription` (V1) | Eventos de RDS: failover, failure, low storage, notification, availability | — | — | Un failover real (experimento D2 con V2/RDS) o el evento de inicio/parada | Correo del evento (el aviso de 20 GiB es de la categoría `low storage`) |
| `alb_target_5xx` (V2) | `AWS/ApplicationELB` `HTTPCode_Target_5XX_Count` (Sum), `LoadBalancer` | ≥ 5 por minuto en 2 de 3 minutos | `notBreaching` | **Se activa sola** en la caída de API (25 y 40 respuestas 5xx por minuto observadas el 22-oct) | Historial + captura |
| `alb_unhealthy_hosts` (V2) | `UnHealthyHostCount` (Maximum), `LoadBalancer`+`TargetGroup` | ≥ 1 durante 3 minutos | `notBreaching` | Caída de API de ≥ 3 min (los 40 s del exp. A **no** bastarían) | Historial |
| `alb_healthy_below_desired` (V2) | `IF(HealthyHostCount < GroupDesiredCapacity)` (expresión entre `AWS/ApplicationELB` y `AWS/AutoScaling`) | = 1 durante 3 minutos | `notBreaching`: **no salta con el grupo en 0 a propósito** | Autohealing (≈ 2,5 min de reemplazo: cerca del límite; puede no saltar) | Historial |
| `asg_in_service_below_desired` (V2) | `IF(GroupInServiceInstances < GroupDesiredCapacity)` | = 1 durante 5 minutos (un reemplazo normal ≈ 2,5 min no salta) | `notBreaching` | Fallo de lanzamiento del ASG (no provocado) | Historial |
| `alb_latency_p95` (V2) | `TargetResponseTime` p95, `LoadBalancer` | > 1,5 s en 3 de 5 minutos (medido p95 ≤ 0,395 s) | `notBreaching` | Carga alta (no se hará sin autorización) | Historial |
| `aws_autoscaling_notification` (V2) | Lanzamiento/terminación y errores del ASG | — | — | Autohealing o escalado | Correo con el aviso |
Procedimiento común de **prueba de la cadena de notificación** (gratuito, sin infraestructura nueva): `aws cloudwatch set-alarm-state --state-value ALARM --state-reason "prueba"` sobre una alarma; es un estado **forzado**: demuestra que SNS entrega el correo (que la propietaria confirma al verlo), **no** que la métrica funcione. Se registra así. No se afirma entrega mientras no se confirme el correo recibido.
