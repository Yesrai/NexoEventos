# Azure — observabilidad (preparación local; NADA desplegado)

Sustituye el esqueleto anterior. Raíz Terraform con **estado propio** y módulos `network`, `vm`, `budget` y `monitor`; `terraform fmt -check` y `terraform validate` correctos; sin `plan`/`apply`. Región por defecto `centralus` (la directiva de la suscripción *Azure for Students* deniega las demás salvo `southcentralus`, `mexicocentral`, `westus3`, `canadacentral`).

| Módulo | Recursos | Seguridad / costo |
|---|---|---|
| `network` | RG, VNet `10.40.0.0/16`, subred `10.40.1.0/24`, NSG | NSG sin reglas abiertas: SSH y HTTPS solo desde `admin_cidr` (nunca `0.0.0.0/0`); 10051 solo desde IPs de AWS indicadas (Fase B) |
| `vm` | IP pública estática Standard, NIC, VM Linux (`create=false`) | solo clave SSH; Ubuntu 24.04; disco SSD estándar 64 GiB; sin identidad administrada |
| `budget` | presupuesto mensual (por defecto USD 100) con alertas 50/80/100 % real y 100 % previsto | solo avisa |
| `monitor` | Log Analytics (30 días, tope 0,2 GB/día); Application Insights y pruebas HTTPS externas **desactivadas** | verificar costo antes de activar |

Antes de crear nada: `az login`, confirmar saldo/vigencia del crédito, **registrar los proveedores** `Microsoft.Compute/Network/Storage` (hoy NotRegistered; `resource_provider_registrations = "none"` impide el registro automático) y comprobar cuota y tamaño de VM (`az vm list-skus`). Uso: `terraform init -backend-config="path=$PWD/../../work/terraform-state/azure/terraform.tfstate"`; `work/terraform-envs/azure.tfvars` a partir de `terraform.tfvars.example`.

## Costos estimados (tarifa pública; **verificar** con la calculadora)
| Recurso | Estimación |
|---|---|
| VM `Standard_B2s` (2 vCPU/4 GB), solo en ventanas (≈ 40 h/mes) | ≈ USD 0,04/h → ≈ USD 1,7/mes |
| Disco SSD estándar 64 GiB (persiste aunque la VM esté desasignada) | ≈ USD 5/mes |
| IP pública estática Standard (existe solo con la VM) | ≈ USD 0,005/h (≈ 3,6/mes si queda siempre) |
| Log Analytics (5 GB/mes de ingesta gratuita; tope diario 0,2 GB) | ≈ USD 0–1/mes |
| Pruebas de disponibilidad externas | por verificar; desactivadas |
| **Total** | ≈ USD 8–12/mes, dentro de los USD 100 informados (sin verificar) |
