# Preparación AWS, Terraform y Ansible — 7 de octubre de 2026

## Resultado

La primera revisión fue local; después se renovaron las credenciales y se completaron lecturas AWS. No se arrancó RDS, no se aplicó Terraform y no se desplegó la aplicación.

## Credenciales y acceso

- AWS CLI obtiene `nexoeventos-lab` de los archivos compartidos de configuración/credenciales, ambos con modo `0600`.
- No había variables `AWS_*` de credenciales o perfil sustituyendo esa fuente.
- El bloque contiene access key, secret key y session token, pero su archivo no se actualiza desde el 2 de octubre; no se mostraron valores.
- Hora del sistema coherente. Una sola llamada STS aislada devolvió `InvalidClientTokenId`; no se repitió.
- Tras renovar el bloque, STS validó cuenta/región. EC2 estaba `running` por Academy y RDS `stopped`. Cost Explorer mostró USD 0.8180416576 del 1–7 de octubre; Budgets no expuso el presupuesto Academy por API.

## Terraform

- El wrapper ahora exige `work/terraform-state/<entorno>-current/terraform.tfstate`; cancela si falta y evita crear un estado paralelo vacío.
- `academy.tfvars` se reconstruyó desde el estado real serial 32 y permanece ignorado/modo `0600`.
- AMI dinámica sustituida por la AMI exacta ya desplegada, leída del estado.
- `max_allocated_storage = 0` desactiva explícitamente el autoescalado; al habilitarlo se exige al menos 10 % de margen y máximo 100 GiB.
- ciclo de vida S3 alineado a `backups/database/`; el bucket permanece en el estado.
- `terraform fmt` y `terraform validate`: aprobados. El refresh autenticado mostró parcialmente 0 altas/1 cambio/0 bajas y luego falló por la SCP Object Lock. No existe plan aplicable; S3 no se retiró del estado.

## Ansible

Se prepararon inventario dinámico EC2, conexión `amazon.aws.aws_ssm`, artefacto por commit, releases `current`/`previous`, configuración Nginx/systemd, health check y reversión. Los secretos, claves QR y certificados quedan fuera del artefacto. La sintaxis de ambos playbooks fue validada localmente.

Session Manager Plugin ARM64 1.2.835.0 quedó instalado por el procedimiento oficial en `~/.local`. Sesión directa y `ansible.builtin.ping` funcionaron sin SSH. Los objetos temporales S3 se limpiaron incluyendo versiones/marcadores; los respaldos no se tocaron.

## Pruebas locales

- Terraform `fmt` y `validate`: OK.
- Bash `-n` para wrappers/artefacto/validador: OK.
- Ansible `--syntax-check` para deploy y rollback: OK.
- Empaquetador versionado: probado con Git compatible y Node 24 efectivo; genera archivo/hash protegidos y excluye `work/`, estados, planes y secretos (conserva únicamente plantillas `.env.example`).
- Frontend: 15 pruebas aprobadas y build Vite (49 módulos) aprobado.
- Backend: 19 pruebas aprobadas; una advertencia de deprecación de Starlette/httpx pendiente, sin fallo.

## Próxima acción concreta

Revisar [el plan previo](../docs/operacion/plan-actualizacion-aws-2026-10-07.md). Terraform queda bloqueado por refresh incompleto. Para la aplicación: respaldo preactualización, RDS activa, migraciones `0004`/`0005`, catálogo ficticio, release versionada, prueba pública y apagado.
