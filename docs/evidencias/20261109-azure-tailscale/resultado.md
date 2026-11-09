# Acceso a Grafana y Zabbix de Azure por Tailscale (8–9-nov-2026, hora de Perú, saneado)

Autorizado paso a paso por la usuaria. VM `vm-nexoeventos-obs` encendida 23:12 → desasignada 00:14 (≈ 1 h 2 min, ≈ 0,11 USD a 0,108 USD/h; tarifa pública, sin verificar con facturación).

## Qué se hizo
1. Se comprobó que la IP pública de la usuaria coincidía con NSG y UFW; se encendió solo la VM; SSH con la clave existente y huella verificada (`work/ssh/azure_known_hosts`).
2. Copia de seguridad de UFW antes de cada cambio (`/var/backups/nexoeventos-ufw-20261109T041656Z` y `…T050122Z-tras-tailscale` en la VM).
3. Tailscale 1.104.5 desde el repositorio oficial (`pkgs.tailscale.com`): clave y archivo del repositorio con el mismo SHA-256 descargados desde el Mac y desde la VM; firma «Good signature from Tailscale Inc.».
4. Primer intento: el Mac estaba en una tailnet ajena (compartida con otras cuentas); la VM no se unió a ella. Se creó/usó una tailnet personal propia y se generó un enlace nuevo; la VM entró en la tailnet personal (solo el Mac y la VM).
5. Ajustes de `tailscale up`: `--hostname=vm-nexoeventos-obs --accept-dns=false --netfilter-mode=off` (así UFW decide qué entra por `tailscale0`; con el modo por defecto Tailscale acepta todo el tráfico de esa interfaz saltándose UFW) y `--advertise-tags=tag:obs`.
6. Política de acceso de la tailnet (guardada por la usuaria tras la vista previa con pruebas): solo la cuenta propietaria llega a `tag:obs` y solo al puerto 443. La VM verificó que su filtro de paquetes contiene esa única regla (origen: el Mac; destino: la VM, puerto 443).
7. Un problema de «handshake» tras etiquetar (`no UDP or DERP addr`) se resolvió desconectando y reconectando Tailscale en el Mac; no se reinició `tailscaled`.
8. Regla de UFW añadida solo para la interfaz (IPv4 e IPv6): `ufw allow in on tailscale0 to any port 443 proto tcp`. Las reglas 22 y 443 por IP pública, el NSG y SSH no se modificaron.

## Verificaciones
- Por Tailscale (`100.91.65.26`): Grafana `/grafana/api/health` → 200 (versión 13.2.4, base de datos `ok`); pantalla de acceso de Grafana → 200 con redirecciones dentro de la IP de Tailscale; Zabbix `/zabbix/` → 200 (certificado autofirmado, advertencia esperada).
- Puertos: por Tailscale solo conecta el 443; 22, 80, 3000, 5432, 10050, 10051 y 8080 no conectan y no llegan a `tailscale0` (0 paquetes). Por la IP pública, el NSG sigue permitiendo solo 22 y 443 desde la IP autorizada (80, 3000, 5432 y 10051 bloqueados).
- Nginx registró 32 peticiones a `/grafana/` y `/zabbix/` con origen la IP privada de Tailscale del Mac (`100.64.53.54`) entre las 05:01 y las 05:11 UTC; incluyen accesos a `/grafana/login` y `/zabbix/` con respuesta 200.

## Límite declarado: acceso «desde otra red»
**No está confirmado.** Al verificarlo (00:12) la IP pública del Mac era `<IP-autorizada>`, la misma que permiten el NSG y UFW (red `192.168.0.x`). Los accesos por Tailscale están comprobados, pero no se demostró que se hicieran desde el Internet del celular. La prueba desde otra red queda pendiente para el próximo encendido.

## Estado final
VM `deallocated` (00:14); IP pública estática conservada; apagado automático habilitado (17:38 UTC = 12:38 hora de Perú); NSG sin cambios; bloqueos de borrado de discos intactos (3); Tailscale, UFW y servicios (nginx, grafana-server, zabbix-server, zabbix-agent2, postgresql, ufw, tailscaled) activos y habilitados al arranque al momento de apagar.

## Pendientes (registrados)
1. **Prueba de acceso desde otra red** (Internet del celular) en el próximo encendido: comprobar antes con `curl -s https://api.ipify.org` que la IP pública sea distinta de la autorizada, abrir `https://100.91.65.26/grafana/` y `/zabbix/` con Tailscale conectado y anotar el resultado.
2. Confirmar en la consola de Tailscale que la VM figura con `tag:obs` y con la caducidad de clave deshabilitada; activar *Device approval* y MFA.
3. Captura de la interfaz de Zabbix (Monitoring → Hosts y Latest data), ahora posible por Tailscale (Anexo B del informe).
