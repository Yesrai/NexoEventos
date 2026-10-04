# Costos AWS V1 corregidos

Estimación revisada el 2 de octubre de 2026 para `us-east-1`, Linux On-Demand, sin impuestos, Free Tier ni créditos aplicados. **Treinta días son 720 horas**; 730 horas es una convención mensual promedio que no se usa aquí para representar 30 días. El presupuesto de USD 50 comunicado por AWS Academy es el límite disponible indicado por el laboratorio, no un saldo actual confirmado ni un tope automático de facturación.

## Un periodo de 30 días exactos

| Categoría | Recurso y supuesto | Tarifa | 720 h / 30 días |
|---|---|---:|---:|
| ejecución | EC2 `t3.small` | USD 0.0208/h | USD 14.976 |
| ejecución | RDS PostgreSQL `db.t3.micro`, Single-AZ | USD 0.018/h | USD 12.960 |
| ejecución | una IPv4 pública mientras EC2 está activa | USD 0.005/h | USD 3.600 |
| almacenamiento | EBS gp3 20 GiB | USD 0.08/GiB-mes | USD 1.600 |
| almacenamiento | RDS gp2 20 GiB | USD 0.115/GiB-mes | USD 2.300 |
| servicio persistente | un secreto maestro administrado | USD 0.40/mes | USD 0.400 |
| almacenamiento | S3 1 GiB Standard supuesto | USD 0.023/GiB-mes | USD 0.023 |
| almacenamiento | CloudWatch Logs 0.20 GiB supuesto | USD 0.03/GiB-mes | USD 0.006 |
| servicio persistente | una alarma estándar | USD 0.10/mes | USD 0.100 |
| consumo variable base | ingestión de 1 GiB de logs | USD 0.50/GiB | USD 0.500 |
| **total** | sin margen |  | **USD 36.465** |

Una jornada aislada de ocho horas cuesta USD 0.3504 en EC2/RDS/IPv4. Prorrateando además un mes de persistencia como 720 horas y 1 GiB mensual de logs, el equivalente es aproximadamente **USD 0.405**; detener cómputo no elimina los componentes persistentes.

## Calendario real propuesto hasta la entrega

> **Actualización del 4 de octubre de 2026:** la V1 se desplegó el 3 de octubre y EC2/RDS quedaron detenidas al final de la sesión. Por tanto, ya no es correcto afirmar costo cloud cero ni `apply` pendiente. Aún faltan consolidar `LaunchTime`, `InstanceCreateTime` y el consumo observado; hasta entonces el cuadro siguiente se conserva como **forecast previo**, no como costo real.

El forecast histórico usa el escenario conservador desde **2 de octubre de 2026 15:00 (Lima)** hasta **26 de noviembre de 2026 23:59 (Lima)**: 1,328.983 horas, equivalentes a 1.845810 periodos de 720 horas. Se reemplazará por horas observadas cuando se capture el inventario.

| Componente | Horas/periodo | Importe previsto |
|---|---:|---:|
| EC2 activa | 37 h | USD 0.770 |
| RDS activo | 37 h | USD 0.666 |
| IPv4 pública | 37 h | USD 0.185 |
| EBS + RDS storage + secreto + S3 + logs almacenados + alarma | 1,328.983 h | USD 8.175 |
| ingestión variable base | 1.845810 GiB supuesto | USD 0.923 |
| **subtotal** | | **USD 10.719** |
| margen explícito para solicitudes S3, transferencia, créditos T3, más logs y desvíos | | **USD 3.000** |
| **techo planificado** | | **USD 13.719** |

`scripts/calculate-aws-budget.py` reproduce el forecast. Falta reconciliarlo con timestamps y consumo reales; la estimación no demuestra elegibilidad de servicios ni garantiza el precio final.

## Qué continúa cobrando

- Detener EC2 elimina el cómputo y normalmente libera su IPv4 pública autoasignada, pero EBS, snapshots, S3, CloudWatch y el secreto permanecen.
- Detener RDS elimina la tarifa de instancia mientras esté realmente `stopped`; almacenamiento y backups continúan. Consultar el estado o volver a enviar `stop-db-instance` no reinicia el máximo de siete días.
- El snapshot final queda después de eliminar RDS. Como escenario conservador, 20 GiB a USD 0.095/GiB-mes son **USD 1.90/mes** tras la eliminación; el cobro real depende del almacenamiento incremental y de la asignación gratuita de backups mientras exista la instancia.
- No se incluyeron impuestos, transferencia saliente, solicitudes S3, CPU excedente T3 ni almacenamiento que supere los supuestos.

## Control del crédito

Se revisará manualmente el consumo mostrado por Academy antes y después de cada sesión. Al llegar a USD 30: reconciliar inventario, horas y forecast, detener cómputo no esencial y confirmar backups/evidencias. Al llegar a USD 40: no iniciar nuevas pruebas, preparar cierre/backup y solicitar una decisión explícita sobre conservación o desmontaje. Estas revisiones son puntos de decisión; **no son límites automáticos de gasto** y el panel puede tener retraso.

Fuentes vigentes: páginas oficiales de precios de [EC2](https://aws.amazon.com/ec2/pricing/on-demand/), [RDS PostgreSQL](https://aws.amazon.com/rds/postgresql/pricing/), [VPC/IPv4](https://aws.amazon.com/vpc/pricing/), [EBS](https://aws.amazon.com/ebs/pricing/), [S3](https://aws.amazon.com/s3/pricing/), [CloudWatch](https://aws.amazon.com/cloudwatch/pricing/) y [Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/). Learner Lab denegó previamente `pricing:GetProducts`; los valores se consultaron en fuentes públicas, no mediante un permiso de la cuenta.
