# Azure — despliegue de la infraestructura BASE (2026-10-28, UTC)

Estado: **desplegada y verificada en Azure** (suscripción Azure for Students, `Enabled`, región `centralus`). **No hay VM, NIC, IP pública ni disco administrado.** Zabbix y Grafana **no** están instalados todavía; la VM `Standard_D2s_v4` **no** se ha creado.

## Despliegue
- Plan guardado `azure-base-definitivo.tfplan` (9 a crear, 0 modificar, 0 destruir; sin VM/NIC/IP/disco), revisado antes del `apply`: suscripción activa = la del plan, configuración y tfvars sin cambios posteriores al plan, proveedores `Compute/Network/OperationalInsights/Insights` registrados.
- `terraform apply` del plan guardado, sin `-auto-approve` ni otros cambios: **`Apply complete! 9 added, 0 changed, 0 destroyed`** en 111 s, sin errores de permisos, políticas ni proveedores (`terraform-apply-resumen.txt`).
- `terraform plan` posterior: **No changes** (código de salida 0; `terraform-plan-sin-cambios.txt`).

## Inventario (9 recursos de Terraform; `terraform-state-list.txt`, `inventario-azure.txt`)
Grupo de recursos `rg-nexoeventos-observabilidad` · VNet `vnet-nexoeventos-obs` (10.40.0.0/16) · subred `snet-monitoring` (10.40.1.0/24) · NSG `nsg-nexoeventos-obs` · asociación NSG–subred · Log Analytics `log-nexoeventos-obs` · grupo de acción `ag-nexoeventos-obs` · ajuste de diagnóstico `actividad-suscripcion` (alcance de suscripción) · presupuesto `presupuesto-nexoeventos` (alcance de suscripción).

## Verificación posterior (`verificacion-base.txt`; `azure-verify-deploy.sh --stage base`; 18/18 correctas)
Región y VNet; subred con NSG asociado; NSG: ninguna regla de entrada «Allow» con origen abierto, administración solo 22 y 443 desde una única IP /32 (enmascarada), denegación explícita de toda la entrada y de la salida a Internet salvo 80/443/53/123 y el servicio de plataforma de Azure (`nsg-reglas.txt`); Log Analytics con 30 días de retención y tope de 0,2 GB/día; grupo de acción con 1 receptor de correo (enmascarado); presupuesto de 60 USD mensual con 4 avisos (50/80/100 % reales y 100 % previsto) **sin automatización** (solo avisa); registro de actividad hacia Log Analytics; **ausencia de máquinas virtuales, discos, IP públicas e interfaces de red**.
Incidencias del verificador (no de la infraestructura): la primera ejecución dio 3 falsos fallos por errores del propio script (lectura de la subred, formato de la consulta de Log Analytics y campos del presupuesto); se corrigieron y se repitió la verificación completa. Causas, correcciones y la salida de la primera ejecución están en `verificacion-base-primera-ejecucion.txt`.

## Costos (consulta del 28-oct-2026; la facturación puede tardar en reflejarse)
Cost Management (mes en curso): **sin filas (USD 0)**; consumo detallado: 0 líneas; saldo de crédito **USD 100,00** (estimado 100,00; cargos pendientes elegibles 0,00). Una primera consulta de Cost Management devolvió 429 (límite de solicitudes) y se repitió con éxito. Los 9 recursos no cuestan en uso normal; riesgo residual: ingesta de Log Analytics (tope 0,2 GB/día; los primeros 5 GB/mes son gratis; máximo pesimista ≈ USD 3,9 en 7 días).

## Pendiente (no hecho en esta fase)
Crear la VM `Standard_D2s_v4` (+7 recursos), instalar Zabbix/Grafana con Ansible y las pruebas de monitoreo, alertas y recuperación en Azure.
