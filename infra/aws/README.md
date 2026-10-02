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

`terraform fmt`, `validate` y un `plan` autenticado se ejecutaron satisfactoriamente el 2 de octubre de 2026 con el perfil temporal `nexoeventos-lab`. El plan propone **30 altas, 0 cambios y 0 eliminaciones**. El binario permanece solo en `work/aws-v1.tfplan`, ignorado y con modo `0600`; no es evidencia de que cada alta será autorizada al aplicar ni de que haya cuota disponible.

La lectura confirmó que `LabInstanceProfile` existe y contiene `LabRole`. Learner Lab denegó `iam:GetPolicy`, de modo que el contenido efectivo de sus políticas y el acceso al secreto permanecen sin verificar. Guardar cualquier plan solo bajo `work/` o con extensión `.tfplan`; ambos están excluidos de Git.

No hay `user_data`. Terraform solicita a RDS administrar el secreto maestro, pero las credenciales limitadas de la aplicación y las claves de sesión/QR deben inyectarse después del despliegue sin pasar por variables, plan o estado. Hasta verificar Secrets Manager, la alternativa V1 es una carga interactiva sin eco a `/etc/nexoeventos/backend.env`, propiedad `root:root` y modo `0600`; nunca usar la cuenta maestra como cuenta de ejecución.

No ejecutar `apply` ni `destroy` sin aprobación explícita posterior del plan y su costo.
