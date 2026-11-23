# Plan P1 — Cadena CloudWatch → SNS → correo (PREPARADO, NO EJECUTADO)

Preparado el 4-nov-2026. **EJECUTADO y COMPLETADO el 4-nov-2026**: resultado en `docs/evidencias/20261104-p1-notificacion/resultado.md`. El texto siguiente es el plan original.

## Qué demuestra y qué no
`aws cloudwatch set-alarm-state` **simula una transición de estado**: CloudWatch registra el cambio y ejecuta las acciones de la alarma. Demuestra que la cadena **alarma → acción SNS → tema → suscripción → correo** funciona. **NO demuestra** que la alarma detecte una sobrecarga real de CPU: la métrica no cambia y el motivo queda registrado como «cambio manual». En el informe debe llamarse **«notificación probada con estado forzado»**, no «alarma de CPU validada». La detección real queda para P2 (carga de CPU), si se autoriza.

## Comprobaciones previas (solo lectura, 4-nov-2026)
| Comprobación | Resultado |
|---|---|
| Sesión AWS CLI, perfil `nexoeventos-lab` | válida (cuenta y rol enmascarados) |
| `ec2-cpu-high` | estado `OK`, acciones habilitadas |
| `alarm_actions` / `ok_actions` | ambas = el tema `nexoeventos-academy-alarmas`; `insufficient_data_actions` vacías |
| Suscripción | 1 de protocolo `email`, ARN real (no `PendingConfirmation`); confirmadas 1, pendientes 0, eliminadas 0 |
| Permisos para `cloudwatch:SetAlarmState` | `allowed` según `iam:SimulatePrincipalPolicy` (**indicativo**: no ve SCP de Academy; solo la ejecución real lo confirma) |
| EC2 / RDS | `running` / `stopped` (sin cambios) |
| Historial de la alarma | transiciones recientes por `INSUFFICIENT_DATA`↔`OK`; la última a `OK` fue anterior a esta preparación |

## Comportamiento esperado
1. `set-alarm-state … ALARM` → la alarma pasa a `ALARM` y se publica en SNS **1 correo** («ALARM»).
2. En la siguiente evaluación (CloudWatch evalúa cada ≈ 1 min; la métrica real está por debajo de 80 %), la alarma **vuelve sola a `OK`** → **1 segundo correo** («OK», por `ok_actions`). Lo normal es 1–6 min.
3. Total esperado: **2 correos**. Un tercero indicaría otra transición (p. ej. `INSUFFICIENT_DATA`, que no tiene acción).

## Criterios de éxito (todos)
- `set-alarm-state` termina sin error (si da `AccessDenied`, la prueba se detiene: no hay alternativa autorizada).
- El historial muestra `StateUpdate` a `ALARM` (motivo manual) **y** un ítem `Action` «Successfully executed action» hacia el tema SNS; sin ítems `Failed to execute action`.
- La propietaria **recibe el correo de ALARM** (revisar spam) y confirma la hora de llegada.
- La alarma vuelve a `OK` (sola o por recuperación) y llega el **correo de OK**.
- Estado final = `OK`, acciones habilitadas, EC2 `running`, RDS `stopped`.

## Evidencias
1. Salidas saneadas (`scripts/cloud/mask.sh`) de: estado antes, `set-alarm-state` (sin salida), historial de estado y de acciones, estado después. Guardar en `docs/evidencias/<fecha>-p1-notificacion/`.
2. Captura de ambos correos **por la propietaria**, ocultando su dirección, el ID de cuenta y los enlaces de baja/«unsubscribe» (contienen tokens). Pegar solo la hora y el asunto en el informe.
3. Métrica opcional de SNS (`NumberOfNotificationsDelivered` del tema) como corroboración.
4. En el informe: «estado forzado; no evidencia de carga real».

## Comandos exactos (NO ejecutados)
Variables y estado inicial:
```bash
export AWS_PROFILE=nexoeventos-lab AWS_DEFAULT_REGION=us-east-1
A=nexoeventos-academy-ec2-cpu-high
T0=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "T0=$T0"
aws cloudwatch describe-alarms --alarm-names $A --query 'MetricAlarms[0].[StateValue,ActionsEnabled]' --output text   # esperado: OK True
```
Transición forzada (único cambio de estado de la prueba):
```bash
aws cloudwatch set-alarm-state --alarm-name $A --state-value ALARM \
  --state-reason "Prueba P1 controlada: transicion forzada manualmente; no es carga real de CPU"
```
Seguimiento hasta volver a `OK` (máx. 10 min; solo lectura):
```bash
for i in $(seq 1 20); do s=$(aws cloudwatch describe-alarms --alarm-names $A --query 'MetricAlarms[0].StateValue' --output text); echo "$(date -u +%H:%M:%SZ) $s"; [ "$s" = OK ] && [ $i -gt 1 ] && break; sleep 30; done
```
Evidencia (solo lectura):
```bash
aws cloudwatch describe-alarm-history --alarm-name $A --start-date $T0 --history-item-type StateUpdate --query 'AlarmHistoryItems[].[Timestamp,HistorySummary]' --output text
aws cloudwatch describe-alarm-history --alarm-name $A --start-date $T0 --history-item-type Action --query 'AlarmHistoryItems[].[Timestamp,HistorySummary]' --output text | sed -E 's/[0-9]{12}/<cuenta>/g'
```
Recuperación **solo si pasados 10 min no volvió a `OK`** (envía un correo de OK adicional; se documenta como recuperación manual):
```bash
aws cloudwatch set-alarm-state --alarm-name $A --state-value OK --state-reason "Recuperacion P1: retorno manual al estado normal"
```
Verificación final:
```bash
aws cloudwatch describe-alarms --alarm-names $A --query 'MetricAlarms[0].[StateValue,ActionsEnabled,length(AlarmActions),length(OKActions)]' --output text   # OK True 1 1
aws ec2 describe-instances --filters Name=tag:Name,Values=nexoeventos-academy-app --query 'Reservations[].Instances[].State.Name' --output text   # running
aws rds describe-db-instances --db-instance-identifier nexoeventos-academy-postgres --query 'DBInstances[0].DBInstanceStatus' --output text          # stopped
```

## Recuperación y parada
- **No vuelve a `OK` en 10 min:** ejecutar el comando de recuperación manual. Si tras él sigue sin `OK`, revisar `ActionsEnabled`, `StateReason` y que EC2 siga `running` (si estuviera detenida pasaría a `INSUFFICIENT_DATA`; sin acción asociada y sin efectos). No se toca nada más sin consultar.
- **`AccessDenied`:** detener y documentar «`SetAlarmState` denegado por Academy»; no se usan alternativas (p. ej. publicar en SNS) sin nueva autorización.
- **No llega el correo y el historial muestra la acción exitosa:** revisar spam y esperar 5 min; no reintentar el envío ni suscribir otra dirección sin consultar.
- **Falla la acción en el historial:** detener, no repetir; revisar la política del tema.

## Riesgos
- **Evidencia mal etiquetada** (mayor riesgo): presentar P1 como detección real. Mitigación: texto fijo de este plan.
- **Efectos:** la alarma de V1 solo tiene acciones SNS (sin autoscaling ni reinicios), así que forzar `ALARM` no cambia infraestructura. Coste ≈ 0 (2 correos; dentro de la capa gratuita de SNS).
- **Privacidad:** el correo recibido contiene ID de cuenta, nombre de alarma, región y un enlace de baja con token; sanear antes de archivar.
- **Lo forzado se confunde con real:** el historial queda con un `ALARM` manual; se explica en la matriz.
- **Permisos de Academy** no verificables en seco (la simulación IAM no ve SCP).
- **Sesión de Academy caducada** a mitad: reanudar solo tras revisar el estado de la alarma.
