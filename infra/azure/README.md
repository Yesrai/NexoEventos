# Azure — observabilidad (preparación local; NADA desplegado)

Sustituye el esqueleto anterior. Raíz Terraform con **estado propio** y módulos `network`, `vm`, `budget` y `monitor`; `terraform fmt -check` y `terraform validate` correctos; con `plan` de revisión (lectura) y sin `apply`. Región por defecto `centralus` (la directiva de la suscripción *Azure for Students* deniega las demás salvo `southcentralus`, `mexicocentral`, `westus3`, `canadacentral`).

| Módulo | Recursos | Seguridad / costo |
|---|---|---|
| `network` | RG, VNet `10.40.0.0/16`, subred `10.40.1.0/24`, NSG | Entrada solo desde `admin_cidr` (/32: 22 y 443) con denegación explícita del resto; 10051 solo si se autorizan IPs de AWS; **salida a Internet denegada salvo 80/443/53/123** y el servicio de plataforma de Azure |
| `vm` | IP pública estática Standard (con etiqueta DNS), NIC, VM Linux (`create=false`); en la raíz: auto-shutdown de DevTest Labs (hora UTC por variable) | Solo clave SSH; Ubuntu 24.04 con Trusted Launch (arranque seguro + vTPM); sin extensiones; identidad administrada (solo «Monitoring Reader» en el RG, ver `main.tf`); SSD estándar 64 GiB |
| `budget` | presupuesto mensual (60 USD por defecto) con alertas 50/80/100 % real y 100 % previsto | Solo avisa; exige al menos un correo |
| `monitor` | Log Analytics (30 días, tope 0,2 GB/día), registro de actividad de la suscripción, grupo de acción por correo y 3 alertas de métricas de la VM; Application Insights y pruebas HTTPS **desactivadas** | Verificar costo antes de activar las pruebas |

La configuración de la VM (Zabbix 7.0, PostgreSQL, Grafana, Nginx/TLS) está en `ansible/roles/monitoring_zabbix_grafana`; el diseño, las verificaciones de la Fase 0, las validaciones y el plan de despliegue en `docs/multicloud/09-azure-observabilidad.md`.

Antes de crear nada: `az login`, confirmar saldo/vigencia del crédito, **registrar los proveedores** `Microsoft.Compute/Network/Storage` (hoy NotRegistered; `resource_provider_registrations = "none"` impide el registro automático) y comprobar cuota y tamaño de VM (`az vm list-skus`). Uso: `terraform init -backend-config="path=$PWD/../../work/terraform-state/azure/terraform.tfstate"`; `work/terraform-envs/azure.tfvars` a partir de `terraform.tfvars.example`.

## Costos estimados (tarifa pública; **verificar** con la calculadora)
| Recurso | Estimación |
|---|---|
| VM `Standard_D2s_v4` (2 vCPU/8 GiB; `B2s` está restringida para Azure for Students), solo en ventanas (≈ 40 h/mes) | USD 0,108/h (tarifa pública, 28-oct-2026) → ≈ USD 4,3 por 40 h |
| Disco SSD estándar 64 GiB (persiste aunque la VM esté desasignada) | USD 4,80/mes |
| IP pública estática Standard (existe solo con la VM) | USD 0,005/h (≈ 3,65/mes si queda siempre) |
| Log Analytics (5 GB/mes de ingesta gratuita; tope diario 0,2 GB) | ≈ USD 0–1/mes |
| Pruebas de disponibilidad externas | por verificar; desactivadas |
| **Total** | ≈ USD 12,8/mes con ventanas de 40 h y la VM desasignada entre ellas (≈ 87 con 24×7: **nunca dejarla encendida**); saldo de USD 100 leído el 27-oct-2026 |
