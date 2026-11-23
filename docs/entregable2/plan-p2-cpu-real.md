# Plan P2 — Detección real de CPU elevada en AWS V1 (EJECUTADO el 4-nov-2026; ver `docs/evidencias/20261104-p2-cpu-real/resultado.md`)

> Nota posterior: la alarma se activó a los ≈ 6,6 min (no 11–15 min como estimaba la sección 5) porque CloudWatch evaluó un datapoint parcial del periodo en curso. Texto original abajo.

Preparado el 4-nov-2026 con lecturas únicamente. **No se ha generado carga, ni ejecutado ningún comando SSM, ni modificado ningún recurso.** No hay resultados de P2 en este documento; solo diseño.

## 1. Qué demuestra
Que la alarma `nexoeventos-academy-ec2-cpu-high` **detecta una CPU alta real** (métrica medida por CloudWatch, no estado forzado) y que la cadena completa CloudWatch → SNS → correo funciona con una transición causada por la métrica. Complementa P1 (notificación con estado forzado). Es carga sintética: no equivale a tráfico real de usuarios.

## 2. Verificaciones de solo lectura (4-nov-2026 ≈ 00:55 hora de Perú)
| Elemento | Resultado |
|---|---|
| Sesión AWS | válida (perfil `nexoeventos-lab`) |
| EC2 `nexoeventos-academy-app` | `running`, `t3.small` (2 vCPU, 2 GiB), **monitoreo básico (métricas cada 5 min)**, perfil de instancia del laboratorio; último arranque 23:45 (Perú) del 3-nov |
| **Créditos de CPU** | modo **`unlimited`**; saldo `CPUCreditBalance` = **576** (máximo) estable; `CPUSurplusCreditBalance` = 0 |
| RDS | `stopped` (db.t3.micro) |
| SSM | instancia **`Online`** (Amazon Linux 2023, agente 3.3); documento `AWS-RunShellScript` activo; ya se usó con éxito el 23-oct |
| Permisos SSM | `SendCommand`, `GetCommandInvocation`, `CancelCommand`, `ListCommandInvocations`: `allowed` según IAM Simulate (**indicativo**; Academy puede denegar al ejecutar) |
| ALB / ASG en la cuenta | 0 / 0 (V1 sin autoscaling: la carga no puede disparar escalados ni reemplazos) |
| CPU real previa | ≈ 0,8 %–0,9 % promedio (máx. ≈ 1,4 %) en las últimas 3 h |
| Crédito del laboratorio | **NO verificable por API**. Solo se ve en la consola de Academy; no se usa Cost Explorer sin pedirlo. El saldo comunicado antes (40,50 USD) **no se da por vigente** |

### Configuración real de la alarma
Métrica `AWS/EC2` `CPUUtilization`, dimensión `InstanceId`; estadístico **Promedio**; **periodo 300 s**; **2 evaluaciones** (`DatapointsToAlarm` no definido, por lo que equivale a 2 de 2); umbral **> 80**; datos faltantes **`missing`**; acciones habilitadas; `alarm_actions` y `ok_actions` = tema SNS `nexoeventos-academy-alarmas` (1 y 1); sin acción para datos insuficientes.

## 3. Viabilidad de la carga por SSM
**Viable sin abrir puertos ni instalar software**, a falta de una comprobación previa en la propia instancia:
- Se usa `AWS-RunShellScript` por el canal SSM existente (no se abre ningún puerto).
- La carga usa `yes > /dev/null` (coreutils, ya en Amazon Linux 2023) y `systemd-run` (systemd, ya presente): sin `stress-ng`, sin `dnf install`, sin descargas.
- **Pendiente de confirmar** (paso 0, un comando SSM de solo lectura, que **también necesita tu autorización** porque es ejecución remota): que existan `systemd-run`, `yes` y `nice`, que haya 2 CPU y que la unidad `nexo-p2-cpu` no exista ya.
- Es necesario cargar **las 2 vCPU**: con una sola el promedio de la instancia sería ≈ 50 % y nunca superaría 80 %.

## 4. Diseño de la carga (limitada, reversible, con parada)
- Dos procesos `yes > /dev/null` (1 por vCPU), dentro de **una unidad transitoria de systemd** `nexo-p2-cpu`:
  - **`RuntimeMaxSec=1500`** → **parada automática a los 25 min** pase lo que pase (independiente de SSM, de tu sesión y de mí).
  - `Nice=19` → la aplicación, nginx y el agente SSM tienen prioridad sobre la carga; el servicio sigue respondiendo, solo con menos CPU sobrante.
  - `MemoryMax=64M` → no puede agotar memoria.
  - Salida a `/dev/null`: sin disco, sin red, sin logs, sin tocar datos, base de datos ni configuración. La unidad es transitoria (no se instala ni persiste: un reinicio la elimina).
- **Parada de emergencia:** `systemctl stop nexo-p2-cpu` por SSM (mata el grupo de procesos completo) y verificación de que no queda ningún `yes`.
- **Respaldo si SSM no responde:** abrir Session Manager en la consola y ejecutar el mismo `systemctl stop`; si tampoco, esperar al tope de 25 min. **Reiniciar la EC2 no está autorizado** y solo se propondría como último recurso, con nueva autorización.

## 5. Cuándo debería activarse (estimación, no promesa)
- La métrica es de **5 min** (monitoreo básico) y la alarma necesita **2 periodos consecutivos con promedio > 80 %**.
- **Si la carga arranca justo después de un límite de 5 min** (:00, :05, … hasta ≈ 45 s después): los dos periodos siguientes quedan casi completos (≈ 89–99 %). Los datos llegan a CloudWatch con 1–3 min de retraso y la evaluación es de ≈ 1 min → **ALARM aproximadamente 11–15 min** después de empezar.
- **Si arranca a mitad de un periodo** (más de ≈ 1 min tarde): ese periodo queda por debajo del umbral y se necesitan dos más → **≈ 16–20 min**.
- Puede variar por el retraso de entrega de métricas y de evaluación. El tope de 25 min cubre el peor caso razonable; **si no hay ALARM al llegar a 25 min la prueba se da por no concluyente** y se investiga, sin ampliar el tiempo sin autorización.
- **Recuperación a OK:** tras detener la carga, la alarma necesita 2 periodos no superiores → **≈ 10–15 min** (más si el periodo de parada queda a medias).
- **Duración total estimada de la ventana: ≈ 30–45 min**; tope operativo propuesto **60 min**.

## 6. Procedimiento y comandos (NO ejecutados)
Variables (en tu terminal o en la mía, con la sesión vigente):
```bash
export AWS_PROFILE=nexoeventos-lab AWS_DEFAULT_REGION=us-east-1
A=nexoeventos-academy-ec2-cpu-high
IID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=nexoeventos-academy-app Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text)
ssm_run() {  # $1 = comando; imprime el CommandId
  aws ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript --timeout-seconds 60 \
    --cli-input-json "$(python3 -c 'import json,sys;print(json.dumps({"Parameters":{"commands":[sys.argv[1]]}}))' "$1")" --query Command.CommandId --output text
}
ssm_out() { sleep 5; aws ssm get-command-invocation --command-id "$1" --instance-id "$IID" --query '[Status,StandardOutputContent,StandardErrorContent]' --output text; }
```
**Paso 0 – comprobación previa en la instancia (ejecución remota inocua):**
```bash
ssm_out $(ssm_run 'systemd-run --version | head -1; command -v yes nice; nproc; systemctl is-active nexo-p2-cpu || echo libre; uptime')
```
**Paso 1 – línea base y sincronización con el límite de 5 minutos** (esperar a :00/:05/:10… y lanzar dentro de los primeros ≈ 30 s):
```bash
aws cloudwatch describe-alarms --alarm-names $A --query 'MetricAlarms[0].[StateValue,ActionsEnabled]' --output text   # OK True
aws ec2 describe-instances --instance-ids $IID --query 'Reservations[0].Instances[0].State.Name' --output text        # running
aws rds describe-db-instances --db-instance-identifier nexoeventos-academy-postgres --query 'DBInstances[0].DBInstanceStatus' --output text   # stopped
T0=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "T0=$T0"
```
**Paso 2 – iniciar la carga (una sola vez):**
```bash
ssm_out $(ssm_run "systemd-run --unit=nexo-p2-cpu --collect -p RuntimeMaxSec=1500 -p Nice=19 -p MemoryMax=64M /bin/sh -c 'yes >/dev/null & yes >/dev/null & wait'")
```
**Paso 3 – supervisión cada 60 s (solo lectura; abortar si se cumple un criterio de la sección 8):**
```bash
for i in $(seq 1 26); do
  s=$(aws cloudwatch describe-alarms --alarm-names $A --query 'MetricAlarms[0].StateValue' --output text)
  c=$(aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization --dimensions Name=InstanceId,Value=$IID --start-time $(date -u -v-12M +%Y-%m-%dT%H:%M:%SZ) --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 300 --statistics Average --query 'sort_by(Datapoints,&Timestamp)[-1].Average' --output text)
  echo "$(date -u +%H:%M:%SZ) alarma=$s cpu5min=$c"; [ "$s" = ALARM ] && break; sleep 60
done
```
**Paso 4 – al pasar a ALARM (o al abortar) detener la carga y verificarlo:**
```bash
ssm_out $(ssm_run 'systemctl stop nexo-p2-cpu; sleep 2; pgrep -c -x yes || echo 0; systemctl is-active nexo-p2-cpu || true')   # esperado: 0 procesos
```
**Paso 5 – recuperación a OK (solo lectura, máx. 20 min):**
```bash
for i in $(seq 1 40); do s=$(aws cloudwatch describe-alarms --alarm-names $A --query 'MetricAlarms[0].StateValue' --output text); echo "$(date -u +%H:%M:%SZ) $s"; [ "$s" = OK ] && break; sleep 30; done
```
**Paso 6 – evidencia y verificación final (solo lectura):**
```bash
aws cloudwatch describe-alarm-history --alarm-name $A --start-date $T0 --query 'AlarmHistoryItems[].[Timestamp,HistoryItemType,HistorySummary]' --output text | sed -E 's/[0-9]{12}/<cuenta>/g'
aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization --dimensions Name=InstanceId,Value=$IID --start-time $T0 --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 300 --statistics Average Maximum --query 'sort_by(Datapoints,&Timestamp)[].[Timestamp,Average,Maximum]' --output text
aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUCreditBalance --dimensions Name=InstanceId,Value=$IID --start-time $T0 --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 300 --statistics Minimum --query 'sort_by(Datapoints,&Timestamp)[].[Timestamp,Minimum]' --output text
aws cloudwatch describe-alarms --alarm-names $A --query 'MetricAlarms[0].[StateValue,ActionsEnabled,length(AlarmActions),length(OKActions)]' --output text   # OK True 1 1
```
Opcional: `NumberOfNotificationsDelivered` del tema SNS como corroboración.

## 7. Registro de evidencia
1. **Métricas reales:** serie `CPUUtilization` (promedio/máximo cada 5 min) y `CPUCreditBalance` entre T0 y el final.
2. **Transición a ALARM:** `StateUpdate` del historial, cuyo motivo debe citar los **dos datapoints > 80** (a diferencia de P1, donde el motivo era «cambio manual»). Esa diferencia es la prueba de que fue detección real.
3. **Ejecución de SNS:** ítems `Action` «Successfully executed action» (ALARM y, luego, OK).
4. **Correos:** confirmación de la propietaria de ALARM y OK, con horas; capturas **solo si ella las guarda y las sanea** (sin dirección, ID de cuenta ni enlace de baja). No se afirma evidencia visual si no existe.
5. **Recuperación:** hora de vuelta a `OK`, ya sea automática o forzada (si es forzada se documenta como tal).
6. Salidas saneadas con `scripts/cloud/mask.sh` en `docs/evidencias/<fecha>-p2-cpu-real/`.

## 8. Criterios de aborto (detener la carga con `systemctl stop` y documentar)
- Sesión de AWS caducada o error de identidad/región; `AccessDenied` en SSM (no se buscan alternativas).
- El comando SSM falla o la unidad no queda `active`; o hay más de 2 procesos `yes` / otra unidad inesperada.
- La EC2 deja de estar `running`, falla `StatusCheckFailed` (la alarma `ec2-comprobaciones-fallidas` pasa a `ALARM`) o el agente SSM pasa a `ConnectionLost`.
- `CPUSurplusCreditBalance` > 0 (empezaría a haber coste por créditos) o `CPUCreditBalance` cae por debajo de **400** (se esperan ≈ 540 al final).
- La RDS arranca sola y el servicio se degrada de forma imprevista (reactivación automática estimada ≈ 16:51 Perú del 4-nov; planificar la prueba para terminar antes).
- Cualquier alarma distinta de `ec2-cpu-high` pasa a `ALARM`, o aparecen más de 2 correos de la prueba.
- Han pasado **25 min sin ALARM** (no concluyente), o la ventana total supera **60 min**.
- La propietaria pide parar, o la sesión del laboratorio está a punto de expirar (no empezar con menos de ≈ 60 min de sesión).

## 9. Coste incremental (estimación con tarifas públicas, no verificada con facturación)
| Concepto | Estimación |
|---|---|
| Créditos de CPU | Saldo 576; 2 vCPU al 100 % gastan ≈ 1,6 créditos/min netos → **≈ 40 créditos en 25 min**. Queda ≈ 7 % consumido, **sin créditos excedentes** → **0 USD**. Peor caso hipotético con excedentes (0,05 USD por vCPU-hora): ≈ 0,03 USD |
| SSM, SNS (2 correos), CloudWatch (lecturas, alarmas ya existentes) | ≈ 0 USD (capa gratuita) |
| Mantener la EC2 encendida la ventana (≈ 1 h) | ≈ 0,03 USD adicionales (ya está `running` por decisión previa; el coste ≈ 0,7 USD/día continúa mientras siga encendida) |
| **Incremental de P2** | **≈ 0,05 USD, techo ≈ 0,10 USD** |

**¿Alcanza el presupuesto?** El incremento es mínimo, pero **el crédito vigente está PENDIENTE de verificación**: no hay fuente accesible por API. Condición: que confirmes en la consola de Academy un saldo ≥ 10 USD en el momento de autorizar.

## 10. Riesgos
- **Servicio degradado** durante la carga (la aplicación de V1 responde con menos CPU sobrante; con la RDS detenida ya está parcialmente degradada). Mitigación: `Nice=19`, tope automático de 25 min, parada de emergencia.
- **Parada ineficaz si SSM no responde:** mitigación en capas (tope por `RuntimeMaxSec`, Session Manager, reinicio solo con autorización).
- **Créditos `unlimited`:** si el saldo se agotara se cobrarían excedentes; hoy el saldo es máximo y el criterio de aborto vigila 400.
- **Sesión del laboratorio** expirada a mitad de la prueba: no iniciar con poca sesión restante; si ocurre, reanudar solo tras revisar el estado real (la unidad tiene tope propio).
- **Evidencia sobreinterpretada:** carga sintética en una sola instancia; no valida capacidad ni rendimiento con tráfico real.
- **Permisos de Academy** no confirmados hasta ejecutar (la simulación IAM no ve SCP).
- **Datos sensibles** en capturas de correo (cuenta, enlace de baja): sanear antes de archivar.

## 11. Condiciones para autorizar P2
1. Tú confirmas en la consola de Academy un **crédito ≥ 10 USD** y que la sesión tiene **≥ 60 min** restantes.
2. Autorizas expresamente: (a) el comando SSM de comprobación del paso 0, (b) el comando SSM que inicia la carga, (c) el comando SSM de parada, (d) las lecturas de seguimiento.
3. Aceptas el tope de **25 min de carga y 60 min de ventana**, y que no se amplíen sin nueva autorización.
4. EC2 `running`, RDS `stopped`, alarma `ec2-cpu-high` en `OK` y sin otras alarmas activas al empezar.
5. Estás disponible durante ≈ 45 min para revisar el correo (bandeja y spam) y confirmar la recepción de ALARM y OK.
6. Sigue vigente: sin Terraform, sin V2, sin reiniciar/parar EC2 ni RDS, sin commit/push salvo autorización aparte.
