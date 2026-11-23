# Ventana de Azure del 4-nov-2026 — resultado (PARCIAL: obs. 6 medida; obs. 3 y 5 BLOQUEADAS)

Horas en UTC (Perú = UTC−5). VM `vm-nexoeventos-obs` (D2s_v4), grupo `rg-nexoeventos-observabilidad`. Sin Terraform, sin AWS ni OCI. IP, suscripción y correos no aparecen en estos archivos.

## Prechequeos (Fase 1, aprobados antes de encender)
Identidad y rol `Owner`; VM `deallocated`; 12 recursos; umbrales **sin modificar**: `alerta-vm-cpu` (CPU media > 80 %, ventana 15 min, evaluación cada 5 min), `alerta-vm-up` (VmAvailabilityMetric < 1, ventana 5 min, cada 1 min), ambas ligadas al grupo `ag-nexoeventos-obs` (receptor `Enabled`); `alerta-vm-up` figuraba «Fired» (28-oct); regla NSG `admin-https` guardada completa en un archivo local 0600 (fuera de `docs/`); apagado automático original 17:38 UTC; precio público D2s_v4 0,108 USD/h (150 min ≈ 0,27 USD ≤ 0,30). Protecciones: apagado de la propia VM movido a encendido + 150 min (01:18 UTC, verificado) y vigilante local `--minutes 150` (01:16:17Z).

## Línea de tiempo
| UTC (Perú) | Hecho |
|---|---|
| 22:46:22 (17:46) | `az vm start` (solo esa VM); `PowerState/running` a las 22:46:37 |
| 22:47 | Arranque completo del guest en ≈ 23 s (PostgreSQL, Grafana, Zabbix server, Nginx, agente) según el registro de arranque |
| 22:48 | Primer valor de «Available Memory Bytes»: **0** |
| 22:50:41 (17:50) | **`alerta-vm-mem` (Sev2) → Fired** (falso positivo del arranque: mínimo 0 < 400 MiB; luego ≈ 6,9 GiB) |
| 22:57:09 (17:57) | **`alerta-vm-up` (Sev1): Fired → Resolved** (10 min 47 s tras el encendido; el valor de la métrica es 1,0 desde las 22:48) |
| ~22:57–23:00 | Comprobación del acceso al guest (ver bloqueos); carga y Grafana NO realizados |
| 22:59:52 (17:59) | `az vm deallocate`; `PowerState/deallocated` confirmado a las 23:00:29 |
| 23:03:09 (18:03) | **`alerta-vm-up` (Sev1): Resolved → Fired** (3 min 17 s tras la orden; el 28-oct fueron ≈ 2 min 40 s) |
| 23:09 | NSG restaurada, apagado automático restaurado, vigilante cancelado, verificación `--expect vm-off` correcta |

## Observación 6 — `alerta-vm-up`
**Transiciones reales medidas en la API de alertas de Azure** (`alertas-api.json`, `metrica-disponibilidad-vm.txt`): `Fired → Resolved` al encender y `Resolved → Fired` al desasignar. Conclusión honesta: **la regla se dispara con un apagado planificado** (no distingue un apagado voluntario de una caída) y queda «Fired» mientras la VM esté desasignada; no es un defecto de configuración sino la semántica de una alerta de disponibilidad. **Correos: PENDIENTE de confirmación de la usuaria** (se esperan «Resolved» ≈ 17:57 y «Fired» ≈ 18:03 hora de Perú). Estado de la observación: **parcial** (técnicamente medida; cerrada solo al confirmar los correos).

## Observaciones 3 y 5 — BLOQUEADAS (no realizadas)
- **Acceso al guest:** el NSG permite la IP actual (Network Watcher: `Allow admin-https`), pero **UFW dentro de la VM solo permite 22 y 443 desde la IP /32 del operador de la ventana del 28-oct** (el rol de Ansible lo fija con `monitoring_admin_cidr`). Desde la IP actual no responden ni 443 ni 22. Grafana quedó inaccesible.
- **`az vm run-command` no está disponible:** la VM se creó con `allowExtensionOperations = false` (endurecimiento; no se puede cambiar en una VM existente). Por tanto no se pudo lanzar la carga de CPU sin SSH.
- Consecuencia: **no se generó carga, no hubo alerta de CPU nueva ni correo de alerta de CPU, y no hay capturas de Grafana.** Se mantienen pendientes (observación 3: la alerta del 28-oct sigue siendo la única, con el receptor entonces sin verificar).
- Vías para desbloquear (decisión de la usuaria): (a) usar la red con la **IP pública original** (la de la regla guardada), con lo que NSG, UFW y SSH funcionan como el 28-oct; (b) **reconstruir la VM** con Terraform con un `monitoring_admin_cidr` nuevo (destruye/crea la VM; requiere autorización aparte y más tiempo).

## Hallazgo nuevo — `alerta-vm-mem`
Se dispara en cada arranque porque la primera muestra de «Available Memory Bytes» es 0 (mínimo en ventana de 15 min), y permanece «Fired» con la VM desasignada (sin datos). Es un falso positivo reproducible; mejora posible (no aplicada: no se tocan umbrales): agregación o ventana que ignore la primera muestra, o requerir varios periodos.

## Estado final y coste
VM `deallocated`; NSG `admin-https` **idéntica a la original** (comparación de todos los campos salvo `etag`); apagado automático **Enabled 17:38 UTC** (igual que antes); vigilante cancelado (0 procesos); 12 recursos en el grupo y 2 grupos en la suscripción (sin recursos nuevos). Alertas: `alerta-vm-up` Fired, `alerta-vm-mem` Fired, `alerta-vm-cpu` Resolved. **Coste incremental estimado:** VM encendida 22:46:22–23:00:29 ≈ 14 min × 0,108 USD/h ≈ **0,03 USD** (tarifa pública; sin verificar con facturación). Siguen facturando apagada: disco, IP estática y Log Analytics (centavos/día).
