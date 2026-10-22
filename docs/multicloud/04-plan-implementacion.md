# 4. Plan de implementación por etapas

Cada etapa con efecto en una nube requiere autorización explícita (acción, costo, riesgo). Evidencias en `docs/evidencias/multicloud/<nube>/AAAAMMDD-<tema>/`.

| # | Etapa | Qué se hace | Aceptación (evidencia auténtica) | Costo |
|---|---|---|---|---|
| 0 | Cuentas y verificaciones | AWS: Start Lab + credenciales. OCI: crear cuenta, región de origen, clave API. Azure: saldo/vigencia del crédito, registrar proveedores, cuota/tamaño de VM en región permitida | AWS `sts` correcto y lectura de VPC/RDS; OCI `oci iam region list` y cuota; Azure `az vm list-skus`/uso y saldo | 0 |
| 1 | Repositorio y CI estático | `infra/oci`, ajustar `infra/azure`; `terraform fmt/validate` + Ansible `--syntax-check` + Trivy config en Actions (sin credenciales) | CI en verde con los nuevos jobs | 0 |
| 2 | AWS: inventario real y línea base | Releer VPC/SG/RDS (solo lectura), comparar con el estado local, registrar | `aws/AAAAMMDD-inventario-real/` coincidente o diferencias explicadas | 0 |
| 3 | OCI: base | Terraform (estado propio): compartment, VCN `10.30.0.0/16`, subred privada, NSG, Service Gateway, Bucket privado, políticas mínimas | `terraform plan` revisado → `apply` → comprobación de que no hay IP pública ni bucket público | ≈ 0 |
| 4 | Respaldo AWS→OCI | Crear respaldo fresco (procedimiento existente), descargar, subir a OCI, verificar SHA-256 en cada salto | hashes iguales en S3, estación y OCI; objeto privado | ≈ 0 |
| 5 | OCI: simulacro de restauración | VM temporal + Bastion, PostgreSQL 18, restaurar y comparar huella (135 reservas, 135 entradas, 25 usuarios, Alembic 0008); destruir la VM | informe con tiempos (RTO medido) y huella idéntica | ≈ 0 |
| 6 | Azure: base | Terraform: RG, VNet `10.40.0.0/16`, NSG por IP, presupuesto con alertas | alerta de presupuesto creada; NSG sin entradas abiertas | ≈ 0 |
| 7 | Azure: Zabbix + Grafana | VM + Ansible (Zabbix server/PostgreSQL, Grafana, TLS), arranque solo en ventana | interfaces por HTTPS desde la IP del operador; versiones y hashes registrados | ≈ USD 0,04/h |
| 8 | Observabilidad externa (Fase A) | Zabbix web scenarios y pruebas de disponibilidad de Azure contra V1/V2 (`/healthz`, `/api/events`, TLS); paneles de Grafana | capturas sin datos sensibles + series con fechas | |
| 9 | Integración y fallos | Ventana AWS (V1 o V2): provocar un fallo real y mostrar detección en Zabbix/Azure y alerta; opcional Fase B con agentes (SG con autorización) | línea de tiempo: fallo → alerta → recuperación | ≈ 0,11/h |
| 10 | RDS Multi-AZ (opcional) | Consultar permisos/costo; si procede, conversión en ventana con respaldo y conmutación | `describe-db-instances` Multi-AZ + prueba de failover o denegación documentada | +0,018/h |
| 11 | Cierre | Detener/destruir temporales, inventario de costos reales, índice de evidencias, matriz rúbrica | recursos apagados, estados Terraform consistentes, sin secretos | |

Orden recomendado: **0 → 1 → 3 → 6** (bases sin costo, en paralelo con la espera de AWS) → **2 → 4 → 5** → **7 → 8** → **9 → 10 → 11**.

## Reglas transversales
- Nunca `apply`/`destroy` sin plan guardado revisado y autorización; estados y planes solo en `work/` (0600).
- Sin credenciales en Git, logs ni capturas; CI sin acceso a nubes.
- V1, RDS, S3, respaldos, AMI, certificado y secretos **no se modifican**; la etapa 10 solo con autorización específica.
- Cada evidencia con fecha, comando/origen y resultado real; lo no ejecutado se marca PENDIENTE.
