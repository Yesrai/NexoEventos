# NexoEventos AWS V2 (ALB + Auto Scaling) — preparación LOCAL

Raíz Terraform **separada** de V1 (`infra/aws`): estado propio y solo recursos nuevos; V1 se lee con `data` (VPC, subred pública a, tabla de rutas pública, SG de la base) y no se modifica. **No se ha ejecutado `plan`/`apply` ni creado nada.** Diseño: [propuesta-v2-alb-asg.md](../../docs/operacion/propuesta-v2-alb-asg.md).

| Archivo | Contenido |
|---|---|
| `network.tf` | subred pública b (otra zona), SG del ALB (80/443 públicos) y SG de las instancias (80 **solo desde el SG del ALB**, sin SSH), regla aditiva 5432 hacia la RDS |
| `alb.tf` | ALB, target group (`least_outstanding_requests`, health check `/livez` (liveness sin base de datos), sin afinidad), listener 443 (TLS 1.2/1.3) y 80→443 |
| `compute.tf` | launch template (AMI dorada, IMDSv2, EBS cifrado, `LabInstanceProfile`), ASG 2–3 en dos zonas con health check ELB y política de seguimiento de CPU (opcional: solicitudes por instancia) |
| `observability.tf` | panel de CloudWatch (instancias sanas, solicitudes/latencia/5xx, CPU, RDS) |
| `tests/check_security.py` | comprobaciones estáticas de las reglas de seguridad |

Fuera de Terraform (con autorización y por Session Manager, el valor nunca sale de AWS): `deploy/v2/create-shared-secret-on-v1.sh` (secreto compartido), `deploy/v2/import-acm-certificate-on-v1.sh` (certificado) y la AMI dorada. Arranque: `deploy/v2/bootstrap-instance.sh.tftpl` (lee el secreto con el rol de la instancia).
Uso futuro: `terraform init` con estado en `work/terraform-state/academy-v2`, `terraform plan -var-file=…` (con `ami_id` y `certificate_arn`) y revisar antes de cualquier `apply`.

Validación local realizada: `terraform fmt`, `terraform validate`, `python3 infra/aws-v2/tests/check_security.py`, `scripts/v2/test-nginx-alb.sh` (Nginx en Docker: sintaxis, health check, IP real), `scripts/v2/test_measure.py`, `ansible-playbook --syntax-check` y las pruebas del backend.

## Secuencia de ejecución real (cada paso con autorización propia)
1. **Plan de lectura (hecho):** `terraform plan` con valores provisionales de `ami_id` y `certificate_arn` → 21 recursos nuevos, 0 cambios, 0 destrucciones (`work/terraform-envs/academy-v2.plan-provisional.tfvars`, ignorado por Git; estado en `work/terraform-state/academy-v2`).
2. **Certificado y secreto** (arranca solo la EC2 de V1, ~10 min): `scripts/cloud/v2-prepare.sh v1-ec2-start` → `import-cert` → `create-secret` → `v1-ec2-stop`.
3. **AMI dorada** (instancia temporal, ~45 min): `v2-prepare.sh builder-launch` → `scripts/ansible-aws.sh bake` (rol `nexoeventos` en modo `nexoeventos_bake` + `nexoeventos_edge: alb`: sin secretos, sin migraciones, API sin arrancar) → `builder-image` → `builder-delete`.
4. **Plan real** con `ami_id` (`work/operacion/v2-ami-id`) y `certificate_arn` (`work/operacion/v2-certificate-arn`) y revisión.
5. **`terraform apply`** solo de esta raíz; después verificación funcional y medición.
