# NexoEventos AWS V2 (ALB + Auto Scaling) — preparación LOCAL

Raíz Terraform **separada** de V1 (`infra/aws`): estado propio y solo recursos nuevos; V1 se lee con `data` (VPC, subred pública a, tabla de rutas pública, SG de la base) y no se modifica. **No se ha ejecutado `plan`/`apply` ni creado nada.** Diseño: [propuesta-v2-alb-asg.md](../../docs/operacion/propuesta-v2-alb-asg.md).

| Archivo | Contenido |
|---|---|
| `network.tf` | subred pública b (otra zona), SG del ALB (80/443 públicos) y SG de las instancias (80 **solo desde el SG del ALB**, sin SSH), regla aditiva 5432 hacia la RDS |
| `alb.tf` | ALB, target group (`least_outstanding_requests`, health check `/healthz`, sin afinidad), listener 443 (TLS 1.2/1.3) y 80→443 |
| `compute.tf` | launch template (AMI dorada, IMDSv2, EBS cifrado, `LabInstanceProfile`), ASG 2–3 en dos zonas con health check ELB y política de seguimiento de CPU (opcional: solicitudes por instancia) |
| `observability.tf` | panel de CloudWatch (instancias sanas, solicitudes/latencia/5xx, CPU, RDS) |
| `tests/check_security.py` | comprobaciones estáticas de las reglas de seguridad |

Fuera de Terraform (con autorización y por Session Manager, el valor nunca sale de AWS): `deploy/v2/create-shared-secret-on-v1.sh` (secreto compartido), `deploy/v2/import-acm-certificate-on-v1.sh` (certificado) y la AMI dorada. Arranque: `deploy/v2/bootstrap-instance.sh.tftpl` (lee el secreto con el rol de la instancia).
Uso futuro: `terraform init` con estado en `work/terraform-state/academy-v2`, `terraform plan -var-file=…` (con `ami_id` y `certificate_arn`) y revisar antes de cualquier `apply`.

Validación local realizada: `terraform fmt`, `terraform validate`, `python3 infra/aws-v2/tests/check_security.py`, `scripts/v2/test-nginx-alb.sh` (Nginx en Docker: sintaxis, health check, IP real), `scripts/v2/test_measure.py`, `ansible-playbook --syntax-check` y las pruebas del backend.
