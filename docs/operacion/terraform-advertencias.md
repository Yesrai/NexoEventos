# Advertencias de Terraform y propuestas no aplicadas

Estado al 4 de octubre de 2026: revisión local; **ningún parche de `infra/aws/propuestas/` se aplicó**, no se ejecutó `plan`, `apply`, `refresh` ni `destroy`, y no se consultó AWS. El bucket S3 **permanece administrado en el estado**.

## Decisiones

| Tema | Hallazgo | Decisión local | Verificación cloud pendiente |
|---|---|---|---|
| AMI EC2 | `most_recent = true` puede seleccionar una AMI nueva y proponer reemplazo | prioridad: fijar explícitamente la AMI desplegada mediante `ec2_ami_id`; **no** añadir `ignore_changes` | plan autenticado, aceptable solo sin reemplazo ni eliminación |
| RDS storage autoscaling | `max_allocated_storage = allocated_storage = 20` no aporta margen y generó advertencia | variable explícita; `0` desactiva, o un valor > 20 y ≤ 100 habilita con margen | comprobar `MaxAllocatedStorage` y `PendingModifiedValues` con RDS activa antes de cualquier aplicación |
| lectura S3 | Learner Lab denegó `s3:GetBucketObjectLockConfiguration` durante refresh | conservar `aws_s3_bucket.private` en el estado y documentar la limitación; **no** usar `removed` | un plan completo seguirá pendiente hasta contar con lectura permitida o una solución compatible verificada |
| ciclo de vida S3 | el respaldo real usa `backups/database/`, pero la regla Terraform filtra `database-backups/` | propuesta 0003 alinea únicamente el prefijo; no aplicada | plan y lectura posterior de la regla; hasta entonces el objeto puede persistir más de lo previsto |

## 1. AMI fijada, sin ocultar deriva

La propuesta [0001-fijar-ami-desplegada.patch](../../infra/aws/propuestas/0001-fijar-ami-desplegada.patch) elimina el selector dinámico y exige `ec2_ami_id`.

- Academy fija la AMI observada en el despliegue del 3 de octubre.
- Otra cuenta debe elegir y registrar explícitamente una AMI AL2023 válida para su región.
- Cambiar la variable mostrará el reemplazo de EC2 en el plan; no se oculta con `ignore_changes`.
- La propuesta solo se incorpora después de `terraform fmt`, `validate` y un plan autenticado que confirme 0 reemplazos.

Esta opción mejora reproducibilidad y mantiene visible cualquier cambio destructivo.

## 2. Autoescalado de almacenamiento RDS

El proyecto fija `hashicorp/aws = 6.67.0`. Para `aws_db_instance`, `max_allocated_storage` es opcional; el proveedor acepta `0` para deshabilitar explícitamente el autoescalado. La API de RDS también trata un máximo igual al almacenamiento asignado como autoescalado desactivado. El proyecto adopta una validación deliberadamente más estricta al habilitarlo: **mayor** que el asignado, porque un máximo igual no deja capacidad de crecimiento.

La propuesta [0002-rds-desactivar-autoescalado.patch](../../infra/aws/propuestas/0002-rds-desactivar-autoescalado.patch):

- usa `0` por defecto para la V1 de costo acotado;
- permite > `db_allocated_storage_gib` y ≤ 100 GiB si se decide habilitarlo;
- no promete que el cambio esté aplicado ni que el laboratorio permita `ModifyDBInstance`;
- requiere RDS `available`, revisión del plan y aprobación propia antes de aplicar.

Referencias oficiales: [proveedor `aws_db_instance`](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/db_instance) y [RDS Storage Autoscaling](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIOPS.Autoscaling.html). La versión fijada se comprueba en `versions.tf` y `.terraform.lock.hcl`.

## 3. Denegación de lectura S3

Hecho observado: el refresh del recurso bucket fue denegado por la política del laboratorio al intentar `s3:GetBucketObjectLockConfiguration`.

Consecuencias:

- no se puede afirmar un `No changes` general;
- un plan con `-refresh=false` puede servir para inspeccionar cambios de configuración, pero **no detecta deriva** y no completa I01/EV09;
- un plan dirigido omite parte del grafo y tampoco reemplaza una revisión integral;
- retirar el bucket del estado reduciría control y portabilidad, por lo que se descarta.

Alternativas futuras, sin ampliar privilegios ahora:

1. conservar el estado y presentar la denegación como limitación comprobada;
2. verificar si una versión posterior del proveedor evita esa lectura sin perder gestión, en una sesión/plan separado;
3. ejecutar la revisión integral en una cuenta autorizada que sí permita la lectura;
4. solicitar al responsable del laboratorio una aclaración de permisos, sin eludir la SCP.

## Secuencia segura futura

1. Aplicar primero solo la propuesta de AMI en una rama local y ejecutar `fmt`/`validate`.
2. Con credenciales vigentes, generar plan nuevo; detenerse ante cualquier `-/+` o eliminación.
3. Evaluar la propuesta RDS por separado, con RDS activa y respaldo confirmado.
4. Revisar la propuesta 0003 de prefijo S3 sin retirar el bucket del estado.
5. Mantener el bucket en estado en todos los casos.
6. Registrar la denegación S3 si impide el refresh; no presentar `-refresh=false` como prueba de ausencia de deriva.

Ninguna de estas acciones forma parte de la revisión local actual.
