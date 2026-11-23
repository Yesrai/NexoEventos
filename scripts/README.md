# Scripts de NexoEventos — mapa por finalidad

Índice de navegación: los scripts no se agrupan en subcarpetas todavía, por lo que conservan su ubicación y nombre actuales (los usan la integración continua, los documentos y otros scripts). Cada uno explica su propósito en la cabecera. Documentación general: [../docs/README.md](../docs/README.md).

> **Antes de ejecutar nada.** Algunos scripts de `cloud/`, `multicloud/` y `v2-ops/` actúan sobre infraestructura real (AWS, OCI, Azure). Léelos primero: varios de los que modifican algo exigen variables de confirmación o frases exactas. Los de «solo lectura» no cambian recursos, y los laboratorios y ensayos trabajan en Docker o en local.

## Scripts sueltos en esta carpeta

**Desarrollo local y datos de demostración**
[check-local.sh](check-local.sh), [docker-dev.sh](docker-dev.sh), [dev-bootstrap.py](dev-bootstrap.py), [db-migrate.sh](db-migrate.sh), [provision-database-roles.py](provision-database-roles.py), [seed-demo-catalog.py](seed-demo-catalog.py), [add-demo-images.py](add-demo-images.py), [download-demo-images.py](download-demo-images.py), [update-demo-dates.py](update-demo-dates.py), [update-demo-descriptions.py](update-demo-descriptions.py), [reset-local-password.py](reset-local-password.py).

**Respaldo y restauración en local**
[create-portable-backup.sh](create-portable-backup.sh), [test-restore-local.sh](test-restore-local.sh), [test-db-tls-verification.sh](test-db-tls-verification.sh).

**Pruebas en navegador y auditoría visual** (contra bases aisladas)
[audit-visual.sh](audit-visual.sh) y [audit-visual.mjs](audit-visual.mjs), [audit-typography.mjs](audit-typography.mjs), [capture-pages.mjs](capture-pages.mjs), [capture-venues.mjs](capture-venues.mjs), [e2e-organizer.sh](e2e-organizer.sh) y [e2e-organizer-flow.mjs](e2e-organizer-flow.mjs), [journey-buyer.sh](journey-buyer.sh) y [journey-buyer.mjs](journey-buyer.mjs), [verify-live-app.mjs](verify-live-app.mjs), [verify-seat-selection.mjs](verify-seat-selection.mjs).

**Despliegue AWS V1, Terraform y recuperación de cuenta**
[build-release.sh](build-release.sh), [ansible-aws.sh](ansible-aws.sh), [terraform-account.sh](terraform-account.sh), [reconstruct-academy-tfvars.py](reconstruct-academy-tfvars.py) y su prueba [test_reconstruct_academy_tfvars.py](test_reconstruct_academy_tfvars.py), [calculate-aws-budget.py](calculate-aws-budget.py), [prepare-recovery-ansible.py](prepare-recovery-ansible.py), [prepare-recovery-keys.sh](prepare-recovery-keys.sh), [prepare-recovery-runtime.py](prepare-recovery-runtime.py).

**Validación de observabilidad**
[validate-observability-config.py](validate-observability-config.py).

## Subcarpetas
| Carpeta | Finalidad | Alcance |
|---|---|---|
| [v2-ops/](v2-ops/) | Operación de AWS V2: estado, encendido, apagado y cambio vía Terraform, con guarda de seguridad y pruebas simuladas. Ver su [README](v2-ops/README.md). | Cloud (con confirmaciones) |
| [v2/](v2/) | Pruebas locales de V2 (configuración de Nginx para el balanceador, medición). | Local |
| [cloud/](cloud/) | Operación y pruebas sobre AWS: sesión de V1, auditorías de solo lectura, ensayos de restauración, pruebas de carga y de tolerancia a fallos, verificación de planes de Terraform. | Cloud (mayoría lectura) |
| [multicloud/](multicloud/) | Integración AWS–OCI: auditorías y viabilidad de solo lectura, preparación y verificación de la transferencia de respaldos, simulacro de restauración, verificador de recursos residuales, componentes de failover (lease, cambio de DNS, orquestador simulado) y sus pruebas. | Local y cloud preparado |
| [multicloud/oci-drill/](multicloud/oci-drill/) | Scripts del despliegue temporal de la aplicación en una VM de OCI. | Cloud |
| [multicloud/failover/](multicloud/failover/) | Orquestador y simulador de failover (locales). | Local |
| [multicloud/tests/](multicloud/tests/) | Pruebas de los componentes de failover. | Local |
| [observability/](observability/) | Zabbix, Grafana y Azure: configuración, verificación y exportación de métricas y evidencias. Ver su [README](observability/README.md). | Cloud y local |
| [repl-lab/](repl-lab/) | Laboratorio de replicación PostgreSQL y fencing en Docker local; incluye scripts `patch_*.py` históricos de iteraciones del laboratorio. | Docker local |
| [failover-lab/](failover-lab/) | Laboratorio de failover de aplicación en Docker local. | Docker local |
| [rehearsal/](rehearsal/) | Ensayo local y desechable de una actualización de la aplicación. | Local |
| [docs/](docs/) | Generación de documentos: presentación, conversión de HTML a Word, verificación del Entregable 2. | Local |

## Notas
- `__pycache__/` son cachés de Python regenerables: se pueden ignorar.
- Los laboratorios arrancan contenedores Docker con nombre de proyecto fijo. En `repl-lab/`, `lab.sh down` elimina también los volúmenes (usa `-v`): no ejecutarlo sin necesidad.
- Variables, claves y contraseñas no se guardan aquí: se leen de entorno o de ubicaciones protegidas fuera del repositorio.
