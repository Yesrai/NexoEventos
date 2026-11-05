# Fase 0 — lectura de solo lectura de AWS Academy (3-nov-2026) — resultado saneado

Perfil `nexoeventos-lab`, región `us-east-1`. Solo consultas de lectura (`describe-*`, `list-*`, `get-*`, `get-metric-statistics`, `simulate-principal-policy`). Sin creación, modificación, inicio ni detención de recursos; sin lectura de valores de secretos; sin `set-alarm-state`; sin Cost Explorer. Identidad: la cuenta coincide con la esperada (comprobado sin imprimirla). IDs de cuenta, ARN, identificadores de recursos, IP y usuario enmascarados; no se guardan salidas crudas.

## 1. Estado de los recursos
| Recurso | Estado | Nota |
|---|---|---|
| RDS `nexoeventos-academy-postgres` | **stopped** | db.t3.micro, Multi-AZ, 20 GiB asignados y umbral máximo 20 GiB, copias automáticas 7 días, CA `rds-ca-rsa2048-g1`, sin modificaciones pendientes |
| EC2 `nexoeventos-academy-app` | **running** (lanzada hoy 16:46 UTC = 11:46 Perú, al iniciar el laboratorio) | t3.small; **genera coste**; no se tocó |
| Otras instancias EC2 | ninguna encendida | solo la anterior |
| ALB, grupos de destino, ASG, plantillas de lanzamiento (V2) | **0** | V2 sigue destruida |
| IP elásticas / NAT Gateway | 0 / 0 | sin cargos de estos recursos |
| Volúmenes EBS | 1 (20 GiB, cifrado, en uso) | el disco de la EC2 en ejecución |

## 2. Eventos de RDS (14 días)
Último evento: **28-oct 21:51:22 UTC (16:51 Perú) «DB instance stopped»**. **No hay eventos posteriores**: la RDS no se ha reiniciado sola. Reinicio automático previsto (7 días): **4-nov 21:51 UTC (16:51 Perú)**. Se repiten los avisos «Storage size 20 GiB is approaching the maximum storage threshold 20 GiB» (23-oct 00:30 UTC y 28-oct 21:45 UTC).

## 3. `FreeStorageSpace` y `FreeableMemory` (CloudWatch, periodo de 60 s, estadísticas mínimo/promedio/máximo)
| Ventana (UTC = Perú + 5 h) | Puntos | Minutos sin dato | `FreeStorageSpace` mín / prom / máx | `FreeableMemory` mín / prom / máx |
|---|---:|---:|---|---|
| 23-oct 00:13–01:55 UTC (22-oct 19:13–20:55 Perú; incluye el failover de 01:08 UTC) | 103 | 0 | 17,05 / 17,11 / 17,12 GiB | 165,87 / 186,44 / 223,50 MiB |
| 23-oct 15:03–15:11 UTC (10:03–10:11 Perú) | 9 | 0 | 17,12 / 17,12 / 17,12 GiB | 214,86 / 230,72 / 267,84 MiB |
| 28-oct 21:37–21:45 UTC (16:37–16:45 Perú) | 8 | 1 | 17,12 / 17,12 / 17,12 GiB | 214,30 / 238,80 / 274,42 MiB |
**Conclusión:** de 20 GiB asignados quedaban **≈ 17,1 GiB libres (≈ 85 %)** en las tres ventanas, con un mínimo de 17,05 GiB: **no hay evidencia de poco almacenamiento**; el aviso de «20 GiB / umbral 20 GiB» es de configuración (el autoescalado no puede crecer porque umbral = asignado), no de espacio libre. **Observación nueva:** la memoria liberable es baja (mínimo 166 MiB sobre 1 GiB de RAM en una db.t3.micro): es el recurso más ajustado, no el disco. Lecturas limitadas a las ventanas en que la RDS estuvo encendida; no hay datos fuera de ellas.

## 4. S3 y respaldos (solo metadatos)
- Un bucket del proyecto, con versionado **Enabled**, cifrado **AES256 (SSE-S3)** y bloqueo de acceso público completo. Prefijos de primer nivel: `backups/` y `deployment-source/`.
- **Lifecycle desplegado:** una regla `expire-demo-backups`, activa, sobre el prefijo **`database-backups/`** con caducidad de 7 días (y 7 días para versiones no vigentes). En `database-backups/` hay **0 objetos**: la regla **no borra nada hoy**. Confirma la deriva documentada.
- **Respaldos reales en `backups/database/`** (4 objetos cifrados `.cms`, 4 versiones, 0 marcas de borrado): 04-oct (31 KB), 08-oct (22 KB), 19-oct (78 KB), 23-oct (92 KB).
- **Riesgo confirmado antes de aplicar la nueva retención:** alinear el prefijo con la retención de **7 días** habría hecho caducar los **4** respaldos (todos tienen más de 7 días). Con **90 días** caducarían el 2-ene, 6-ene, 17-ene y 21-ene-2027 (caducidad desde la fecha de modificación, aproximada). De ellos, en OCI solo está el del 23-oct; los otros tres solo existen en AWS y en la copia local. Recomendación: **365 días** o copiar antes de aplicar.

## 5. Alarmas, SNS, CloudTrail y eventos
- **Alarmas CloudWatch:** una sola, `nexoeventos-academy-ec2-cpu-high` (EC2/CPUUtilization), estado **OK**, **0 acciones** de alarma y 0 de OK. Sin alarmas compuestas ni de escalado (V2 destruida).
- **SNS:** un tema ajeno al proyecto (`RedshiftSNS`, con una suscripción de tipo lambda); **el acceso a sus atributos tiene una denegación explícita** de la política de Academy. Ningún tema ni suscripción de NexoEventos.
- **CloudTrail:** **0 trails**. **Suscripciones a eventos de RDS:** 0.

## 6. Dependencias para reconstruir V2
| Dependencia | Estado |
|---|---|
| AMI dorada `nexoeventos-v2-20261022t051316z` | **existe** (available, 20 GiB, 22-oct) con **1 instantánea EBS**; es **anterior** a `/livez` y a las demás correcciones: hay que reconstruirla |
| Secreto compartido `nexoeventos/academy/backend-env` | **existe** (modificado el 21-oct); valor no consultado |
| Secreto maestro de RDS (gestionado por AWS) | existe; **«última modificación» hoy 3-nov 14:27 hora de Perú**; causa no investigada, valor no consultado (la aplicación usa credenciales propias, no la maestra) |
| Certificado en ACM | **ninguno** (el certificado importado ya no existe): hay que volver a importarlo, y la EC2 de V1 está encendida ahora |
| Launch templates / ALB / ASG / grupos de destino | ninguno |

## 7. Permisos observables
`iam:SimulatePrincipalPolicy` **no fue denegado** sobre el rol `voclabs` (el que ejecuta la CLI): **permitidos** `cloudwatch:PutMetricAlarm`, `sns:CreateTopic/Subscribe/SetTopicAttributes`, `cloudtrail:CreateTrail`, `rds:CreateEventSubscription/AddSourceIdentifierToSubscription`, `autoscaling:PutNotificationConfiguration`, `elasticloadbalancing:CreateLoadBalancer`, `ec2:CreateImage`, `s3:PutLifecycleConfiguration` y `acm:ImportCertificate`. **Límite:** la simulación evalúa solo las políticas de identidad; no incluye SCP ni denegaciones por recurso (hay una denegación explícita visible sobre el tema `RedshiftSNS`). Es un indicio, no una garantía: se confirmará con el `plan`/`apply`.

## 8. Costes (estimaciones con tarifas públicas, no verificadas con la facturación)
- **Crédito restante de Academy: no se puede leer por CLI sin Cost Explorer** (no se usó); hay que consultarlo en la página del laboratorio. **No está confirmado.**
- **Genera cargos ahora:** EC2 t3.small encendida (≈ 0,02 USD/h de cómputo + IPv4 pública y disco ≈ 0,03 USD/h en total ≈ 0,7 USD/día); almacenamiento de la RDS detenida Multi-AZ (≈ 4–5 USD/mes), instantáneas (RDS, AMI), 2 secretos (≈ 0,8 USD/mes), 1 volumen EBS. Si la RDS se reinicia el 4-nov: ≈ 0,036 USD/h (≈ 0,9 USD/día) hasta detenerla.
- La estimación de 1,3 USD del plan sigue siendo **una estimación**.

## 9. Riesgos y acciones que requieren autorización
1. **EC2 encendida** (decidir: detenerla o aprovecharla para la Fase 2/3); **RDS** con reinicio automático el 4-nov 21:51 UTC.
2. **Respaldos**: los 4 `.cms` caducarían con 7 días; 3 no tienen copia externa.
3. **Sin alarmas con acciones, sin SNS propio, sin trail**.
4. **Memoria de la RDS ajustada** (mínimo 166 MiB).
5. Certificado de ACM inexistente y AMI antigua para V2.
Cada acción sobre EC2/RDS, S3, SNS, ACM o AMI necesita autorización explícita.
