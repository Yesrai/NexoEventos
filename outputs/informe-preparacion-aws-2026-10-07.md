# Preparación AWS, Terraform y Ansible — 7 de octubre de 2026

## Resultado

Se avanzó únicamente en local. No se inició el laboratorio, no se arrancó EC2/RDS, no se creó ni modificó infraestructura y no se ejecutó `terraform plan/apply/destroy`.

## Credenciales y acceso

- AWS CLI obtiene `nexoeventos-lab` de los archivos compartidos de configuración/credenciales, ambos con modo `0600`.
- No había variables `AWS_*` de credenciales o perfil sustituyendo esa fuente.
- El bloque contiene access key, secret key y session token, pero su archivo no se actualiza desde el 2 de octubre; no se mostraron valores.
- Hora del sistema coherente. Una sola llamada STS aislada devolvió `InvalidClientTokenId`; no se repitió.
- Por ello no se verificaron hoy cuenta, inventario, estado EC2/RDS, presupuesto ni consumo. El último estado real sigue siendo el observado el 4 de octubre y no se presume vigente.

## Terraform

- El wrapper ahora exige `work/terraform-state/<entorno>-current/terraform.tfstate`; cancela si falta y evita crear un estado paralelo vacío.
- `academy.tfvars` se reconstruyó desde el estado real serial 32 y permanece ignorado/modo `0600`.
- AMI dinámica sustituida por la AMI exacta ya desplegada, leída del estado.
- `max_allocated_storage = 0` desactiva explícitamente el autoescalado; al habilitarlo se exige al menos 10 % de margen y máximo 100 GiB.
- ciclo de vida S3 alineado a `backups/database/`; el bucket permanece en el estado.
- `terraform fmt` y `terraform validate`: aprobados. No existe plan vigente por el bloqueo STS. Object Lock puede volver a impedir un refresh completo y se documentará, no se ocultará retirando S3 del estado.

## Ansible

Se prepararon inventario dinámico EC2, conexión `amazon.aws.aws_ssm`, artefacto por commit, releases `current`/`previous`, configuración Nginx/systemd, health check y reversión. Los secretos, claves QR y certificados quedan fuera del artefacto. La sintaxis de ambos playbooks fue validada localmente.

Bloqueo real: falta el ejecutable Session Manager Plugin en el Mac. La colección `amazon.aws` y sus bibliotecas sí están disponibles. No se instaló ni se abrió SSH. La ruta se considera preparada, no probada en AWS.

## Pruebas locales

- Terraform `fmt` y `validate`: OK.
- Bash `-n` para wrappers/artefacto/validador: OK.
- Ansible `--syntax-check` para deploy y rollback: OK.
- Empaquetador versionado: probado; evita el Git incompatible de `/usr/local/bin`, genera archivo/hash protegidos y excluye `work/`, estados, planes y secretos.
- Frontend: 15 pruebas aprobadas y build Vite (49 módulos) aprobado.
- Backend: 19 pruebas aprobadas; una advertencia de deprecación de Starlette/httpx pendiente, sin fallo.

## Próxima acción concreta

Con `Lab environment ready`, ejecutar personalmente `work/enter-aws-academy-credentials.sh`. Después: una comprobación STS, inventario/consumo, `terraform plan` con refresh y preflight Ansible. Antes del despliegue de aplicación se debe instalar/verificar Session Manager Plugin en una tarea autorizada. Si STS rechaza un bloque recién emitido, detenerse y actualizar el reporte a soporte sin regeneraciones repetidas.
