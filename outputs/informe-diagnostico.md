# Informe de diagnóstico y preparación — NexoEventos

Fecha: 1 de octubre de 2026. Alcance cloud: solo lectura. No se inició el laboratorio AWS, no se crearon/modificaron recursos y no se ejecutó `terraform plan`, `apply` ni `destroy`.

## Herramientas

| Herramienta | Estado y versión |
|---|---|
| macOS | 27.0.1, Apple Silicon `arm64` |
| VS Code | Instalado, 1.126.0 |
| Git | Instalado, 2.54.0 (Apple Git-157) |
| Terraform | Instalado, 1.16.4 |
| AWS CLI | Instalado, 2.37.7 |
| Azure CLI | Instalado, 2.90.0 |
| Node.js | Node 24.21.0 LTS instalado; Node 26.7.0 preexistente sigue primero en PATH |
| Python | Instalado, 3.12.0 |
| Docker | CLI 28.0.4; daemon detenido; no fue modificado |
| PostgreSQL | 14.18 activo en localhost:5432 |

## AWS Academy

| Comprobación | Resultado | Evidencia | Limitación |
|---|---|---|---|
| Laboratorio | Learner Lab [184558], terminado | Panel `Lab terminated`, 00:00 | No se pulsó Start Lab; sin autenticación para inventario |
| Presupuesto | USD 50 asignados; USD 0.10 usados | `Used $0.1 of $50` | USD 49.90 es solo resto aritmético; AWS Budgets puede retrasarse 8–12 h |
| Regiones | `us-east-1`, `us-west-2` | README del lab, 2025-06-24 | No prueba permiso de creación |
| EC2/EBS | On-Demand; nano–large; 9 instancias/región, 32 vCPU; EBS ≤100 GB; gp2/gp3/sc1/standard | README | AMI Marketplace, PIOPS y EC2 Fleet no soportados |
| RDS | PostgreSQL y otros motores; nano–medium; gp2 ≤100 GB; sin enhanced monitoring | README | Puede seguir activo al terminar sesión y reiniciarse tras 7 días detenido |
| ELB/Auto Scaling | Listados; pueden asumir `LabRole` | README | No probado operativamente |
| S3/VPC/CloudWatch | Listados como disponibles; S3 puede asumir `LabRole` | README | Sin prueba de creación; CloudTrail no puede enviar logs a CloudWatch |
| IAM | Sin usuarios/grupos; solo roles vinculados a servicio; roles de servicio generalmente permitidos | README | Acceso muy limitado |
| Roles | `LabRole`, `LabInstanceProfile`, roles EKS y EMR precreados | README | Deben usarse según el servicio |
| Persistencia | Datos/recursos persisten; EC2 puede detenerse y reiniciarse en la siguiente sesión | README | Puede reanudarse consumo al iniciar otra sesión |

## Azure for Students

| Comprobación | Resultado | Evidencia | Limitación |
|---|---|---|---|
| Oferta y estado | Azure for Students, Activo, Plan de Azure | Información esencial | No prueba disponibilidad de cada servicio |
| Rol | Propietario en la suscripción | Campo `Mi rol` | Políticas y cuotas aún aplican |
| Costo | Actual 0.00, previsión 0.00 | Panel | No equivale al saldo del crédito |
| Crédito | La usuaria informa USD 100 iniciales | Información del usuario | Saldo/vencimiento pendientes; portal oficial pide selección de cuenta/MFA |
| Servicios gratuitos | Expiran 8-jun-2027 | Panel | No es vencimiento confirmado del crédito |
| Recursos | Ninguno observado | Panel: sin recursos en la suscripción | Inventario visual de portal |
| Blob/VNet/NSG/VM | Viabilidad no confirmada | Servicios visibles en portal | Faltan políticas, proveedores registrados y cuotas regionales |

## Consumo y bloqueos

- AWS: posibles fuentes futuras son EC2 reiniciada al comenzar sesión, RDS, EBS/snapshots, S3, ELB, NAT e IPs. Sin sesión activa no se pudo inventariar.
- Azure: no se observaron recursos ni consumo actual. Saldo real pendiente de autenticación en el portal de crédito.
- La primera entrega del 30-sep-2026 ya pasó; conviene priorizar la demo local y documentar el alcance pendiente.

## Preparación local completada

- Repositorio Git local en la carpeta del proyecto, rama `main`, sin publicación remota.
- Frontend React/TypeScript/Vite responsive con carga, error, vacío, búsqueda y catálogo.
- Backend FastAPI con `GET /health` y `GET /api/events`.
- Variables de entorno de ejemplo sin secretos.
- PostgreSQL local disponible para la próxima iteración; el catálogo actual es deliberadamente en memoria.
- Esqueletos Terraform para AWS/Azure/GCP sin providers ni recursos.
- Workflow de CI preparado, no publicado ni ejecutado en GitHub.

## Verificación ejecutada

- `terraform fmt -check -recursive infra`: correcto.
- `terraform validate` en AWS, Azure y GCP: correcto.
- `pytest`: 2 pruebas aprobadas.
- `npm run build`: correcto, Vite produjo el bundle.
- API real: `/health` respondió `ok` y `/api/events` devolvió tres eventos.
- QA visual: escritorio y móvil 390×844 revisados; catálogo conectado y diseño responsive.

## Próximos pasos

1. La usuaria elige la cuenta en el portal de crédito Azure y completa MFA; registrar saldo y vencimiento.
2. Con autorización explícita, iniciar AWS Learner Lab e inventariar recursos en ambas regiones, solo lectura.
3. Consultar políticas y cuotas Azure para Storage, Network y Compute sin registrar proveedores.
4. Añadir persistencia PostgreSQL y migraciones al backend.
5. Implementar reservas y QR simulados con pruebas.
6. Diseñar módulos Terraform a partir de permisos y costos confirmados.
7. Solicitar aprobación separada antes de cualquier despliegue cloud.
