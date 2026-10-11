# Terraform del ensayo de recuperación completa

Root deliberadamente separado de `infra/aws`: nunca reutiliza el estado de V1. Reutiliza por lectura la VPC, la subred pública y el DB subnet group existentes; crea una EC2, una RDS PITR y dos SG temporales, todos etiquetados con `Purpose=full-recovery-drill` y un `RunId` único.

No contiene recursos DNS, certificados, secretos, SSH, NAT, ALB ni cambios en el entorno principal. Expone como salida un hostname efímero `sslip.io` derivado de la IPv4 temporal; no registra ni modifica el dominio principal.

El estado y el plan pueden contener endpoint, IP y metadatos sensibles. Deben vivir únicamente en `work/terraform-envs/` con permisos `0600`:

```bash
terraform -chdir=infra/aws-recovery init \
  -backend-config="path=$PWD/work/terraform-envs/recovery-AAAAMMDDtHHMM.tfstate"
terraform -chdir=infra/aws-recovery plan \
  -var-file="$PWD/work/terraform-envs/recovery-AAAAMMDDtHHMM.tfvars" \
  -out="$PWD/work/terraform-envs/recovery-AAAAMMDDtHHMM.tfplan"
```

No ejecutar `apply` ni `destroy` hasta revisar el plan/costo y autorizar el ensayo. La restauración usa `use_latest_restorable_time`; el inicio T0 de recuperación completa se registra **antes** del `apply`. Al terminar, `destroy` solo se ejecutará desde este estado separado y después de comprobar sus etiquetas/RunId.
