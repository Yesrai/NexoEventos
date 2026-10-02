# Diagnóstico de entorno — 1 de octubre de 2026

No se crearon, modificaron, detuvieron ni eliminaron recursos cloud. No se ejecutó `terraform plan`, `apply` ni `destroy`.

## Herramientas locales

| Herramienta | Resultado |
|---|---|
| macOS | 27.0.1, Apple Silicon `arm64` |
| VS Code | 1.126.0 |
| Git | 2.54.0 (Apple Git-157) |
| Terraform | 1.16.4, instalado desde el tap de HashiCorp |
| AWS CLI | 2.37.7 |
| Azure CLI | 2.90.0 |
| Node.js | 24.21.0 LTS instalado; Node 26.7.0 sigue primero en el PATH del usuario |
| npm | 11.19.0 |
| Python | 3.12.0 |
| Docker CLI | 28.0.4 instalado; daemon detenido; no se modificó |
| PostgreSQL | 14.18, servicio local activo en 5432 |

## AWS Academy Learner Lab [184558]

| Comprobación | Resultado | Evidencia | Limitación |
|---|---|---|---|
| Estado | Laboratorio terminado; no se pulsó Start Lab | Panel: `Lab terminated`, temporizador 00:00 | Sin sesión no se pudo abrir consola ni inventariar recursos |
| Presupuesto | Asignado USD 50; indicador `Used $0.1 of $50` | Panel del laboratorio | Resto aritmético USD 49.90, pero AWS Budgets puede retrasarse 8–12 h; no es saldo en tiempo real |
| Regiones | Permitidas por instrucciones: `us-east-1`, `us-west-2` | README del laboratorio, actualizado 2025-06-24 | No prueba permisos de creación |
| EC2 | On-Demand; tamaños nano/micro/small/medium/large; máximo 9 instancias concurrentes por región y 32 vCPU; AMI Marketplace y EC2 Fleet no permitidos | README | No se probó creación; 20+ concurrentes puede desactivar la cuenta |
| EBS | Hasta 100 GB; gp2/gp3/sc1/standard; PIOPS no soportado | README | Lectura de instrucciones, no prueba operativa |
| Auto Scaling | Puede asumir `LabRole`; mismos tamaños y límites EC2 | README | Lectura de instrucciones |
| Balanceadores | ELB listado; puede asumir `LabRole` | README | Sin otras restricciones documentadas en la vista; no probado |
| RDS | Aurora provisionado, Oracle, SQL Server, MySQL, PostgreSQL y MariaDB; nano–medium; On-Demand; gp2 hasta 100 GB; sin enhanced monitoring | README | Puede seguir ejecutándose al acabar sesión y reiniciarse tras 7 días detenido |
| S3 | S3 listado y puede asumir `LabRole` | README | No se observaron restricciones adicionales; no probado |
| VPC | VPC listado entre servicios disponibles | README | No se observaron restricciones adicionales; no probado |
| CloudWatch | Listado entre servicios disponibles | README | CloudTrail no puede habilitar logging a CloudWatch; no probado |
| IAM | Muy limitado; sin usuarios/grupos; solo roles vinculados a servicio; roles de servicio generalmente permitidos | README | No se probaron acciones IAM |
| Roles | `LabRole`, `LabInstanceProfile`, roles EKS y roles EMR precreados | README | Usarlos según servicio; no se leyeron credenciales |
| Fin de sesión | Recursos/datos persisten; EC2 puede detenerse y arranca en próxima sesión; SageMaker notebook no arranca; Canvas puede seguir ejecutándose | README | Recursos persistentes pueden consumir en sesiones futuras |

Revisión actual: la pestaña oficial de AWS Academy permaneció en blanco incluso tras recargar. No se pulsó `Start Lab`; por ello no hay identidad STS, inventario regional ni saldo actualizado. Las filas anteriores proceden de la lectura previa de instrucciones/panel y no equivalen a permisos operativos actuales.

## Azure for Students

| Comprobación | Resultado | Evidencia | Limitación |
|---|---|---|---|
| Oferta/estado | `Azure for Students`, Activo, plan `Plan de Azure` | Información esencial de la suscripción | No prueba habilitación de todos los servicios |
| Rol | Propietario a nivel de suscripción | Campo `Mi rol: Propietario` | No descarta políticas, cuotas o restricciones de oferta |
| Gasto actual | 0.00; previsión 0.00 | Panel de suscripción | No equivale al crédito restante |
| Crédito | Usuario informa USD 100 iniciales | Información del usuario | Saldo y vencimiento pendientes: portal de patrocinio pide selección de cuenta |
| Servicios gratuitos | Expiran el 8 de junio de 2027 | Panel de servicios gratuitos | Esta fecha no se tomó como vencimiento del crédito |
| Recursos | Ningún recurso en la suscripción | `No tiene ningún recurso en esta suscripción` | Comprobación visual del portal |
| Blob/VNet/NSG/VM | Aparecen como servicios de Azure; aún no validados | Navegación del portal | Pendientes políticas, proveedores registrados y cuota por región; catálogo no implica disponibilidad |
| Defender | No habilitado | Panel de suscripción | No se modificó |

Revisión actual de solo lectura:

- Sesión del portal autenticada con MFA; no se conservan en este informe correo, identificadores ni datos del directorio.
- Directiva `Allowed resource deployment regions`, efecto `Deny`: `southcentralus`, `mexicocentral`, `westus3`, `canadacentral` y `centralus`.
- `Microsoft.Compute`, `Microsoft.Network` y `Microsoft.Storage` aparecen `NotRegistered` y `RegistrationRequired`. No se registró ningún proveedor.
- La vista de cuotas no devolvió filas seleccionables y quedó sin proveedor/región; los límites de vCPU/tamaños de VM permanecen pendientes.
- Blob Storage, VNet/NSG y una VM de recuperación no son todavía viables de forma comprobada: requieren registro de proveedor y, para VM, cuota/tamaño disponibles en una región permitida.
- El portal de patrocinio quedó en selección de cuenta. El crédito inicial de USD 100 sigue siendo información de la usuaria; saldo y vencimiento del crédito no están confirmados. La fecha 8 de junio de 2027 corresponde a servicios gratuitos, no al crédito.

## Fuentes potenciales de consumo

- AWS: EC2 que se reinicie al iniciar una nueva sesión; RDS que permanezca activo o se reinicie tras siete días; EBS, snapshots, S3, balanceadores, NAT y otros recursos persistentes. El inventario real está pendiente de iniciar el laboratorio.
- Azure: no hay recursos observados, por lo que no se detectó consumo actual. Cualquier almacenamiento, IP pública, disco, snapshot o VM futura generaría consumo según oferta y región.

## Bloqueos

1. AWS: para autenticar e inventariar hay que pulsar `Start Lab`; requiere autorización explícita en el momento.
2. Azure: para ver saldo en el portal de patrocinio la usuaria debe elegir la cuenta y completar cualquier MFA.
3. Azure: políticas, proveedores registrados y cuotas regionales no se completaron todavía.
4. Primera entrega: la fecha del 30 de septiembre de 2026 ya pasó; priorizar una demo local verificable y documentación de restricciones.
