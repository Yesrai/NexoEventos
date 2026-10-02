# EV09 — Terraform

Evidencia obtenida el 2 de octubre de 2026:

- `terraform fmt -check -recursive infra/aws`: correcto.
- `terraform validate`: correcto.
- `terraform plan` autenticado en `us-east-1`: 30 altas, 0 cambios y 0 eliminaciones.
- Plan binario: `work/aws-v1.tfplan`, ignorado por Git y modo `0600`.
- No se ejecutó `apply` ni `destroy`.

El plan puede contener ID de cuenta, nombres derivados, endpoint previsto y metadata marcada sensible de RDS. No se adjunta ni se copia a capturas. La evidencia transportable es el resumen sanitizado anterior. Sigue pendiente, solo después de una aprobación explícita de despliegue, demostrar recursos reales y un plan post-aplicación sin cambios.
