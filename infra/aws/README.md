# AWS V1

Terraform describe una V1 de demostración en `us-east-1` sin alta disponibilidad:

- VPC `10.20.0.0/16`.
- Una subred pública `10.20.1.0/24` para una EC2 `t3.small` con Nginx, frontend compilado y FastAPI.
- Dos subredes privadas de datos, `10.20.21.0/24` y `10.20.22.0/24`, necesarias para el DB subnet group.
- RDS PostgreSQL `db.t3.micro`, Single-AZ, 20 GiB gp2, sin acceso público.
- S3 privado, versionado, cifrado SSE-S3 y ciclo de vida de respaldos.
- Dos grupos de logs y una alarma básica de CPU en CloudWatch.

No incluye NAT Gateway, balanceador, réplica ni Multi-AZ. El puerto 5432 solo acepta tráfico desde el security group de la aplicación. Los puertos 80/443 son públicos; SSH se mantiene cerrado salvo que se proporcione temporalmente un `/32` mediante un archivo local ignorado.

## Estado de validación

```bash
terraform -chdir=infra/aws init -backend=false
terraform fmt -check -recursive infra/aws
terraform -chdir=infra/aws validate
```

La validación local es satisfactoria. `terraform plan` está pendiente porque la CLI no tiene credenciales autorizadas. Un `validate` correcto no demuestra permisos para crear recursos ni disponibilidad de cuotas.

Antes de planificar, copiar `terraform.tfvars.example` a un archivo local `.tfvars`, confirmar que `LabInstanceProfile` existe y revisar que Learner Lab esté activo. Guardar cualquier plan solo bajo `work/` o con extensión `.tfplan`; ambos están excluidos de Git.

No ejecutar `apply` ni `destroy` sin aprobación explícita posterior del plan y su costo.
