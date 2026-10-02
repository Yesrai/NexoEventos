# Estimación de costo AWS V1

Estimación revisada el 2 de octubre de 2026 para el plan autenticado en `us-east-1`, Linux On-Demand, sin impuestos, descuentos, Free Tier ni créditos. Las listas públicas oficiales confirmaron EC2 `t3.small` a USD 0.0208/h, RDS PostgreSQL `db.t3.micro` Single-AZ a USD 0.018/h, EBS gp3 a USD 0.08/GiB-mes y RDS gp2 a USD 0.115/GiB-mes. Learner Lab denegó `pricing:GetProducts`, por lo que no se presenta esa API como permiso disponible.

El panel mostró **Used USD 0.10 of USD 50**. USD 50 es presupuesto asignado y USD 0.10 es uso mostrado; el remanente aritmético sería USD 49.90, pero no aparece como saldo independiente y AWS Academy advierte un retraso de 8–12 horas.

| Componente | Supuesto | USD/h prorrateado | 8 h | 730 h / 30 días |
|---|---:|---:|---:|---:|
| EC2 | `t3.small`, 2 vCPU, 2 GiB | 0.020800 | 0.1664 | 15.184 |
| RDS PostgreSQL | `db.t3.micro`, Single-AZ | 0.018000 | 0.1440 | 13.140 |
| IPv4 pública | una dirección | 0.005000 | 0.0400 | 3.650 |
| EBS gp3 | 20 GiB a USD 0.08/GiB-mes | 0.002192 | 0.0175 | 1.600 |
| RDS gp2 | 20 GiB a USD 0.115/GiB-mes | 0.003151 | 0.0252 | 2.300 |
| Secrets Manager | un secreto administrado por RDS | 0.000548 | 0.0044 | 0.400 |
| S3 Standard | 1 GiB promedio | 0.000032 | 0.0003 | 0.023 |
| CloudWatch Logs | 1 GB ingerido + 0.2 GB-mes almacenado | 0.000693 | 0.0056 | 0.506 |
| Alarma CloudWatch | una alarma estándar | 0.000137 | 0.0011 | 0.100 |
| **Total estimado** | sin transferencia facturable | **0.050552** | **0.4044** | **36.903** |

## Separación por naturaleza del costo

- Tiempo de ejecución: EC2, RDS e IPv4 suman USD 0.0438/h, USD 0.3504 por 8 h y USD 31.974 por 730 h.
- Almacenamiento/servicios persistentes: EBS, RDS gp2, secreto, S3, almacenamiento de logs y alarma suman aproximadamente USD 4.429/mes.
- Consumo: se reservan USD 0.50 por 1 GB de logs ingeridos. Solicitudes S3 y transferencia facturable son variables y no se incluyen salvo el supuesto de transferencia menor a 100 GB.

La columna por hora prorratea cargos mensuales para comparar escenarios; una jornada real puede redondear consumos mínimos. Para transferencia se supone 5 GB salientes al mes, dentro de los primeros 100 GB mensuales gratuitos publicados por AWS. Por encima de ese umbral, el primer tramo cuesta USD 0.09/GB. La elegibilidad efectiva de esa franquicia en AWS Academy no se ha comprobado, por lo que debe vigilarse el panel de costos.

Fuentes oficiales: [EC2 On-Demand](https://aws.amazon.com/ec2/pricing/on-demand/), [lista pública de precios AWS](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.json), [RDS PostgreSQL](https://aws.amazon.com/rds/postgresql/pricing/), [lista pública de precios RDS](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/us-east-1/index.json), [EBS](https://aws.amazon.com/ebs/pricing/), [IPv4/VPC](https://aws.amazon.com/vpc/pricing/), [S3](https://aws.amazon.com/s3/pricing/), [CloudWatch](https://aws.amazon.com/cloudwatch/pricing/) y [Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/).

## Qué sigue cobrando al detener

- Al detener EC2 deja de cobrarse el cómputo y su IPv4 autoasignada se libera, pero el volumen EBS sigue cobrando mientras exista.
- Al detener RDS deja de cobrarse la instancia; siguen el almacenamiento y los backups. AWS inicia automáticamente la instancia después de siete días detenida.
- S3, CloudWatch Logs, snapshots y Secrets Manager siguen cobrando mientras existan.
- Eliminar recursos puede generar un snapshot final si se configura; la V1 actual usa `skip_final_snapshot = true` para el laboratorio, decisión que debe reevaluarse antes de una entrega final.

La cifra de USD 36.903/mes es una estimación, no un resultado medido ni una garantía de factura. El plan autenticado confirmó los recursos, no el permiso de creación ni las cuotas. El calendario conservador hasta el 26 de noviembre está en `docs/operacion/calendario-credito-aws.md` y estima USD 10.164 bajo 37 horas activas y 52 días de persistencia.
