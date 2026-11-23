# Ventana de Azure del 28-oct-2026 — resultado (VM de monitoreo con Zabbix, PostgreSQL 16 y Grafana)
Todas las mediciones «en vivo» de este directorio se tomaron **en la VM de Azure** durante la ventana (13:42–15:05 UTC). Los datos de **AWS y OCI son históricos** (ejecuciones anteriores, cargados con `history.push` conservando su marca de tiempo) y están etiquetados así. Sin IP, correo, claves ni identificadores (enmascarados: `<ip>`, `<fqdn>`, `<id>`).

## Línea de tiempo (UTC)
| Hora | Hecho |
|---|---|
| 13:38:53–13:42:09 | `terraform apply` del plan guardado: 8 creados, 0 cambiados, 0 destruidos (sin `-auto-approve`) |
| 13:42 | Watchdog armado (17:42:27Z) y auto-shutdown de Azure verificado (`Enabled`, 17:38 UTC) |
| 13:43 | `azure-verify-deploy.sh --stage vm`: 18/18 tras corregir el propio verificador; `terraform plan` = *No changes* |
| ~13:55 | Huella SSH verificada por dos canales; clave cargada por la operadora |
| 13:57–14:20 | Ansible: 3 intentos (2 fallidos por causas documentadas) → `ok=67, failed=0` |
| 14:23:18 | Inicio de la carga controlada de CPU (2 procesos, 22 min) |
| 14:41:12 | **Azure Monitor dispara `alerta-vm-cpu` (Sev2)** |
| 14:45:18 | Fin de la carga; CPU vuelve a ~1,4 % desde las 14:47 |
| 15:02:59 | La alerta de Azure pasa a *Resolved* |
| 15:05:52 | `az vm deallocate` → `PowerState/deallocated` (verificado con Azure y con `azure-verify-clean.sh --expect vm-off`) |

## Pruebas aprobadas (con evidencia)
- Infraestructura: VM D2s_v4, Trusted Launch, SSD E6 64 GiB, IP estática, NSG solo 22/443 desde la IP /32 del operador, Monitoring Reader, 3 alertas, apagado automático habilitado (`verificacion-vm.txt`, `nsg-reglas.txt`, `vm-propiedades.json`, `terraform-*`).
- SSH: huella ED25519/ECDSA/RSA igual en la consola serie y en la red; `known_hosts` dedicado y `StrictHostKeyChecking=yes`.
- Servicios en la VM: PostgreSQL 16.15, Zabbix 7.0.32 (server y agent2), Nginx 1.24, Grafana 13.2.4, PHP-FPM, UFW; SSH endurecido (`servicios-y-seguridad-vm.txt`).
- HTTPS: TLS 1.3, HSTS, certificado autofirmado cuya huella desde fuera coincide con la del archivo en la VM; puertos 80, 3000, 5432, 10050 y 10051 no alcanzables (`acceso-https-y-puertos.txt`).
- Identidad administrada: token por el servicio de metadatos con la salida a Internet denegada; lee las 3 métricas (30 puntos cada una); una sola asignación de rol visible; escritura → 403 (`identidad-administrada.txt`).
- Métricas reales: `az monitor metrics list` (`azure-monitor-metricas.txt`, `azure-monitor-cpu-prueba-carga.txt`) y consultas de Grafana a Azure Monitor con la identidad administrada (`grafana.txt`: CPU y memoria, 30 puntos).
- Zabbix: 5 hosts; sondas de AWS V1 (apagado) detectan «NexoEventos no disponible» (High) a las 14:23:31Z; trigger de CPU 5 min después de la carga; **mensaje entregado** del problema de CPU (14:29:41) y de sus 2 recuperaciones (14:45:24 y 14:45:41) en el registro local (`zabbix-alertas-entrega.txt`, `alertas-zabbix-registro-local.txt`).
- Alerta de Azure Monitor: disparada y resuelta con tiempos medidos (`azure-alerta-cpu-disparada.json`).
- Históricos **(no son Azure)**: 468 puntos de AWS (k6 + failover Multi-AZ) y 734 de OCI, 1 202 en total, leídos con `history.get` (`carga-historica.txt`, `zabbix-estado-api.json`).
- Umbrales y plantillas exportadas (`zabbix-umbrales-triggers.txt`, `zabbix-plantillas-exportadas.yaml`).

## Tiempos de la alerta de CPU de Azure Monitor
| Medida | Valor |
|---|---|
| Inicio de la carga | 14:23:18Z |
| Primer minuto de la métrica > 80 % | 14:25Z (la métrica llega con ~2 min de retraso) |
| Media móvil de 15 min > 80 % (umbral de la regla) | desde el minuto 14:36Z (81,9 %) |
| Alerta disparada | 14:41:12Z → **17 min 54 s** desde el inicio de la carga (~4–5 min tras cruzar el umbral: cadencia de evaluación de 5 min) |
| Fin de la carga / media < 80 % | 14:45:18Z / ~14:49Z |
| Alerta resuelta | 15:02:59Z (≈ 14 min tras bajar la media del 80 %) |
**Correo del grupo de acción (estado a las 15:30Z del 28-oct):**
- *Verificación del receptor:* el primer enlace de verificación llegó caducado («This verification link is no longer valid»). Un guardado idéntico del grupo no generó correo; quitar y volver a añadir el receptor `operador-0` (15:23:28–15:23:31Z, misma dirección y ajustes, grupo y alertas intactos, Terraform sin cambios) **sí generó el correo nuevo, que la operadora recibió y confirmó**. El receptor y las 3 alertas siguen habilitados.
- *Entrega de una alerta real por correo:* **NO comprobada.** Azure registró el disparo de `alerta-vm-cpu` (14:41:12Z), pero esa alerta se emitió con el correo aún sin verificar y no se ha confirmado que ningún correo de alerta llegara al buzón. Se intentó una prueba de notificación del grupo de acción (`test-notifications create`, tipo `metricstaticthreshold`, una sola vez, 15:28:57Z): **Azure la rechazó con «Free subscription not supported»** (no disponible en suscripciones gratuitas), así que no se envió correo ni hay estado por receptor. Queda pendiente una nueva alerta real (p. ej. la de CPU) con el receptor ya verificado, y no se declara entregada hasta ver el correo en el buzón.

## Pruebas con fallo o con límite (sin maquillar)
| Qué | Resultado |
|---|---|
| Alertas de Zabbix por la caída de AWS V1 (14:23) | **Fallaron** (5 alertas con «No message defined for media type») porque el medio no tenía plantillas; corregido a las 14:27–14:28. No se reenviaron, así que esa alerta concreta NO se entregó; la entrega quedó demostrada con el problema y las recuperaciones de CPU |
| Ansible intentos 1 y 2 | Fallaron por Nginx sin recargar (handlers); corregido (`flush_handlers`, `force_handlers`, espera del puerto 443) |
| Verificadores propios | Dos errores del script de verificación de despliegue y dos del de huella SSH; corregidos, sin afectar la infraestructura |
| Certificado | Autofirmado (la huella se verificó aparte); no es una CA pública |
| `zabbix_server` (10051) y `zabbix_agent2` (10050) | Escuchan en todas las interfaces (inaccesibles por NSG y UFW); endurecimiento pendiente: enlazar el agente a 127.0.0.1 |

## Pendientes para el Entregable 2
- Capturas de pantalla de los paneles de Grafana y Zabbix (la interfaz solo es accesible con la VM encendida y requiere que la operadora inicie sesión: no se escriben contraseñas por ella). Requiere otra ventana.
- Confirmar la recepción del correo de la alerta de Azure (buzón de la operadora).
- Alertas de memoria (`alerta-vm-mem`) y disponibilidad (`alerta-vm-up`): creadas y con métricas válidas, pero **no disparadas** (no se provocó memoria baja ni caída de la VM).
- Fallo controlado contra AWS V1 encendido (detección y recuperación) y exportación de CloudWatch (retención de 1 min ≈ 15 días: antes del ~3-nov); requieren el laboratorio de AWS, con autorización.
- Correo desde Zabbix (SMTP) no configurado: se usa el registro local.
- Destrucción de la VM / de la base: solo con autorización adicional.

## Costos
Estimación de la ventana (VM encendida 1,40 h): cómputo ≈ 0,15 USD + disco/IP ≈ 0,02 = **≈ 0,17 USD**. **Cost Management aún no muestra consumo** (0 filas; suele tardar 24–48 h): son cifras estimadas con tarifas públicas, no observadas. Siguen facturando tras desasignar: disco E6 de 64 GiB + montaje, IP pública estática (≈ 0,012 USD/h ≈ 0,30 USD/día, ≈ 9 USD/mes si se dejara); Log Analytics (tope 0,2 GB/día, dentro de la capa gratuita), las 3 alertas y el apagado automático (sin cargo). **La programación de auto-shutdown sigue activa a las 17:38 UTC cada día**: en una próxima ventana hay que fijar una hora nueva (`azure-set-shutdown-window.sh`) antes del apply o la VM se desasignaría a esa hora.
