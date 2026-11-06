# Ventana de Azure para la exposición (5-nov-2026, saneado)

Hora de Perú (UTC−5). Suscripción «Azure for Students», grupo `rg-nexoeventos-observabilidad` (centralus). Solo se inició la VM y se hicieron lecturas; no se cambió NSG, DNS, credenciales ni configuración, y no se reinició ningún servicio.

| Hora | Hecho |
|---|---|
| 15:04 | Estado inicial: `VM deallocated` (Standard_D2s_v4). La regla `admin-https` (443) y `admin-ssh` (22) permiten solo la IP /32 actual del operador (coincide con la IP pública de la usuaria) |
| 15:04:19 | `az vm start` (autorizado) |
| 15:06:05 | `VM running` (≈ 1 min 46 s) |
| 15:06:16 | Grafana responde: `/grafana/api/health` → 200, `database: ok`, versión 13.2.4 |

## Comprobaciones HTTPS (desde el Mac, sin credenciales)
- `https://<IP>/` → 302 a `/grafana/`; `/grafana/` → 302 a la pantalla de acceso (título «Grafana»).
- `/zabbix/` y `/zabbix/index.php` → 200 (título «NexoEventos — observabilidad multicloud: Zabbix»).
- TLS 1.3 con certificado autofirmado de la VM; el puerto 80 no responde (cerrado).
- Nginx sirve ambas interfaces; Grafana con base de datos `ok`.

## Lo que NO se pudo comprobar
- `az vm run-command` está bloqueado por la propia VM (`OperationNotAllowed`: extensiones deshabilitadas), así que no se leyó el estado de `zabbix-server`, `zabbix-agent2` ni PostgreSQL por dentro. Que la interfaz de Zabbix cargue no prueba que el servidor esté recolectando.
- Hosts, métricas y antigüedad de los datos de Grafana y Zabbix requieren iniciar sesión (credenciales de la usuaria); no se usaron. Hasta que se vea la hora del último dato en pantalla, los datos del dashboard del 4-nov deben tratarse como **históricos**.

## Costos (tarifas públicas, no verificados con facturación)
VM D2s_v4 encendida ≈ 0,108 USD/h. Con la VM apagada siguen facturando disco, IP estática, Log Analytics e instantánea (≈ 0,33–0,43 USD/día).

## Apagado automático
Existe `shutdown-computevm-vm-nexoeventos-obs` (habilitado, 17:38 UTC = 12:38 hora de Perú, diario). No se modificó. Apagaría la VM mañana 6-nov a las 12:38 (hora de Perú) si sigue encendida.
