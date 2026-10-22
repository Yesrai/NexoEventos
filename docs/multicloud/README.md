# NexoEventos multicloud (AWS + OCI + Azure) — índice

Estado al **22-oct-2026**. Fuente de verdad: este repositorio, el estado Terraform local y las evidencias fechadas; las imágenes conceptuales (IP, dominio) **no** son fuente. Todo lo no verificado se marca **PENDIENTE**.

| Documento | Contenido |
|---|---|
| [01-diagnostico.md](01-diagnostico.md) | Qué existe de verdad (implementado/probado/pendiente), datos reales de AWS y bloqueos |
| [02-arquitectura-inventario.md](02-arquitectura-inventario.md) | Arquitectura corregida, inventario por nube, CIDR, conexiones y permisos |
| [03-costos-y-riesgos.md](03-costos-y-riesgos.md) | Costos estimados, presupuesto y riesgos |
| [04-plan-implementacion.md](04-plan-implementacion.md) | Etapas, orden, aceptación y evidencias |
| [05-transferencia-respaldos.md](05-transferencia-respaldos.md) | Transferencia cifrada AWS → estación → OCI con clave independiente y SHA-256 |
| [06-restauracion-criterios.md](06-restauracion-criterios.md) | Restauración aislada y criterios de aceptación |
| [../../infra/oci/README.md](../../infra/oci/README.md), [../../infra/azure/README.md](../../infra/azure/README.md) | Terraform modular (sin desplegar) con costos por recurso |
| [../evidencias/multicloud/](../evidencias/multicloud/README.md) | Estructura de evidencias (aws, oci, azure, integracion, automatizacion, informe-material) |

Leyenda: **IMPLEMENTADO** (existe en código/IaC), **PROBADO** (hay evidencia ejecutada), **PENDIENTE** (sin crear/sin verificar). Las cifras de costo son **estimaciones por tarifa pública**, no consumo observado.
