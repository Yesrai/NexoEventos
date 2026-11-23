# Plan mínimo de la ventana de Azure — observaciones 3, 5 y 6 (PROPUESTA 4-nov-2026; nada se ha ejecutado)

Solo se leyó Azure (CLI con sesión de la operadora; rol `Owner` en la suscripción «Azure for Students») y se prepararon scripts/documentación. Instantánea saneada: `docs/evidencias/20261104-azure-prechequeo/instantanea-azure.txt` (generada con el nuevo `scripts/observability/azure-alert-snapshot.sh`, solo lectura).

## 1. Estado real
| Obs. | Qué hay | Qué falta |
|---|---|---|
| **3** Correo de una alerta real | `alerta-vm-cpu` (Sev2) se disparó el 28-oct 14:41:12Z y se resolvió 15:02:59Z, **pero con el receptor sin verificar**: no se probó que llegara ningún correo. El receptor del grupo `ag-nexoeventos-obs` está hoy `Enabled` (verificado) | Repetir una alerta real con el receptor verificado y que la operadora confirme el correo (captura recortada) |
| **5** Capturas de Grafana | Grafana 13.2.4 en la VM (`/grafana/` tras Nginx 443), origen Azure Monitor (identidad administrada) y Zabbix; 4 paneles importados y comprobados **por API** (`grafana.txt`), nunca capturados | Capturas reales con métricas de la VM en curso; la VM está apagada |
| **6** `alerta-vm-up` | **Hallazgo nuevo de hoy:** la API de alertas de Azure muestra `alerta-vm-up` (Sev1) **«Fired» el 28-oct 15:08:34Z, ≈ 2 min 40 s después de desasignar la VM (15:05:52Z) y sigue «Fired»** (sin resolver). Es decir, **desasignar la VM sí la dispara** (causa inferida por la coincidencia temporal) y no se resolverá hasta volver a encender | Observar en directo el ciclo completo (resolución al encender, disparo al desasignar) con el receptor verificado y los correos |

Recursos Azure hoy: grupo `rg-nexoeventos-observabilidad` (centralus): VM `vm-nexoeventos-obs` (D2s_v4, Ubuntu 24.04) **deallocated**, disco, NIC, NSG, IP pública estática Standard (asignada, **se factura aunque la VM esté apagada**), VNet, espacio de Log Analytics, grupo de acciones, 3 alertas habilitadas, apagado automático habilitado (**17:38 UTC**). Hay otro grupo `NetworkWatcherRG` (sistema). Credenciales: sesión de `az` activa; secretos de Grafana/Zabbix en `work/ansible-secrets/monitoring/` (no se leen).

## 2. Bloqueos concretos
1. **El NSG no deja entrar a tu IP actual** (la regla `admin-https` apunta a otra IP /32): sin actualizarla no se puede abrir Grafana por 443. Cambio mínimo: `az network nsg rule update` de `admin-https` (solo 443; el 22 no hace falta si la carga se lanza con `az vm run-command`). Requiere tu autorización.
2. **El inicio de sesión en Grafana lo haces tú** (no se escriben contraseñas por ti); las capturas las tomas tú (como las de AWS) y yo las recorto, indexo y enlazo.
3. **No puedo leer tu crédito de Azure for Students** por CLI (Cost Management suele tardar 24–48 h): necesito tu lectura del portal.
4. **El certificado de Grafana/Nginx es autofirmado** (advertencia esperada en el navegador).
5. Sin SMTP en Zabbix: el único correo real es el del grupo de acciones de Azure Monitor (suficiente para las obs. 3 y 6).

## 3. Qué se puede hacer sin y con la VM
| Sin encender la VM (coste 0) | Necesita la VM encendida |
|---|---|
| Lecturas de Azure (hecho) · instantánea con el script nuevo · documentación y criterios · (opcional, **tú** en el portal) «Probar grupo de acciones» en `ag-nexoeventos-obs`: envía un correo de prueba y comprueba el receptor **sin gastar VM**; no cuenta como alerta real (la CLI exigiría escribir tu correo en la orden: no se usa) | Alerta real de CPU y su correo (obs. 3) · capturas de Grafana con datos vivos (obs. 5) · resolución de `alerta-vm-up` al encender y nuevo disparo al desasignar (obs. 6) |

## 4. Ventana mínima propuesta (≈ 70–80 min de VM encendida; límite duro 150 min)
| Min | Acción | Evidencia |
|---|---|---|
| −10 | Tu OK; leer crédito; `azure-alert-snapshot.sh` (antes); armar el vigilante `nohup caffeinate -i -s scripts/observability/azure-vm-watchdog.sh --minutes 150 &`; actualizar `admin-https` a tu IP /32 | Instantánea «antes» (alerta-vm-up `Fired`) |
| 0 | `az vm start` (no hay Terraform ni cambios de configuración) y esperar `running` + HTTPS | Estado de la VM |
| 0–8 | **Obs. 6 (1/2):** `alerta-vm-up` debe pasar de `Fired` a `Resolved` (la métrica vuelve a 1; ≈ 5–8 min) y llegar el correo de resolución | Alerta resuelta + correo (captura) |
| 6 | **Obs. 3:** `az vm run-command invoke` lanza 2 procesos `yes` con tope `timeout 1500 s` (misma lógica que el 28-oct) | Hora de inicio de la carga |
| 10–30 | **Obs. 5:** tú inicias sesión en `https://<IP de la VM>/grafana/` y capturas: panel «Azure — VM de monitoreo» (CPU en subida y memoria) y el resumen multicloud; opcional la UI de Zabbix (host de la VM con su agente) | PNG en `Capturas`; yo los recorto y los indexo |
| ≈ 24–30 | `alerta-vm-cpu` se dispara (el 28-oct tardó 17 min 54 s desde el inicio de la carga) → correo | Alerta `Fired` + correo (captura) |
| ≈ 31 | La carga termina sola (`timeout`) | CPU ≈ 1–2 % |
| ≈ 45 | `alerta-vm-cpu` pasa a `Resolved` (el 28-oct ≈ 14 min después del fin de la carga) → correo opcional | Alerta `Resolved` |
| ≈ 50 | **Obs. 6 (2/2):** `az vm deallocate` y observar ≈ 5 min: `alerta-vm-up` debe volver a `Fired` (≈ 3 min) → correo | Alerta `Fired` + correo |
| ≈ 60 | `azure-verify-clean.sh --expect vm-off`, snapshot «después», cancelar el vigilante | Salida de verificación |
Tiempos sujetos a la latencia de Azure Monitor; si `alerta-vm-cpu` no se dispara en 40 min de carga se declara no concluyente y se apaga (sin prolongar).

## 5. Coste y riesgos
- **Coste incremental estimado:** VM D2s_v4 ≈ 0,096 USD/h × ≈ 1,3 h ≈ **0,13 USD**, más disco/IP ≈ 0,01 USD ⇒ **≈ 0,15 USD**; techo de 150 min ≈ 0,3 USD. (Siguen facturándose cada día, apagada: IP estática ≈ 0,12 USD/día y el disco ≈ 0,2 USD/día aprox.; estimación con tarifas públicas, sin verificar.)
- **Riesgos:** olvidar apagar (mitigado por el vigilante y por el apagado automático de las 17:38 UTC del día siguiente); la IP de la operadora cambia durante la ventana (se pierde el acceso, no se pierde dinero); correos de «Fired/Resolved» de `alerta-vm-up` (3 correos esperados: resolución al encender, disparo al desasignar y CPU) que acaban en spam; el estado «Fired» de `alerta-vm-up` volverá a quedar así al terminar (es el comportamiento actual: se podría documentar o ajustar la regla después, no hoy).
- **Alcance:** solo `az` sobre el grupo `rg-nexoeventos-observabilidad` (+ la regla `admin-https`). **No toca AWS ni OCI.** Zabbix de la VM sondea la URL pública de AWS V1 (solo GET, la RDS sigue detenida: se verá el problema «no disponible», local y esperado). Sin Terraform, sin recursos nuevos.

## 6. Evidencias y criterios de cierre
| Obs. | Se marca CERRADA cuando existen… |
|---|---|
| **3** | (a) alerta de Azure `alerta-vm-cpu` con `monitorCondition=Fired` y hora tras la carga medida, (b) **captura del correo recibido** (remitente de Azure Monitor, regla y hora legibles) y confirmación de la usuaria, (c) la resolución. El correo debe corresponder a una alerta emitida con el receptor `Enabled` |
| **5** | Capturas reales de Grafana con datos **en vivo de la VM** (CPU/memoria con la subida de la carga, origen Azure Monitor y Zabbix sanos, hora visible) y de al menos el panel de Azure y el resumen multicloud; sin contraseñas ni IP; indexadas en `docs/evidencias/capturas/INDICE.md` |
| **6** | Historial de la API de alertas con **dos transiciones reales**: `Fired → Resolved` al encender y `Resolved → Fired` al desasignar, con horas, y los correos recibidos (o la ausencia documentada); conclusión honesta: la regla se dispara con apagados planificados (no distingue un apagado voluntario de una caída) |
Guardar en `docs/evidencias/AAAAMMDD-azure-ventana/`: `instantanea-antes.txt`, `instantanea-despues.txt`, `alertas-api.json` (saneado), `carga-run-command.txt`, `verificacion-vm-off.txt`, capturas PNG y `resultado.md` con límites declarados.

## 7. Autorizaciones que necesito
1. Tu OK a la ventana (fecha y hora) y tu **lectura del crédito de Azure**.
2. `az network nsg rule update` de `admin-https` a tu IP /32 actual (cambio de configuración cloud mínimo).
3. `az vm start` · `az vm run-command invoke` (carga de CPU acotada, 25 min) · `az vm deallocate`.
4. Armar el vigilante local y leer la API de alertas durante la ventana.
5. Que tú inicies sesión en Grafana y tomes las capturas durante la ventana.
