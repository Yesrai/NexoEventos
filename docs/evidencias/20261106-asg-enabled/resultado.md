# Variable `asg_enabled` en infra/aws-v2 (6-nov-2026; SOLO archivos locales y planes; nada aplicado)

Estado de AWS verificado el 6-nov 13:54 (hora de Perú): ASG V2 en 0/0/3 sin instancias; ALB activo; RDS `available` (Multi-AZ); EC2 de V1 `running`; 10 alarmas propias en `OK` más 2 de seguimiento del ASG en `INSUFFICIENT_DATA` (normal con 0 instancias); sin NAT ni IP elásticas propias (las 2 direcciones que lista `describe-addresses` son del ALB, `ServiceManaged=alb`); 1 volumen (V1).

Cambio: `variables.tf` (variable `asg_enabled`, por defecto `true`) y `compute.tf` (mínima y deseada = valor normal si `true`, 0 si `false`; máxima sin cambios; la condición «al menos 2 instancias» solo aplica con `true`).

Planes (sin `apply`, con `-lock=false`, estado de V2 con la misma huella antes y después; copia de seguridad en `work/terraform-state/academy-v2/terraform.tfstate.pre-asg-enabled-20261106`):
- Antes del cambio (código antiguo): 0 crear, 1 modificar (ASG 0→2), 0 destruir — la deriva que motivó el cambio.
- `asg_enabled=false` (estado real de AWS): **No changes**.
- `asg_enabled=true`: 0 crear, 1 modificar (solo `desired_capacity` 0→2 y `min_size` 0→2 del ASG), 0 destruir; 26 recursos sin cambios.
- `asg_enabled=true` con `asg_min=1`: falla la condición (esperado). `asg_enabled=false` con `asg_min=1`: sin cambios.
- `terraform fmt` sin diferencias; `terraform validate` correcto; `tests/check_security.py` sin fallos.
