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

El wrapper consulta STS y cancela si la identidad difiere de `expected_account_id`; no muestra el ID. Mantiene estado, caché y plan separados por nombre de entorno bajo `work/`, ignorado por Git. El subcomando `apply` exige además `NEXO_ALLOW_APPLY=YES` y un plan guardado, pero **no está autorizado en esta etapa**.

No se debe reutilizar el estado Academy para otra cuenta. Una cuenta normal necesita su propio perfil IAM autorizado; no se presupone que `LabRole` o `LabInstanceProfile` existan. También deben reevaluarse permisos, SCP, cuotas, regiones, costos y financiación.

## Estado de comprobación

El plan autenticado histórico del commit `25a12c1` fue 30 altas, 0 cambios y 0 eliminaciones. Después se añadieron controles de cuenta, snapshot final y portabilidad; por ello ese binario ya no debe aplicarse. El intento de plan actual recibió denegaciones explícitas `voc-cancel-cred` al leer AMI, zonas y perfil: la sesión del laboratorio está cancelada. El archivo incompleto se eliminó. `fmt` y `validate` actuales sí pasaron; hay que iniciar otra sesión Academy y descargar credenciales nuevas antes de regenerar el plan.

Academy confirmó que `LabInstanceProfile` existía y contenía `LabRole`, pero denegó `iam:GetPolicy`. La lectura del secreto maestro administrado por RDS no puede probarse hasta que exista: `deploy/bootstrap-rds-secrets.sh` la intenta en la EC2 y falla de forma cerrada a entrada manual sin eco, sin ampliar permisos.

Planes y estados pueden contener IDs, endpoints y ARN/metadata sensible. Deben quedar con permisos restrictivos bajo `work/`; nunca en Git, capturas o informes. Ningún secreto de aplicación entra en Terraform o `user_data`.
