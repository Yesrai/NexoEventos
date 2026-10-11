# Informe de sesión AWS — 9 de octubre de 2026

## Alcance ejecutado

No se desplegó código, no se aplicó Terraform y no se ejecutaron migraciones. STS confirmó la cuenta esperada y `us-east-1`. EC2 y RDS ya estaban activas; no se enviaron órdenes de arranque. DNS se actualizó mediante el timer DuckDNS existente y `cloud-session.sh check` terminó con `rc=0` para HTTPS, health, API y respaldos.

Versión comprobada: `7955e7e`.

## Pendiente cerrado: E01

Prueba cloud válida: 20 usuarios virtuales, rampa 30 s y 300 s medidos, usando clientes `@example.com` y un evento exclusivo `[CARGA]` de 1 000 cupos.

| Medida | Resultado real |
|---|---:|
| solicitudes | 2 520 |
| promedio | 8.4 solicitudes/s |
| p50 | 382.3 ms |
| p95 | 421.2 ms |
| p99 | 585.1 ms |
| errores inesperados | 0 (0 %) |
| conflictos esperados | 0 |
| reservas correctas | 132 × 201 |

La verificación directa posterior encontró 132 reservas, 132 claves de idempotencia distintas, 132 cupos contabilizados y 132 entradas. No hubo sobreventa ni reservas duplicadas. E01 cumplió sus umbrales definidos en esta escala.

## Evidencia AWS nueva

- inventario sanitizado de VPC, subredes/rutas, SG, EC2, RDS privada, snapshot/S3 y CloudWatch antes y después de E01;
- EC2 CPU: 2 puntos de monitoreo básico, promedio 3.53 %, máximo 6.05 %;
- RDS CPU: 7 puntos, promedio 4.66 %, máximo 5.37 %;
- RDS conexiones: promedio 8.86, máximo 10;
- alarma CPU `OK`;
- aplicación HTTPS y base disponibles durante la prueba.

Limitación encontrada: los dos grupos de logs conservan retención de 7 días, pero no tienen streams. El agente de CloudWatch no está instalado ni configurado. El rol de instancia sí evaluó como permitidas `logs:CreateLogStream` y `logs:PutLogEvents`. No se afirma recepción de logs y no se modificó la EC2 para ocultar el problema.

## Recuperación preparada, no ejecutada

R01 queda definida con PITR desde la RDS original hacia una única RDS temporal privada `nexoeventos-academy-restore-<AAAAMMDDtHHMM>`. El recibo `0600`, el hash del ARN y las etiquetas de ejecución limitan la limpieza a esa copia. Se medirán por separado punto recuperable, RDS disponible y datos verificados; el servicio completo seguirá pendiente si no se conmuta la aplicación.

Estimación vigente para la copia temporal: USD 0.02–0.03/h más almacenamiento/backup proporcional, a confirmar antes de ejecutar. El dump/snapshot manual tenía 38 h al cierre y queda como respaldo histórico; `LatestRestorableTime` alcanzaba 2026-10-09 15:39 UTC.

## Cierre

AWS confirmó a las 10:51 Lima:

- EC2: `stopped`;
- RDS original: `stopped`;
- RDS temporal: no creada;
- prefijos S3 `ansible/`, `tmp/` y `temporary/`: sin objetos vigentes;
- reinicio automático aproximado de RDS: 16 de octubre de 2026, 10:51 Lima.

Siguen generando consumo persistente: EBS, almacenamiento/backups de RDS, snapshot manual, S3, secreto, grupos de logs y alarma. La ventana observada por esta sesión fue de aproximadamente una hora; no se presenta como consumo total porque ambos recursos ya estaban activos al recuperar las credenciales.
