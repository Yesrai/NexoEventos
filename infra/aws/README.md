# AWS V1 portable

Terraform describe una V1 de demostración: VPC `10.20.0.0/16`; EC2 `t3.small` Amazon Linux 2023 en `10.20.1.0/24`; RDS PostgreSQL `db.t3.micro` privado/Single-AZ en dos subredes de datos; EBS gp3 20 GiB; RDS gp2 20 GiB; S3 privado/versionado; dos log groups y una alarma. No incluye NAT Gateway, ALB, Auto Scaling, Multi-AZ ni réplica.

El snapshot final está habilitado (`skip_final_snapshot = false`) y su nombre es obligatorio por entorno. PostgreSQL 5432 solo recibe tráfico del SG de la aplicación. 80/443 son públicos y SSH permanece cerrado salvo `/32` temporal explícito.

## Una configuración por cuenta

Los ejemplos están en `environments/academy.tfvars.example` y `environments/authorized-account.tfvars.example`. Cada copia real vive en `work/terraform-envs/<entorno>.tfvars` y define cuenta esperada, región, sufijos, tamaños y perfil existente. No hay ID de cuenta codificado en Terraform.

```bash
./scripts/terraform-account.sh fmt academy
./scripts/terraform-account.sh validate academy
./scripts/terraform-account.sh plan academy
```

El wrapper consulta STS y cancela si la identidad difiere de `expected_account_id`; no muestra el ID. Mantiene estado, caché y plan separados por nombre de entorno bajo `work/`, ignorado por Git. El subcomando `apply` exige además `NEXO_ALLOW_APPLY=YES` y un plan guardado; cada aplicación necesita aprobación explícita de su plan.

No se debe reutilizar el estado Academy para otra cuenta. Una cuenta normal necesita su propio perfil IAM autorizado; no se presupone que `LabRole` o `LabInstanceProfile` existan. También deben reevaluarse permisos, SCP, cuotas, regiones, costos y financiación.

## Estado de comprobación

**Actualización del 7 de octubre de 2026:** la V1 desplegada conserva 30 recursos en el estado protegido `academy-current`. Localmente se fijó la AMI observada, se desactivó explícitamente el autoescalado RDS y se alineó el ciclo de vida con `backups/database/`; `fmt` y `validate` aprobaron. Esos cambios **no están aplicados** y requieren un plan autenticado. `s3:GetBucketObjectLockConfiguration` sigue siendo una limitación de refresh. Véase [`docs/operacion/terraform-advertencias.md`](../../docs/operacion/terraform-advertencias.md).


Registro histórico previo al despliegue: el plan del commit `25a12c1` no se reutilizó; se renovó la sesión, STS validó identidad y un plan nuevo mostró **30 altas, 0 cambios y 0 eliminaciones**. Ese plan fue aplicado después con autorización y produjo la V1 del 3 de octubre. No se ejecutó `destroy`. Los planes bajo `work/` son artefactos sensibles/efímeros y no deben tratarse como vigentes sin regenerarlos.

La vía de administración comprobada es Systems Manager Session Manager mediante `LabInstanceProfile`/`LabRole`. SSH permanece cerrado cuando `admin_cidr = ""`. Esos nombres pertenecen a Academy y no se presuponen en otra cuenta.

Academy confirmó que `LabInstanceProfile` existía y contenía `LabRole`, pero denegó `iam:GetPolicy`. En la EC2 desplegada se comprobó la lectura autorizada del secreto maestro administrado por RDS; el bootstrap lo usa en memoria y conserva el fallback manual sin eco, sin ampliar permisos.

Planes y estados pueden contener IDs, endpoints y ARN/metadata sensible. Deben quedar con permisos restrictivos bajo `work/`; nunca en Git, capturas o informes. Ningún secreto de aplicación entra en Terraform o `user_data`.
