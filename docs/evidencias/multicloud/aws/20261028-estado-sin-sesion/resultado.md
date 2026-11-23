# AWS — comprobación de sesión y riesgo de reinicio de la RDS (28-oct-2026)

**Resultado: no hay sesión de AWS Academy activa; no se consultó nada en AWS.** La única llamada fue `sts get-caller-identity` (solo lectura) con el perfil `nexoeventos-lab`, que devolvió `ExpiredToken` («The security token included in the request is expired»). No existe otro perfil ni variables `AWS_*`. No se intentó iniciar el laboratorio, renovar credenciales ni ninguna otra operación, conforme a la instrucción de la propietaria.

## Lo que se puede afirmar solo con registros locales (no verificado contra AWS)
Fuente: `work/operacion/sesiones-cloud.log` (órdenes autorizadas) y [`20261023-respaldo-0008/resultado.md`](../20261023-respaldo-0008/resultado.md).
| Dato | Valor | Fuente |
|---|---|---|
| Última orden `stop-db-instance` aceptada | 2026-10-23 15:10:33Z | registro de sesiones |
| `stopped` verificado | ≈ 15:17:53Z (orden + 440 s) | respaldo-0008 |
| Último registro de actividad en AWS | 2026-10-23 19:20Z (EC2 detenida tras un reinicio del laboratorio; lectura de un secreto) | registro de sesiones |
| **Reinicio automático estimado de la RDS (7 días detenida)** | **≈ 2026-10-30 15:18Z** | cálculo |
| Margen a las 19:5xZ del 28-oct | **≈ 43 h** | cálculo |
| Costo si ocurriera | Multi-AZ `db.t3.micro` ≈ 0,036 USD/h ≈ 0,86 USD/día hasta volver a detenerla | tarifa pública |

**Incertidumbres:** (1) no se sabe si el reinicio del laboratorio del 23-oct (19:20Z) o una sesión posterior no registrada modificó el estado de la RDS; (2) AWS describe el reinicio como «tras siete días», sin hora exacta; (3) el estado real solo puede leerse con una sesión activa.

## Recursos que, según la documentación, siguen generando costo (NO verificado)
Almacenamiento de la RDS Multi-AZ (20 GiB ×2), snapshots manuales de RDS, EBS gp3 20 GiB de la EC2 de V1 (detenida) y AMI/snapshots propios, S3 (respaldos), Secrets Manager (≥ 1–2 secretos) y logs de CloudWatch. Orden de magnitud documentado: ≈ 0,21–0,22 USD/día. Sin ALB, ASG, NAT ni IPv4 elástica (V2 destruida) **según los registros**, no por consulta.

## Herramientas dejadas listas (sin ejecutar contra AWS)
- [`scripts/cloud/readonly-audit.py`](../../../../../scripts/cloud/readonly-audit.py): auditoría de solo lectura con una **guarda en código** que rechaza inicio, parada, reinicio, modificación, borrado, lectura de secretos/objetos y Cost Explorer (`ce`, con cargo por consulta). Probada: `--selftest` OK (rechaza 12 operaciones de escritura/costo, admite las de lectura, enmascara cuenta, IDs, IP, correo y endpoint) y `--dry-run`.
- [`scripts/observability/export-cloudwatch.py`](../../../../../scripts/observability/export-cloudwatch.py) (esquema 2): guarda **series originales** por recurso con su resolución observada y, aparte, los puntos **derivados** (combinados) solo para Zabbix.
- [`scripts/observability/plot-cloudwatch.py`](../../../../../scripts/observability/plot-cloudwatch.py): gráficos SVG sin interpolación, con fuente, periodo UTC, resolución observada y número de puntos; `--selftest` OK.
