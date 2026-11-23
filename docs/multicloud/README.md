# NexoEventos multicloud (AWS + OCI + Azure) — índice

Estado al **28-oct-2026** (AWS V1/V2 + RDS Multi-AZ, OCI recuperación y Azure observabilidad ejecutados; ver cada documento y `../entregable2/`). Fuente de verdad: este repositorio, el estado Terraform local y las evidencias fechadas; las imágenes conceptuales (IP, dominio) **no** son fuente. Todo lo no verificado se marca **PENDIENTE**.

| Documento | Contenido |
|---|---|
| [01-diagnostico.md](01-diagnostico.md) | Qué existe de verdad (implementado/probado/pendiente), datos reales de AWS y bloqueos |
| [02-arquitectura-inventario.md](02-arquitectura-inventario.md) | Arquitectura corregida, inventario por nube, CIDR, conexiones y permisos |
| [03-costos-y-riesgos.md](03-costos-y-riesgos.md) | Costos estimados, presupuesto y riesgos |
| [04-plan-implementacion.md](04-plan-implementacion.md) | Etapas, orden, aceptación y evidencias |
| [05-transferencia-respaldos.md](05-transferencia-respaldos.md) | Transferencia cifrada AWS → estación → OCI con clave independiente y SHA-256 |
| [06-restauracion-criterios.md](06-restauracion-criterios.md) | Restauración aislada y criterios de aceptación |
| [07-simulacro-oci.md](07-simulacro-oci.md) · [08-recuperacion-aplicacion-oci.md](08-recuperacion-aplicacion-oci.md) | Simulacro de restauración y recuperación de la aplicación en OCI (ejecutados el 23-oct) |
| [09-azure-observabilidad.md](09-azure-observabilidad.md) | Azure: Zabbix + Grafana + Azure Monitor, plan, ventana del 28-oct, incidentes y resultados |
| [../entregable2/README.md](../entregable2/README.md) | **Informe del Entregable 2** (20 secciones), diagramas, matriz de evidencias y procedimientos pendientes |
| [../../infra/oci/README.md](../../infra/oci/README.md), [../../infra/azure/README.md](../../infra/azure/README.md) | Terraform modular con costos por recurso (OCI y Azure desplegados; ver estado en cada documento) |
| [../evidencias/multicloud/](../evidencias/multicloud/README.md) | Estructura de evidencias (aws, oci, azure, integracion, automatizacion, informe-material) |

Leyenda: **IMPLEMENTADO** (existe en código/IaC), **PROBADO** (hay evidencia ejecutada), **PENDIENTE** (sin crear/sin verificar). Las cifras de costo son **estimaciones por tarifa pública**, no consumo observado.
