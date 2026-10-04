# EV09 — Terraform

Evidencia obtenida el 2 de octubre de 2026:

- `terraform fmt -check -recursive infra/aws`: correcto.
- `terraform validate`: correcto.
- `terraform plan` vigente autenticado en `us-east-1`: 30 altas, 0 cambios y 0 eliminaciones, sin advertencias.
- Plan binario: `work/terraform-plans/academy.tfplan`, ignorado por Git y modo `0600`.
- No se ejecutó `apply` ni `destroy`.

El plan puede contener ID de cuenta, nombres derivados, endpoint previsto y metadata marcada sensible de RDS. No se adjunta ni se copia a capturas. La evidencia transportable es el resumen sanitizado anterior. El plan histórico de `25a12c1` no se reutilizó.

Diagnóstico del bloqueo: no había variables `AWS_*` ni rutas de archivos alternativas sustituyendo el perfil. La access key y secret key provenían del perfil explícito; el session token había quedado truncado al copiarlo desde la representación accesible. Se recuperó el token completo de la misma sesión, se guardó junto con los otros dos componentes en archivos temporales externos al repositorio (`0700`/`0600`) y STS respondió correctamente con el entorno aislado. Hora comprobada: 2-oct-2026 15:06, UTC-05.

## Después del despliegue (3 de octubre de 2026)

- El estado protegido contiene los 30 recursos administrados del plan (`outputs/informe-despliegue-aws-2026-10-03.md`). El bucket se completó con un plan dirigido porque el laboratorio deniega `s3:GetBucketObjectLockConfiguration`.
- **Falta la evidencia I01:** un `plan` posterior con *No changes*. Hoy un refresh general puede fallar por la lectura S3, y la AMI `most_recent` podría proponer reemplazar la EC2. Las correcciones propuestas, sin aplicar, están en `docs/operacion/terraform-advertencias.md`.
- Ningún plan o estado se adjunta: pueden contener IDs, endpoints y metadata sensible.
