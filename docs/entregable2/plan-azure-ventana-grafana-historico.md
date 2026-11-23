# Ventana corta de Azure para capturar los paneles HISTÓRICOS de Grafana (obs. 5) — PROPUESTA 5-nov-2026; nada ejecutado

## ¿Se pueden recuperar las gráficas del 4-nov 20:45–21:30 (Perú) = 5-nov 01:45–02:30 UTC?
**Sí, con la VM encendida unos minutos** (Grafana vive en la VM; apagada no hay interfaz). Evidencia local/configuración:
- **Panel «Azure Monitor: CPU / memoria / red»** (`nexo-azure-vm`, paneles 2–4): consultan **Azure Monitor en el momento** con la identidad administrada; las métricas de plataforma se conservan 93 días con resolución de 1 min, y la ventana ya está guardada aparte (`docs/evidencias/20261105-azure-ventana2/metrica-*.txt`: CPU 2 % → 99–100 % entre 01:48 y 02:12Z → 2 %). Por tanto se pueden volver a dibujar con un rango absoluto.
- **Paneles del agente de Zabbix** (paneles 5–7: CPU, memoria, valores/s): su historial está en el PostgreSQL del **disco de la VM**, que no se tocó (el disco original sigue igual salvo el sello de propiedad). El origen de Zabbix usa historial para rangos < 7 días (`trendsFrom: 7d`). **No se ha confirmado la retención configurada de los ítems** (por defecto de Zabbix: 31 días de historial); se verá al abrir el panel.
- **Zona horaria:** el panel está fijado en **UTC** (`timezone: utc`): los ejes mostrarán 01:45–02:30 y no 20:45–21:30; se puede cambiar a «Navegador» en el selector de tiempo (sin guardar) o indicar la equivalencia en la captura.
- El panel de resumen y las URL de cada ventana no dependen de datos nuevos: los paneles históricos de AWS/OCI son importaciones locales (`work/observability/*.json`).

## URL de la vista (con el rango absoluto; epoch en ms)
- Ventana 2 (carga de CPU del 4-nov Perú): `…/grafana/d/nexo-azure-vm/?orgId=1&from=1793843100000&to=1793845800000` (= 01:45–02:30 UTC del 5-nov).
- Ventana 1 (apagado/encendido de `alerta-vm-up`): `from=1793832000000&to=1793833800000` (22:40–23:10 UTC del 4-nov).
La IP se obtiene con `az network public-ip show …` y no se escribe en los archivos.

## Capturas que tomar (hora y rango visibles; sin contraseñas ni IP)
1. Dashboard «Azure — VM de monitoreo» completo (rango 01:45–02:30 UTC) con la subida de CPU de Azure Monitor y de Zabbix.
2. Los mismos paneles individuales en vista ampliada (tecla `v`): CPU de Azure Monitor, memoria disponible y CPU del agente de Zabbix (legibilidad).
3. «NexoEventos — observabilidad multicloud (resumen)» con el mismo rango (opcional) y, en Zabbix, *Monitoring → Problems* de esa hora (opcional).

## ¿Basta una ventana de 15–20 min?
**Sí, si ya tienes preparados el inicio de sesión y la URL**; recomiendo **20 min con tope de 30**.
| Min | Acción |
|---|---|
| 0 | Prechequeos (IP = NSG, VM `deallocated`, respaldos intactos); apagado remoto a +30 min y vigilante `--minutes 30`; `az vm start` (≈ 15 s) |
| 1–3 | Servicios arrancan (Grafana responde hacia el minuto 3–5); yo aviso |
| 4–14 | Tú inicias sesión, abres la URL y capturas (≈ 10 min) |
| 15 | `az vm deallocate` (la alerta `alerta-vm-up` pasará a Fired ≈ 2–3 min después y enviará un correo; no se espera) |
**Coste:** 20 min × 0,108 USD/h ≈ **0,04 USD** (techo de 30 min ≈ 0,05 USD). Sin carga de CPU, sin SSH necesaria (basta HTTPS 443 desde tu IP; la clave SSH no hace falta). Efectos: llegarán 1–2 correos de `alerta-vm-up` (Resolved al cabo de ≈ 10 min si la ventana dura tanto; Fired tras apagar).
**Riesgos:** tu IP puede cambiar (se comprueba al inicio); el panel de Zabbix puede no tener datos si la retención fuera menor (poco probable); Grafana tarda unos minutos en consultar Azure Monitor tras el arranque.

## Cierre de la observación 5
Se marca cerrada solo con **capturas reales** aportadas por la usuaria: dashboard de Azure con rango absoluto de la prueba (CPU 2 % → ≈ 100 % → 2 %) e indicación clara de que son datos históricos recuperados el día de la captura (no en vivo durante la carga).
