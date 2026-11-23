# Documentación de NexoEventos — mapa de navegación

Este índice solo orienta; el contenido está en cada documento. Estado general del proyecto: [estado-proyecto.md](estado-proyecto.md) y [proximos-pasos.md](proximos-pasos.md). Visión de conjunto del repositorio: [../README.md](../README.md) y [../PROJECT_STATUS.md](../PROJECT_STATUS.md).

> **Importante.** Las carpetas de evidencias están ligadas a manifiestos SHA-256 y son material académico. No se mueven, renombran ni editan: cualquier cambio invalidaría la verificación. Los códigos de ruta citados en informes y manifiestos dependen de esta estructura.

## 1. Arquitectura y diseño
| Tema | Dónde |
|---|---|
| Arquitectura V1 (una instancia) | [arquitectura-inicial.md](arquitectura-inicial.md) |
| Arquitectura V2 (balanceador y grupo de Auto Scaling) | [arquitectura-v2.md](arquitectura-v2.md) |
| Persistencia y reservas | [persistencia-y-reservas.md](persistencia-y-reservas.md) |
| Autenticación, permisos y entradas QR | [autenticacion-y-entradas.md](autenticacion-y-entradas.md) |
| Sala de espera y cola virtual | [sala-de-espera-y-cola.md](sala-de-espera-y-cola.md) |
| Recintos, planos y funciones | [recintos-y-planos.md](recintos-y-planos.md) |
| Costos de V1 | [costos-v1.md](costos-v1.md) |
| Diagnóstico inicial del entorno | [diagnostico-entorno.md](diagnostico-entorno.md) |
| Arquitectura multicloud (inventario) | [multicloud/02-arquitectura-inventario.md](multicloud/02-arquitectura-inventario.md) |
| Diagramas del Entregable 2 | [entregable2/diagramas/](entregable2/diagramas/) |
| Diagramas del Entregable 3 | [entregable3/diagramas/](entregable3/diagramas/) |
| Diseño visual (auditoría y propuesta) | [auditoria-visual/](auditoria-visual/), [propuesta-visual/](propuesta-visual/), [atribuciones-imagenes.md](atribuciones-imagenes.md) |

## 2. Entregable 2
Índice propio con estado y siguiente paso: [entregable2/README.md](entregable2/README.md).
- Informe: [entregable2/informe-entregable2.md](entregable2/informe-entregable2.md). Las versiones finales en Word y PDF (`Entregable2-NexoEventos.docx` y `.pdf`) se conservan solo de forma local y no están disponibles en GitHub.
- Trazabilidad frente a la rúbrica: [matriz-cobertura-rubrica.md](entregable2/matriz-cobertura-rubrica.md), [matriz-requisitos-evidencias.md](entregable2/matriz-requisitos-evidencias.md), [matriz-cierre-observaciones.md](entregable2/matriz-cierre-observaciones.md).
- Presentación y guion: [entregable2/presentacion/](entregable2/presentacion/) (el archivo PowerPoint se conserva solo de forma local y no está en GitHub); gráficos: [entregable2/graficos/](entregable2/graficos/).
- Planes y procedimientos de ejecución cloud: los `plan-*.md` y `procedimiento-*.md` de [entregable2/](entregable2/).

## 3. Entregable 3
| Bloque | Documentos |
|---|---|
| Diagnóstico y viabilidad | [00](entregable3/00-diagnostico-y-plan.md), [01](entregable3/01-informe-viabilidad-fase0.md), [02](entregable3/02-plan-cuentas-gratuitas.md), [07](entregable3/07-viabilidad-integracion-aws-oci.md), [08](entregable3/08-procedimiento-sesion-aws-academy.md) |
| Replicación y failover en Docker local | [03](entregable3/03-prueba-local-failover.md), [04](entregable3/04-prueba-replicacion-failover-bd.md), [05](entregable3/05-diseno-proteccion-reservas-confirmadas.md), [06](entregable3/06-informe-estrategia-sincrona.md) |
| Protección del crédito y respaldo RDS → OCI | [09](entregable3/09-plan-eliminar-alb-y-parar-rds.md), [10](entregable3/10-verificaciones-previas-alb-y-rds.md), [11](entregable3/11-plan-respaldo-restaurable-rds-a-oci.md), [12](entregable3/12-preparacion-local-respaldo-rds.md), [13](entregable3/13-respaldo-rds-a-oci-cierre.md) |
| Cumplimiento, informe y defensa | [14](entregable3/14-matriz-cumplimiento-y-plan-minimo.md), [15](entregable3/15-informe-consolidado-entregable3.md), [16](entregable3/16-guion-defensa-entregable3.md), [17](entregable3/17-revision-calidad-academica.md) |
| Pendientes y procedimientos preparados | [18](entregable3/18-evaluacion-O1-restauracion-en-vm-oci.md), [19](entregable3/19-backlog-tecnico-y-auditoria-fase1.md), [20](entregable3/20-procedimientos-cloud-pendientes.md), [recordatorio de la RDS](entregable3/recordatorio-rds-20261116.md) |

Entregable final: las versiones en Word y PDF (`entregable3/informe-final/NexoEventos-Entregable3-Informe-Consolidado.docx` y `.pdf`) se conservan solo de forma local y no están disponibles en GitHub; el contenido está en [15-informe-consolidado-entregable3.md](entregable3/15-informe-consolidado-entregable3.md). Herramienta que lo genera: [entregable3/herramientas/](entregable3/herramientas/).

## 4. Evidencias académicas
| Ubicación | Qué contiene |
|---|---|
| [evidencias/](evidencias/) | Evidencias del Entregable 2, en carpetas con fecha (`AAAAMMDD-tema`) y carpetas `EV01`–`EV11` por requisito. Ver [matriz-rubrica.md](evidencias/matriz-rubrica.md) y [revision-rubrica.md](evidencias/revision-rubrica.md). |
| [evidencias/capturas/INDICE.md](evidencias/capturas/INDICE.md) | Índice de las capturas por nube y GitHub |
| [evidencias/multicloud/](evidencias/multicloud/) | Evidencias AWS, OCI, Azure e integración; ver su [README](evidencias/multicloud/README.md) |
| [entregable3/evidencias/](entregable3/evidencias/) | Evidencias del Entregable 3 (operaciones del 10 y 11 de nov, pruebas locales, corridas de laboratorio). Integridad: [MANIFIESTO-SHA256-20261110.txt](entregable3/evidencias/MANIFIESTO-SHA256-20261110.txt) |

## 5. Integración AWS–OCI y multicloud
Índice: [multicloud/README.md](multicloud/README.md), con diagnóstico, arquitectura, costos, plan, [transferencia de respaldos](multicloud/05-transferencia-respaldos.md), [criterios de restauración](multicloud/06-restauracion-criterios.md), [simulacro en OCI](multicloud/07-simulacro-oci.md), [recuperación de la aplicación](multicloud/08-recuperacion-aplicacion-oci.md) y [observabilidad en Azure](multicloud/09-azure-observabilidad.md). Complemento del Entregable 3: documentos 07, 11, 12, 13, 18 y 20 de la sección anterior.

## 6. Operaciones cloud
Todo en [operacion/](operacion/).
| Tema | Documentos |
|---|---|
| Encender y apagar V2 | [reencendido-v2.md](operacion/reencendido-v2.md), [propuesta-v2-alb-asg.md](operacion/propuesta-v2-alb-asg.md), [propuesta-v2-activacion-costos-20261105.md](operacion/propuesta-v2-activacion-costos-20261105.md), [propuesta-escalado-v2.md](operacion/propuesta-escalado-v2.md), [secuencia-prueba-real-v2-20261106.md](operacion/secuencia-prueba-real-v2-20261106.md) |
| Terraform y cuentas | [terraform-advertencias.md](operacion/terraform-advertencias.md), [migracion-entre-cuentas.md](operacion/migracion-entre-cuentas.md), [propuesta-rds-almacenamiento-y-terraform-20261106.md](operacion/propuesta-rds-almacenamiento-y-terraform-20261106.md) |
| Sesiones cloud y crédito | [procedimientos-sesion-cloud.md](operacion/procedimientos-sesion-cloud.md), [sesion-cloud-siguiente.md](operacion/sesion-cloud-siguiente.md), [calendario-credito-aws.md](operacion/calendario-credito-aws.md) |
| Despliegue y producción | [ansible-despliegue.md](operacion/ansible-despliegue.md), [configuracion-produccion.md](operacion/configuracion-produccion.md), [ci-docker.md](operacion/ci-docker.md), [plan-actualizacion-0008-2026-10-17.md](operacion/plan-actualizacion-0008-2026-10-17.md), [plan-actualizacion-aws-2026-10-07.md](operacion/plan-actualizacion-aws-2026-10-07.md) |
| Observabilidad y acceso a Azure | [observabilidad-cloudwatch.md](operacion/observabilidad-cloudwatch.md), [azure-acceso-tailscale.md](operacion/azure-acceso-tailscale.md), [propuesta-acceso-azure-tailscale-20261108.md](operacion/propuesta-acceso-azure-tailscale-20261108.md), [propuesta-dominio-estable-v2-20261106.md](operacion/propuesta-dominio-estable-v2-20261106.md) |

## 7. Laboratorios de PostgreSQL y failover (solo Docker local)
- **Qué se probó y resultados:** documentos 03 a 06 del Entregable 3 (sección 3) y las corridas `repl-*` de [entregable3/evidencias/](entregable3/evidencias/).
- **Dónde está el código:** [../scripts/repl-lab/](../scripts/repl-lab/) (replicación y fencing), [../scripts/failover-lab/](../scripts/failover-lab/) (failover de aplicación) y [../scripts/rehearsal/](../scripts/rehearsal/) (ensayo de actualización). Ver [../scripts/README.md](../scripts/README.md).
- **Salidas de ejecución (no versionadas):** `work/repl-lab/`, `work/failover-lab/` y `work/obs-lab/`; ver `work/README.md` en esa carpeta.

## 8. Informes y procedimientos de recuperación
- Respaldo y recuperación general: [respaldo-y-recuperacion.md](operacion/respaldo-y-recuperacion.md) y [recuperacion-completa.md](operacion/recuperacion-completa.md).
- Respaldo RDS → OCI y restauración: documentos 11, 12, 13 y 18 del Entregable 3, y los de multicloud 05 a 08 (sección 5).
- Procedimientos cloud preparados y no ejecutados: [entregable3/20-procedimientos-cloud-pendientes.md](entregable3/20-procedimientos-cloud-pendientes.md); del Entregable 2: [entregable2/procedimientos-pendientes-autorizacion.md](entregable2/procedimientos-pendientes-autorizacion.md).
- Informes históricos de sesiones y despliegues: [../outputs/](../outputs/).
