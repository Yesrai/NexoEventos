# EV09 — Terraform

Evidencia obtenida el 2 de octubre de 2026:

- `terraform fmt -check -recursive infra/aws`: correcto.
- `terraform validate`: correcto.
- `terraform plan` vigente autenticado en `us-east-1`: 30 altas, 0 cambios y 0 eliminaciones, sin advertencias.
- Plan binario: `work/terraform-plans/academy.tfplan`, ignorado por Git y modo `0600`.
- No se ejecutó `apply` ni `destroy`.

El plan puede contener ID de cuenta, nombres derivados, endpoint previsto y metadata marcada sensible de RDS. No se adjunta ni se copia a capturas. La evidencia transportable es el resumen sanitizado anterior. El plan histórico de `25a12c1` no se reutilizó.

Diagnóstico del bloqueo: no había variables `AWS_*` ni rutas de archivos alternativas sustituyendo el perfil. La access key y secret key provenían del perfil explícito; el session token había quedado truncado al copiarlo desde la representación accesible. Se recuperó el token completo de la misma sesión, se guardó junto con los otros dos componentes en archivos temporales externos al repositorio (`0700`/`0600`) y STS respondió correctamente con el entorno aislado. Hora comprobada: 2-oct-2026 15:06, UTC-05.
