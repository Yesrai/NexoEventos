# Fase 2 — plan final de las alarmas de V1 (3-nov-2026) — resumen saneado
Perfil `nexoeventos-lab`, región `us-east-1`. Plan contra el **estado real** (serie 36; la misma antes y después, con bloqueo), sin `apply`; plan guardado con permisos `0600` fuera de Git. IDs, direcciones y ARN omitidos; sin salidas crudas.
| Plan | Resultado |
|---|---|
| Final, dirigido a las alarmas (`enable_alarms=true`, `public_subnet_auto_public_ip=true`) | **7 a crear, 1 a cambiar, 0 a destruir**; verificado con `terraform show -json` y `scripts/cloud/verificar-plan-alarmas.py`: **CORRECTO** (sin cambios en subred, S3, RDS ni EC2; sin dirección de correo en el plan) |
| Completo sin refresh (configuración frente al estado) | 0 a crear, 2 a cambiar, ajenos a las alarmas: lifecycle de S3 (prefijo y 7 → 90 días) y subred |
| Completo con refresh | Falla por la denegación de Academy `s3:GetBucketObjectLockConfiguration` (limitación documentada) |
Diferencia con el plan previo (8 + 1): el correo salió de Terraform (7 + 1), para que no quede en el estado ni en un plan guardado. Observación informativa: la IP pública de la EC2 cambió fuera de Terraform al reiniciarse el laboratorio.
