# Advertencias de Terraform y correcciones locales pendientes de plan

Estado al 7 de octubre de 2026: las tres correcciones se incorporaron a la configuración local y `terraform validate` fue satisfactorio contra el estado protegido real `academy-current` (serial 32). **No se ejecutó plan, apply, refresh ni destroy** porque STS devolvió `InvalidClientTokenId`. El bucket S3 permanece administrado en el estado.

## Decisiones

| Tema | Hallazgo | Decisión local | Verificación cloud pendiente |
|---|---|---|---|
| AMI EC2 | `most_recent = true` podía seleccionar una AMI nueva y proponer reemplazo | `ec2_ami_id` se reconstruye desde la EC2 del estado; sin `ignore_changes` | plan autenticado, aceptable solo sin reemplazo ni eliminación |
| RDS storage autoscaling | máximo igual al asignado no aportaba margen | `0` lo desactiva; si se habilita exige ≥ 10 % adicional y ≤ 100 GiB | comprobar plan, `MaxAllocatedStorage` y `PendingModifiedValues` antes de aplicar |
| lectura S3 | Learner Lab denegó `s3:GetBucketObjectLockConfiguration` durante refresh | conservar `aws_s3_bucket.private` en el estado y documentar la limitación; **no** usar `removed` | un plan completo seguirá pendiente hasta contar con lectura permitida o una solución compatible verificada |
| ciclo de vida S3 | el respaldo real usa `backups/database/`, pero la regla filtraba `database-backups/` | prefijo local alineado a `backups/database/` | plan y lectura posterior; hasta aplicar, el objeto remoto puede persistir más de lo previsto |

## 1. AMI fijada, sin ocultar deriva

La configuración elimina el selector dinámico y exige `ec2_ami_id`; `reconstruct-academy-tfvars.py` toma el valor de la EC2 ya administrada, sin imprimirlo.

- Academy fija la AMI observada en el despliegue del 3 de octubre.
- Otra cuenta debe elegir y registrar explícitamente una AMI AL2023 válida para su región.
- Cambiar la variable mostrará el reemplazo de EC2 en el plan; no se oculta con `ignore_changes`.
- `fmt` y `validate` están completos; falta un plan autenticado que confirme 0 reemplazos.

Esta opción mejora reproducibilidad y mantiene visible cualquier cambio destructivo.

## 2. Autoescalado de almacenamiento RDS

El proyecto fija `hashicorp/aws = 6.67.0`. Para `aws_db_instance`, `max_allocated_storage` es opcional; el proveedor acepta `0` para deshabilitar explícitamente el autoescalado. La API de RDS también trata un máximo igual al almacenamiento asignado como autoescalado desactivado. El proyecto adopta una validación deliberadamente más estricta al habilitarlo: **mayor** que el asignado, porque un máximo igual no deja capacidad de crecimiento.

La variable `db_max_allocated_storage_gib`:

- usa `0` por defecto (valor de la variable para una V1 nueva de costo acotado). **La RDS real de Academy ya no está en ese caso** (6-nov-2026): es Multi-AZ y su máximo es 40 GiB (se subió con la CLI desde 20). Por eso `work/terraform-envs/academy.tfvars` debe declarar `db_max_allocated_storage_gib = 40`, `db_multi_az = true` y `db_apply_immediately`; **omitir `db_multi_az` (valor por defecto false) o dejar el máximo en 0 propondría quitar Multi-AZ o el autoescalado**. `scripts/reconstruct-academy-tfvars.py` ya lee esos valores del estado y conserva el mayor máximo entre el estado y el archivo actual;
- permite habilitarlo solo con al menos 10 % por encima de `db_allocated_storage_gib` y ≤ 100 GiB;
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

1. Renovar credenciales una sola vez y confirmar STS/cuenta/región.
2. Generar un plan nuevo contra `academy-current`; detenerse ante cualquier `-/+` o eliminación.
3. Si Object Lock bloquea el refresh, registrar la denegación. Un plan `-refresh=false` solo puede ayudar a inspeccionar configuración y no autoriza apply.
4. Aplicar las tres correcciones únicamente tras revisar el plan y confirmar respaldo/estado RDS.
5. Mantener el bucket en estado en todos los casos.
6. Registrar la denegación S3 si impide el refresh; no presentar `-refresh=false` como prueba de ausencia de deriva.

El wrapper ya cancela si falta `work/terraform-state/<entorno>-current/terraform.tfstate`; no vuelve a inicializar silenciosamente `academy/` como estado paralelo.
