# Apply de alarmas V1 — 4-nov-2026 (saneado)

Precondiciones: crédito de Academy confirmado por la propietaria (50 USD total, 9,50 gastados, 40,50 disponibles); perfil `nexoeventos-lab`; estado Terraform serie 36 antes del apply; plan guardado verificado con `scripts/cloud/verificar-plan-alarmas.py`: **7 creaciones, 1 actualización (solo `alarm_actions`/`ok_actions` de la alarma de CPU de EC2), 0 destrucciones**; sin correos en el plan.

Resultado: `Apply complete! Resources: 7 added, 1 changed, 0 destroyed.` (estado serie 46). Plan guardado eliminado tras su uso.

| Alarma | Métrica / estadístico | Umbral | Periodos | Datos faltantes | Estado inicial | Acciones |
|---|---|---|---|---|---|---|
| ec2-comprobaciones-fallidas | EC2 StatusCheckFailed, Máximo | ≥ 1 | 3×60 s | notBreaching | INSUFFICIENT_DATA | SNS (alarma y OK) |
| ec2-cpu-high (modificada) | EC2 CPUUtilization, Promedio | > 80 | 2×300 s | missing | OK | SNS (alarma y OK) |
| rds-cpu-alta | RDS CPUUtilization, Promedio | > 80 | 3×300 s | missing | INSUFFICIENT_DATA (RDS detenida) | SNS |
| rds-espacio-libre-bajo | RDS FreeStorageSpace, Mínimo | < 2 GiB | 2×300 s | missing | INSUFFICIENT_DATA | SNS |
| rds-memoria-liberable-baja | RDS FreeableMemory, Mínimo | < 100 MiB | 3×300 s | missing | INSUFFICIENT_DATA | SNS |

Tema SNS `nexoeventos-academy-alarmas`: política con dos sentencias (eventos de RDS y CloudWatch, `Allow sns:Publish`, condición `aws:SourceAccount`). Suscripciones confirmadas: 0; pendientes: 0. Suscripción a eventos de RDS activa (categorías: failover, failure, notification, low storage, availability).

Estados tras el apply: EC2 `running`, RDS `stopped` (sin cambios).

## Qué está y qué NO está probado (al momento del apply; ver actualización al final)
- Alarmas desplegadas: SÍ. SNS configurado: SÍ. Suscripción de correo: **PENDIENTE**. Notificación enviada: **NO**. Correo recibido: **NO**.
- Las alarmas de RDS están en INSUFFICIENT_DATA porque la RDS está detenida; se evaluarán cuando esté encendida.

## Actualización posterior (4-nov-2026)
La suscripción de correo fue confirmada por la propietaria y P1 se completó después (ver `../20261104-p1-notificacion/resultado.md`). Lo anterior describe el estado inmediatamente posterior al apply.
