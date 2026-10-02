# EV09 — Terraform

Evidencia obtenida el 2 de octubre de 2026:

- `terraform fmt -check -recursive infra/aws`: correcto.
- `terraform validate`: correcto.
- `terraform plan` histórico de `25a12c1` autenticado en `us-east-1`: 30 altas, 0 cambios y 0 eliminaciones.
- Plan binario: `work/aws-v1.tfplan`, ignorado por Git y modo `0600`.
- No se ejecutó `apply` ni `destroy`.

El plan puede contener ID de cuenta, nombres derivados, endpoint previsto y metadata marcada sensible de RDS. No se adjunta ni se copia a capturas. La evidencia transportable es el resumen sanitizado anterior. Después de `25a12c1` se habilitó snapshot final y se añadieron identidad/estado por cuenta, por lo que el plan 30/0/0 queda como evidencia histórica y no debe aplicarse.

El 2 de octubre se inició una sesión nueva y la consola AWS abrió correctamente en `us-east-1`, pero STS rechazó el bloque CLI recién emitido con `InvalidClientTokenId`. El intento de plan actual falló durante la validación de credenciales del proveedor y no produjo binario. `fmt` y `validate` sí pasaron. Se necesita otra credencial temporal que supere STS antes de generar evidencia vigente.
