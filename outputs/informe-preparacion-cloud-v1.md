# Informe actualizado de preparación cloud V1 — NexoEventos

Fecha: 2 de octubre de 2026. Base revisada: commit `4ad752b`. No se ejecutó `terraform apply` ni `destroy` y no se creó, modificó, detuvo o eliminó ningún recurso cloud durante esta actualización.

## Ficha ejecutiva

| Tema | Resultado actual |
|---|---|
| Arquitectura | una EC2 `t3.small` AL2023 con Nginx/React/FastAPI; RDS PostgreSQL `db.t3.micro` privado Single-AZ; S3 privado; CloudWatch; sin NAT/ALB/Multi-AZ |
| Terraform | `fmt` y `validate` correctos; plan 30/0/0 de `25a12c1` histórico y no reutilizado; el intento nuevo se bloqueó en STS con `InvalidClientTokenId` y no produjo plan |
| SO e instalación | instalador AL2023 con DNF, Python 3.11 aislado, Node 24.21.0 verificado, dependencias/proveedor fijados; ejecución sobre EC2 real pendiente |
| Secretos | carga interactiva sin eco, archivos root-only, proceso sin privilegios; maestro RDS no se guarda; permiso de lectura del secreto se probará con rol real |
| DNS/TLS | `nexoeventos-demo.duckdns.org` confirmado por la usuaria; DNS hacia EC2, certificado y HTTPS todavía no operativos |
| Costo hasta 26 nov | subtotal previsto USD 10.719; margen USD 3.000; techo USD 13.719, suponiendo 37 h activas y persistencia desde 2 oct 15:00 |
| Recuperación | restore local, snapshot final, backup portable cifrado y procedimiento entre cuentas preparados; pruebas cloud/copia externa/migración real pendientes |

El FQDN ya está decidido: **`nexoeventos-demo.duckdns.org`**. El token no se aporta por chat; como quedó visible durante una inspección de accesibilidad, debe regenerarse personalmente otra vez antes de introducirlo en el servidor mediante prompt sin eco.

## Arquitectura desplegable

- VPC `10.20.0.0/16`; pública `10.20.1.0/24`; datos privadas `10.20.21.0/24` y `10.20.22.0/24` en dos AZ.
- EC2 Amazon Linux 2023 `x86_64`, `t3.small`, EBS gp3 20 GiB cifrado, IMDSv2, IPv4 dinámica y perfil IAM definido por entorno.
- Nginx sirve `frontend/dist`; FastAPI/Uvicorn escucha en loopback y corre como usuario `nexoeventos`, sin shell/sudo.
- RDS PostgreSQL `db.t3.micro`, Single-AZ, gp2 20 GiB cifrado, no público, backup 7 días y snapshot final obligatorio.
- S3 bloqueado al público, SSE-S3, versionado/lifecycle; dos log groups de 7 días y alarma CPU.
- Sin NAT Gateway, balanceador, Auto Scaling, réplica ni Multi-AZ para preservar crédito.

El SG de RDS acepta 5432 exclusivamente desde el SG de EC2. 443 es público; 80 queda para redirección/ACME. SSH está cerrado por defecto (`admin_cidr = ""`). La administración prevista es Systems Manager Session Manager con `LabInstanceProfile`/`LabRole`, salida HTTPS y el agente incluido en la AMI oficial AL2023. Academy documenta la vía, pero su funcionamiento real solo podrá probarse cuando exista la instancia.

## Amazon Linux 2023 y reproducibilidad

Se eliminó cualquier ambigüedad Ubuntu. El instalador comprueba `ID=amzn` y `VERSION_ID=2023`, usa DNF e instala Nginx, Python 3.11, cliente PostgreSQL y AWS CLI v2. No repunta `/usr/bin/python3`. Node 24.21.0 se instala desde el archivo oficial con SHA-256 fijado. Backend usa `requirements-production.txt`; frontend usa versiones exactas y lock; Terraform fija AWS provider 6.67.0.

El script instala archivos y unidades pero no inicia FastAPI hasta que existan secretos/DNS. La compatibilidad observada localmente incluye sintaxis, compilación y tests. La prueba definitiva de nombres de paquetes, systemd, SELinux/contextos y servicio en la AMI real solo puede ejecutarse después de un `apply` aprobado.

## Terraform por cuenta

`expected_account_id`, región, entorno, tamaños, perfil IAM y snapshot se declaran por entorno en tfvars ignorados. `scripts/terraform-account.sh` consulta STS, compara sin imprimir el ID y separa:

- `work/terraform/<entorno>` — caché/directorio de trabajo;
- `work/terraform-state/<entorno>/terraform.tfstate` — estado independiente;
- `work/terraform-plans/<entorno>.tfplan` — plan protegido.

No se reutiliza el estado de Academy en otra cuenta. El destino debe aportar su propio perfil/rol: `LabRole` y `LabInstanceProfile` no se asumen. También se vuelven a verificar SCP/IAM, cuotas, regiones, tipos disponibles, costos y financiación. No se asumen créditos nuevos.

## Secretos y base de datos

`bootstrap-rds-secrets.sh` obtiene endpoint/ARN mediante lectura AWS, prueba `GetSecretValue` y usa la credencial maestra solo en memoria para crear:

- `nexoeventos_owner`: `NOLOGIN`, propietario;
- `nexoeventos_migrator`: login exclusivo Alembic, miembro del owner;
- `nexoeventos_app`: login limitado para FastAPI.

Las contraseñas migrator/app son distintas. `/etc/nexoeventos/migration.env` y `backend.env` son `root:root 0600`; solo backend.env lo consume systemd antes de bajar privilegios. QR/hash se cargan sin eco y se respaldan separadas. Si el rol no lee el secreto maestro, el script lo informa, no eleva permisos y ofrece entrada manual sin eco. El archivo de aplicación no sustituye ese permiso.

## DuckDNS, HTTPS y ACM

La usuaria confirmó que `nexoeventos-demo.duckdns.org` quedó agregado en DuckDNS. Esa confirmación no demuestra resolución hacia AWS ni HTTPS, porque todavía no existe una IP pública de NexoEventos. El token visto durante la inspección del navegador debe invalidarse y regenerarse personalmente justo antes del despliegue.

El token queda en `/etc/nexoeventos/duckdns.env` root-only; un timer lo usa por entrada estándar para actualizar la IPv4 cada cinco minutos. Certbot 5.8.0 ejecuta ACME/Let's Encrypt y renueva dos veces al día mediante timer. No se emitió certificado.

Corrección técnica: ACM ya permite certificados públicos exportables y puede desplegarse en EC2. Desde febrero de 2026, el certificado exportable público predeterminado usa 198 días y cobra por nombre. Para esta V1 se prefiere Let's Encrypt gratuito; no se afirma que ACM requiera obligatoriamente ALB/CloudFront.

## Presupuesto corregido

Treinta días exactos son 720 horas:

| Componente | 720 h/30 días |
|---|---:|
| EC2 `t3.small` | USD 14.976 |
| RDS `db.t3.micro` | USD 12.960 |
| IPv4 pública | USD 3.600 |
| EBS 20 GiB | USD 1.600 |
| RDS storage 20 GiB | USD 2.300 |
| secreto + S3 + logs almacenados + alarma | USD 0.529 |
| ingestión de logs supuesta | USD 0.500 |
| **total sin margen** | **USD 36.465** |

Forecast desde el escenario más temprano 2-oct-2026 15:00 hasta 26-nov-2026 23:59: 1,328.983 horas persistentes y 37 horas activas. Ejecución USD 1.621; almacenamiento/servicios USD 8.175; variable base USD 0.923; subtotal USD 10.719; margen USD 3.000; **techo USD 13.719**. No es costo observado: no existe fecha real de creación sin `apply`.

El presupuesto Academy indicado es USD 50; el último uso observado fue USD 0.10 y puede retrasarse. Se revisa manualmente a USD 30 y USD 40 para decidir antes de agotarlo, sin presentarlo como límite automático.

## RDS, snapshot y recuperación

Consultar RDS o repetir la orden de detención no reinicia los siete días. Antes del límite hay que arrancar, esperar `available`, comprobar, detener y esperar `stopped`; se registran ambas transiciones. No se añadieron automatizaciones porque sus permisos no están comprobados.

Terraform ahora exige snapshot final y propone `nexoeventos-academy-final-20261126`; debe verificarse unicidad antes de una eventual eliminación. Escenario conservador después de eliminar RDS: 20 GiB × USD 0.095 = USD 1.90/mes. No se ejecutó `destroy`.

`test-restore-local.sh` verifica restauración aislada y descifrado QR. `create-portable-backup.sh` produce un dump+fuentes+checksums cifrados; todavía debe copiarse a un destino protegido fuera de la cuenta. Las claves QR/hash y la contraseña del paquete viajan por canales separados.

La migración entre cuentas queda pendiente. El procedimiento incluye destino aislado, restore de prueba, roles/reservas/QR, pausa final de escrituras, backup final, restore, DNS/HTTPS y rollback al origen sin escrituras simultáneas.

## AWS Academy observado anteriormente

Learner Lab 184558 documentó regiones `us-east-1`/`us-west-2`, sesiones de 4 h, tamaños EC2 nano–large, RDS nano–medium, EBS/RDS hasta 100 GiB y roles precreados. El inventario no encontró recursos NexoEventos; había tres log groups ajenos con solo 6,187 bytes. Listar servicios no demostró creación. `iam:GetPolicy` y `pricing:GetProducts` fueron denegados. Los permisos de creación, cuota y lectura del secreto siguen sin probarse.

## Verificaciones ejecutadas en esta actualización

- Node efectivo `v24.21.0`; frontend: 1 test aprobado y build Vite correcto (44 módulos).
- Backend/PostgreSQL: 16 tests aprobados; permanece una advertencia no bloqueante de compatibilidad futura Starlette/httpx.
- Restauración aislada: 3 eventos, 1 reserva y 1 entrada; token cifrado recuperable con la clave separada.
- Terraform AWS: `fmt` y `validate` satisfactorios. Se inició una sesión Academy nueva y la consola web abrió en `us-east-1`; STS rechazó las credenciales CLI recién emitidas con `InvalidClientTokenId`, así que el proveedor no calculó cambios ni creó un plan.
- Scripts shell: análisis de sintaxis correcto; Python: compilación correcta. `shellcheck` no está instalado y no se añadió.
- Escaneo básico: ninguna firma de clave AWS/PEM en archivos versionados; `.env`, estados y planes continúan ignorados.

## Bloqueos y decisiones restantes

1. Regenerar personalmente el token DuckDNS antes de instalarlo, sin compartirlo por chat.
2. Obtener de Academy un bloque CLI que supere `aws sts get-caller-identity`; el Lab y la consola web están activos, pero la credencial emitida actualmente es inválida.
3. Generar el plan nuevo, revisar recursos/costo y aprobar `apply` explícitamente.
4. Tras desplegar, comprobar perfil de instancia → secreto maestro, instalación AL2023 real, DNS y HTTPS.
5. Elegir el destino protegido fuera de la cuenta para el backup cifrado.

NexoEventos continúa como implementación académica local preparada para despliegue; no está desplegado ni listo para producción.
